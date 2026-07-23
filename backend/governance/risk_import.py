"""
CSV / XLSX ingestion for the risk register.

Parsing is deliberately dependency-free (stdlib ``csv``, ``zipfile`` and
``xml.etree``) so the importer works everywhere the app runs. An .xlsx file is
a zip of XML; we read the first worksheet plus the shared-strings table, which
covers files produced by Excel, Google Sheets and LibreOffice.

This module is Django-free on purpose: it turns bytes into normalized row
dicts plus per-row issues. Resolving owners/controls and creating rows happens
in the view, so the parsing layer can be tested standalone.
"""
import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

MAX_FILE_BYTES = 2 * 1024 * 1024        # request-level guard (2 MB)
MAX_UNZIPPED_BYTES = 20 * 1024 * 1024   # zip-bomb guard for xlsx
MAX_ROWS = 1000
MAX_TEXT = 20000

FIELDS = [
    "title", "description", "status", "risk_type", "treatment",
    "likelihood", "impact", "owner", "control",
    "due_date", "identified_on", "jira_key", "mitigation_plan", "note",
]

HEADER_ALIASES = {
    "title": "title", "risk": "title", "risk title": "title", "name": "title",
    "description": "description", "details": "description", "summary": "description",
    "status": "status", "state": "status",
    "type": "risk_type", "risk type": "risk_type", "category": "risk_type", "source": "risk_type",
    "treatment": "treatment", "response": "treatment", "risk response": "treatment",
    "likelihood": "likelihood", "probability": "likelihood",
    "impact": "impact", "severity": "impact",
    "owner": "owner", "assigned to": "owner", "assignee": "owner", "risk owner": "owner",
    "control": "control", "control id": "control", "related control": "control",
    "due": "due_date", "due date": "due_date", "target date": "due_date",
    "remediation due": "due_date",
    "identified": "identified_on", "identified on": "identified_on",
    "date identified": "identified_on", "raised": "identified_on",
    "jira": "jira_key", "jira key": "jira_key", "ticket": "jira_key", "issue": "jira_key",
    "mitigation": "mitigation_plan", "mitigation plan": "mitigation_plan",
    "plan": "mitigation_plan", "remediation": "mitigation_plan",
    "remediation plan": "mitigation_plan",
    "note": "note", "notes": "note", "comment": "note", "comments": "note",
}

SCALE_WORDS = {
    "very low": 1, "rare": 1, "minimal": 1,
    "low": 2, "unlikely": 2, "minor": 2,
    "medium": 3, "moderate": 3, "possible": 3,
    "high": 4, "likely": 4, "major": 4,
    "very high": 5, "almost certain": 5, "critical": 5, "severe": 5,
}

STATUS_ALIASES = {
    "open": "open", "new": "open", "identified": "open",
    "in progress": "mitigating", "in-progress": "mitigating",
    "mitigating": "mitigating", "remediating": "mitigating",
    "in remediation": "mitigating",
    "accepted": "accepted", "risk accepted": "accepted",
    "closed": "closed", "done": "closed", "resolved": "closed",
    "complete": "closed", "completed": "closed",
}

TYPE_ALIASES = {
    "control gap": "control_gap", "control_gap": "control_gap", "gap": "control_gap",
    "audit finding": "audit_finding", "audit_finding": "audit_finding",
    "finding": "audit_finding", "audit": "audit_finding",
    "pentest": "pentest", "pen test": "pentest", "penetration test": "pentest",
    "vendor": "vendor", "third party": "vendor", "third-party": "vendor",
    "supplier": "vendor",
    "incident": "incident",
    "other": "other",
}

TREATMENT_ALIASES = {
    "mitigate": "mitigate", "reduce": "mitigate", "remediate": "mitigate",
    "accept": "accept", "tolerate": "accept",
    "transfer": "transfer", "share": "transfer",
    "avoid": "avoid", "terminate": "avoid",
}

_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# --------------------------------------------------------------------------
# Low-level readers: bytes -> list of rows (each row a list of strings)
# --------------------------------------------------------------------------
def _read_csv(data):
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    # A single oversized cell makes csv raise csv.Error ("field larger than
    # field limit"), which is NOT a ValueError — surface it as one so the view
    # returns a clean 400 instead of a 500.
    rows = []
    try:
        for row in csv.reader(io.StringIO(text), dialect):
            rows.append([(cell or "").strip() for cell in row])
            if len(rows) > MAX_ROWS + 1:
                break
    except csv.Error as exc:
        raise ValueError(f"Could not parse the CSV file: {exc}")
    return rows


def _col_index(ref):
    """'B7' -> 1 (zero-based column index from a cell reference)."""
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return max(idx - 1, 0)


def _cell_text(cell, shared):
    """Extract a cell's value as a string, whatever its storage type."""
    t = cell.get("t", "")
    if t == "s":  # shared string
        v = cell.find(f"{_XLSX_NS}v")
        try:
            return shared[int(v.text)] if v is not None and v.text is not None else ""
        except (ValueError, IndexError):
            return ""
    if t == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{_XLSX_NS}t"))
    if t == "b":
        v = cell.find(f"{_XLSX_NS}v")
        return "TRUE" if v is not None and v.text == "1" else "FALSE"
    v = cell.find(f"{_XLSX_NS}v")  # numbers, dates-as-serials, formula results
    return (v.text or "").strip() if v is not None and v.text else ""


def _read_xlsx(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Not a valid .xlsx file.")
    if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES:
        raise ValueError("Spreadsheet is too large to import.")

    sheet_names = sorted(
        n for n in zf.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)
    )
    if not sheet_names:
        raise ValueError("No worksheet found in the .xlsx file.")

    # Malformed XML inside an otherwise-valid zip raises ET.ParseError (a
    # SyntaxError subclass, not ValueError) — convert it so the view returns a
    # clean 400 rather than a 500.
    try:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter(f"{_XLSX_NS}si"):
                shared.append("".join(node.text or "" for node in si.iter(f"{_XLSX_NS}t")))

        root = ET.fromstring(zf.read(sheet_names[0]))
    except ET.ParseError:
        raise ValueError("The .xlsx file is corrupt or unreadable.")
    rows = []
    for row_el in root.iter(f"{_XLSX_NS}row"):
        cells = {}
        fallback = 0
        for cell in row_el.findall(f"{_XLSX_NS}c"):
            ref = cell.get("r")
            idx = _col_index(ref) if ref else fallback
            fallback = idx + 1
            cells[idx] = _cell_text(cell, shared).strip()
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
        else:
            rows.append([])
        if len(rows) > MAX_ROWS + 1:
            break
    return rows


def parse_upload(filename, data):
    """Dispatch on extension. Returns rows or raises ValueError with a
    user-safe message."""
    name = (filename or "").lower()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File is larger than the 2 MB import limit.")
    if name.endswith(".csv") or name.endswith(".txt"):
        return _read_csv(data)
    if name.endswith(".xlsx"):
        return _read_xlsx(data)
    raise ValueError("Unsupported file type — upload a .csv or .xlsx file.")


# --------------------------------------------------------------------------
# Normalization: raw rows -> canonical record dicts + issues
# --------------------------------------------------------------------------
def _norm_header(h):
    return re.sub(r"\s+", " ", (h or "").strip().strip("*").lower())


def map_headers(header_row):
    """Map each column to a canonical field (or None). Unknown columns are
    ignored so people can import their existing registers unchanged."""
    return [HEADER_ALIASES.get(_norm_header(h)) for h in header_row]


def _norm_scale(value, field, row_n, issues):
    v = (value or "").strip().lower()
    if not v:
        return None
    if re.fullmatch(r"\d+(\.0+)?", v):
        n = int(float(v))
        if 1 <= n <= 5:
            return n
        issues.append({"row": row_n, "field": field,
                       "message": f"{field} must be 1-5; got {value!r}"})
        return None
    if v in SCALE_WORDS:
        return SCALE_WORDS[v]
    issues.append({"row": row_n, "field": field,
                   "message": f"Unrecognized {field} {value!r} (use 1-5 or low/medium/high)"})
    return None


def _norm_choice(value, aliases, field, row_n, issues, default=None):
    v = re.sub(r"\s+", " ", (value or "").strip().lower())
    if not v:
        return default
    if v in aliases:
        return aliases[v]
    issues.append({"row": row_n, "field": field,
                   "message": f"Unrecognized {field} {value!r} — using default"})
    return default


def _excel_serial_to_date(n):
    # Excel's day 1 is 1900-01-01 with the fictitious 1900 leap day, so the
    # standard epoch trick is 1899-12-30. Plausible range only (1955-2079).
    if not (20000 <= n <= 65700):
        return None
    return date(1899, 12, 30) + timedelta(days=int(n))


def _norm_date(value, field, row_n, issues):
    v = (value or "").strip()
    if not v:
        return None
    # Excel date-time cells carry a fractional serial (e.g. 45658.5 = midday);
    # truncating to the integer day yields the correct date.
    if re.fullmatch(r"\d+(\.\d+)?", v):
        d = _excel_serial_to_date(int(float(v)))
        if d:
            return d
    for fmt in (None, "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y"):
        try:
            if fmt is None:
                return date.fromisoformat(v[:10])
            from datetime import datetime as _dt
            return _dt.strptime(v, fmt).date()
        except ValueError:
            continue
    issues.append({"row": row_n, "field": field,
                   "message": f"Could not parse date {value!r} (use YYYY-MM-DD)"})
    return None


def normalize(rows):
    """
    rows: raw string rows including the header row.
    Returns (records, issues, error).
      records: list of canonical dicts with a "row" key (1-based file row).
      issues:  non-fatal warnings, row-tagged.
      error:   fatal, e.g. no header / no Title column.
    """
    issues = []
    if not rows:
        return [], [], "The file is empty."
    header = map_headers(rows[0])
    if "title" not in header:
        return [], [], ("Could not find a Title column. Recognized headers include: "
                        "Title, Description, Status, Type, Likelihood, Impact, Owner, "
                        "Control, Due date, Jira, Mitigation plan, Note.")

    records = []
    for offset, raw in enumerate(rows[1:], start=2):
        if len(records) >= MAX_ROWS:
            issues.append({"row": offset, "field": "",
                           "message": f"Stopped at the {MAX_ROWS}-row import limit."})
            break
        if not any((c or "").strip() for c in raw):
            continue
        rec = {f: "" for f in FIELDS}
        for i, field in enumerate(header):
            if field and i < len(raw):
                rec[field] = (raw[i] or "").strip()

        title = rec["title"][:255].strip()
        if not title:
            issues.append({"row": offset, "field": "title",
                           "message": "Row skipped — no title."})
            continue

        records.append({
            "row": offset,
            "title": title,
            "description": rec["description"][:MAX_TEXT],
            "status": _norm_choice(rec["status"], STATUS_ALIASES, "status", offset, issues, default="open"),
            "risk_type": _norm_choice(rec["risk_type"], TYPE_ALIASES, "type", offset, issues, default="other"),
            "treatment": _norm_choice(rec["treatment"], TREATMENT_ALIASES, "treatment", offset, issues, default="mitigate"),
            "likelihood": _norm_scale(rec["likelihood"], "likelihood", offset, issues),
            "impact": _norm_scale(rec["impact"], "impact", offset, issues),
            "owner": rec["owner"].strip(),
            "control": rec["control"].strip(),
            "due_date": _norm_date(rec["due_date"], "due date", offset, issues),
            "identified_on": _norm_date(rec["identified_on"], "identified on", offset, issues),
            "jira_key": rec["jira_key"][:40].strip(),
            "mitigation_plan": rec["mitigation_plan"][:MAX_TEXT],
            "note": rec["note"][:MAX_TEXT],
        })
    return records, issues, None
