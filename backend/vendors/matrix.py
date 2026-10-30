"""Reads a vendor's responsibility matrix whatever its layout: headers are scored into column roles, then cells are
read. Anything unrecognised or unmatched is reported, never guessed and never silently dropped."""
import re

from governance.risk_import import parse_upload  # stdlib CSV/XLSX, zip-bomb guarded

# Lower-cased; the longest matching phrase wins, so list order does not matter.
HEADER_HINTS = {
    "control": ["control id", "control ref", "control reference", "requirement id",
                "requirement number", "requirement #", "req #", "req id", "req no",
                "requirement", "control", "req", "ref", "reference", "id", "criteria", "clause"],
    "responsibility": ["responsibility", "responsible party", "responsible", "who is responsible",
                       "owner", "ownership", "allocation", "assignment", "party"],
    "provider_statement": ["provider statement", "provider responsibility", "service provider statement",
                           "tpsp statement", "tpsp responsibility", "vendor statement",
                           "vendor responsibility", "supplier statement", "provider notes",
                           "what the provider does", "service provider", "provider", "tpsp",
                           "vendor", "supplier"],
    "customer_statement": ["customer statement", "customer responsibility", "merchant statement",
                           "merchant responsibility", "client statement", "client responsibility",
                           "your responsibility", "cuec", "complementary user entity controls",
                           "customer notes", "what the customer does", "customer", "merchant",
                           "client", "you", "user entity"],
    "provider_mark": ["provider", "tpsp", "vendor", "supplier", "service provider"],
    "customer_mark": ["customer", "merchant", "client", "you", "user entity"],
}

PROVIDER_WORDS = {"provider", "tpsp", "vendor", "supplier", "service provider", "sp", "us"}
CUSTOMER_WORDS = {"customer", "merchant", "client", "you", "user", "user entity", "entity"}
SHARED_WORDS = {"shared", "both", "joint", "jointly", "split", "co-owned", "provider and customer",
                "customer and provider"}
# "\u2014" is an input token (the em dash a vendor's cell may hold), not copy: keep it escaped.
NA_WORDS = {"n/a", "na", "not applicable", "none", "-", "\u2014", "not in scope", "out of scope"}
MARK_YES = {"x", "✓", "✔", "yes", "y", "true", "1", "responsible", "r"}
MARK_NO = {"no", "n", "false", "0", "✗", "✘"}


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _looks_like_marks(values):
    """Every non-blank cell is a tick, no or n/a, with at least one tick or no: an all-"N/A" column is not marks."""
    vals = [v for v in (_norm(v) for v in values) if v]
    return (bool(vals)
            and all(v in MARK_YES or v in MARK_NO or v in NA_WORDS for v in vals)
            and any(v in MARK_YES or v in MARK_NO for v in vals))


def _column(body, i):
    return [line[i] if i < len(line) else "" for line in body]


def _set_role(report, index, role, confidence=None):
    for col in report:
        if col["index"] == index:
            col["role"] = role
            if confidence is not None:
                col["confidence"] = confidence


def _promote_mark_columns(assigned, report, body):
    """Re-read a statement column as a mark column when its cells are all ticks (storing "X" as a statement would be
    wrong). A prose responsibility column, when present, stays authoritative."""
    if "responsibility" in assigned:
        return
    pairs = (("provider_statement", "provider_mark"), ("customer_statement", "customer_mark"))
    for stmt, mark in pairs:
        i = assigned.get(stmt)
        if i is not None and mark not in assigned and _looks_like_marks(_column(body, i)):
            assigned[mark] = assigned.pop(stmt)
            _set_role(report, i, mark)
    # An unnamed column full of ticks (a vendor header we did not know) is one party's marks: it pairs with the other
    # side's mark column, or with its statement column when that is empty.
    taken = set(assigned.values())
    unnamed = [c for c in report
               if c["role"] is None and c["index"] not in taken and _looks_like_marks(_column(body, c["index"]))]
    if not unnamed:
        return
    for mark, other, other_stmt in (("provider_mark", "customer_mark", "customer_statement"),
                                    ("customer_mark", "provider_mark", "provider_statement")):
        if mark in assigned:
            continue
        blank_other = other_stmt in assigned and not any(_norm(v) for v in _column(body, assigned[other_stmt]))
        if other in assigned or blank_other:
            if other not in assigned:
                assigned[other] = assigned.pop(other_stmt)
                _set_role(report, assigned[other], other)
            col = unnamed.pop(0)
            assigned[mark] = col["index"]
            _set_role(report, col["index"], mark, 40)
            break


def normalise_ref(text):
    """Reduce a control reference to the form the register uses (``Req 8.3.6`` -> ``8.3.6``)."""
    t = str(text or "").strip()
    t = re.sub(r"(?i)^(pci(\s*dss)?|req(uirement)?|requirement|control|ctrl|clause)[\s.:#-]*", "", t)
    t = t.strip().rstrip(".").strip()
    t = re.sub(r"\s+", "", t)
    # ISO annex controls are written A.5.15 in the register; accept A5.15 / A-5.15.
    m = re.match(r"(?i)^a[.\-]?(\d+)[.\-](\d+)$", t)
    if m:
        return f"A.{m.group(1)}.{m.group(2)}"
    return t.upper() if re.match(r"^[a-z]", t) else t


def _score_header(name, hints):
    h = _norm(name)
    best = 0
    for phrase in hints:
        if h == phrase:
            return 100 + len(phrase)
        if phrase in h:
            best = max(best, 50 + len(phrase))
    return best


def _is_vendor_header(h, vendor):
    """Does a header name the vendor, in full, by its initials ("AWS") or by its first word ("Amazon")?"""
    if not vendor:
        return False
    if vendor in h:
        return True
    words = [w for w in vendor.split() if w]
    tokens = set(h.replace("/", " ").replace("-", " ").split())
    if len(words) >= 2 and "".join(w[0] for w in words) in tokens:
        return True
    return len(words[0]) >= 4 and words[0] in tokens


def recognise_headers(header_row, vendor_name=""):
    """Returns ``({role: column_index}, report)``; the per-column report is what the UI shows."""
    vendor = _norm(vendor_name)
    columns = [str(h or "").strip() for h in header_row]
    assigned, report = {}, []
    scores = []
    for i, name in enumerate(columns):
        h = _norm(name)
        if not h:
            continue
        row_scores = {role: _score_header(name, hints) for role, hints in HEADER_HINTS.items()}
        if _is_vendor_header(h, vendor):
            row_scores["provider_statement"] = max(row_scores["provider_statement"], 120)
            row_scores["provider_mark"] = max(row_scores["provider_mark"], 110)
        scores.append((i, name, row_scores))

    candidates = sorted(
        ((s, role, i, name) for i, name, rs in scores for role, s in rs.items() if s),
        key=lambda x: -x[0],
    )
    taken_cols = set()
    for s, role, i, name in candidates:
        if role in assigned or i in taken_cols:
            continue
        assigned[role] = i
        taken_cols.add(i)
        report.append({"column": name, "index": i, "role": role, "confidence": min(100, s) })

    # Marks only count when no prose responsibility column was found; the prose column is authoritative.
    if "responsibility" in assigned:
        assigned.pop("provider_mark", None)
        assigned.pop("customer_mark", None)
    for i, name in enumerate(columns):
        if i not in taken_cols and name:
            report.append({"column": name, "index": i, "role": None, "confidence": 0})
    # Once confirmed the report is stored as the vendor's layout, so it keeps the file's own column order.
    report.sort(key=lambda c: c["index"])
    return assigned, report


def recognise_responsibility(value, provider_mark=None, customer_mark=None):
    """A prose value or a pair of marks -> provider, customer, shared or not_applicable; None when unrecognised."""
    v = _norm(value)
    if v:
        if v in NA_WORDS:
            return "not_applicable"
        if any(w in v for w in SHARED_WORDS):
            return "shared"
        has_p = any(re.search(rf"\b{re.escape(w)}\b", v) for w in PROVIDER_WORDS)
        has_c = any(re.search(rf"\b{re.escape(w)}\b", v) for w in CUSTOMER_WORDS)
        if has_p and has_c:
            return "shared"
        if has_p:
            return "provider"
        if has_c:
            return "customer"
        return None
    p = _norm(provider_mark) in MARK_YES
    c = _norm(customer_mark) in MARK_YES
    if p and c:
        return "shared"
    if p:
        return "provider"
    if c:
        return "customer"
    if _norm(provider_mark) in NA_WORDS or _norm(customer_mark) in NA_WORDS:
        return "not_applicable"
    return None


def recognise(filename, data, vendor_name="", control_refs=None):
    """Parse an uploaded matrix into ``{"columns", "rows", "summary"}``; writes nothing.
    ``control_refs`` is ``{normalised_ref: control_id}`` for the framework the user picked."""
    header, body = _split(parse_upload(filename, data))
    assigned, report = recognise_headers(header, vendor_name)
    _promote_mark_columns(assigned, report, body)
    if "control" not in assigned:
        return {
            "columns": report, "rows": [],
            "summary": {"error": "No column looks like a control or requirement reference. "
                                 "Rename the column to 'Control' or 'Requirement' and try again."},
        }
    control_refs = control_refs or {}
    rows, matched, unmatched, unrecognised = [], 0, 0, 0
    vendor = _norm(vendor_name)
    # parse_upload stops one row past its cap instead of raising, so truncation is detected by length.
    from governance.risk_import import MAX_ROWS
    truncated = len(body) > MAX_ROWS
    body = body[:MAX_ROWS]

    def cell(line, role):
        i = assigned.get(role)
        return line[i] if i is not None and i < len(line) else ""

    for n, line in enumerate(body, start=2):
        raw_ref = str(cell(line, "control") or "").strip()
        if not raw_ref:
            continue
        ref = normalise_ref(raw_ref)
        control_id = control_refs.get(ref) or control_refs.get(ref.lower())
        prose = _norm(cell(line, "responsibility"))
        responsibility = recognise_responsibility(
            prose, cell(line, "provider_mark"), cell(line, "customer_mark"),
        )
        if responsibility is None and prose and _is_vendor_header(prose, vendor):
            responsibility = "provider"
        provider_statement = str(cell(line, "provider_statement") or "").strip()
        customer_statement = str(cell(line, "customer_statement") or "").strip()
        if _norm(provider_statement) in NA_WORDS:
            provider_statement = ""
        if _norm(customer_statement) in NA_WORDS:
            customer_statement = ""
        # Marks that say N/A lose to a statement that says who does the work.
        if responsibility == "not_applicable" and not prose and (provider_statement or customer_statement):
            responsibility = None
        # Statements alone imply the split; an unrecognised prose value is reported, not guessed around.
        if responsibility is None and not prose and (provider_statement or customer_statement):
            if provider_statement and customer_statement:
                responsibility = "shared"
            elif provider_statement:
                responsibility = "provider"
            else:
                responsibility = "customer"
        if control_id:
            matched += 1
        else:
            unmatched += 1
        if responsibility is None:
            unrecognised += 1
        rows.append({
            "line": n,
            "raw_ref": raw_ref,
            "ref": ref,
            "control_id": control_id,
            "matched": bool(control_id),
            "responsibility": responsibility,
            "provider_statement": provider_statement[:4000],
            "customer_statement": customer_statement[:4000],
        })
    return {
        "columns": report,
        "rows": rows,
        "summary": {
            "total": len(rows), "matched": matched, "unmatched": unmatched,
            "unrecognised_responsibility": unrecognised, "truncated": truncated,
            "row_limit": MAX_ROWS,
        },
    }


ROLES = {"control", "responsibility", "provider_statement", "customer_statement",
         "provider_mark", "customer_mark"}
RESPONSIBILITY_LABEL = {"provider": "Provider", "customer": "Customer", "shared": "Shared",
                        "not_applicable": "N/A"}


def clean_layout(columns, file_name="", framework=""):
    """Validate a column layout the client sends back; the stored form, or None when nothing is usable."""
    from django.utils import timezone

    out = []
    for position, col in enumerate(list(columns)[:50]):
        if not isinstance(col, dict):
            continue
        name = str(col.get("column") or col.get("name") or "").strip()[:120]
        role = col.get("role")
        if not name:
            continue
        try:
            index = int(col.get("index", position))
        except (TypeError, ValueError):
            index = position
        out.append({"name": name, "role": role if role in ROLES else None, "index": index})
    out.sort(key=lambda c: c["index"])
    for c in out:
        c.pop("index", None)
    if not any(c["role"] == "control" for c in out):
        return None
    return {"columns": out, "file": file_name, "framework": framework,
            "saved_at": timezone.now().isoformat()}


def _mark(resp, sides):
    if resp in sides:
        return "X"
    return "N/A" if resp == "not_applicable" else ""


def render_layout(layout, rows):
    """Rows under the vendor's own headers: marks get an X (both sides when shared); unknown columns stay blank."""
    columns = layout.get("columns") or []
    header = [c["name"] for c in columns]
    lines = []
    for r in rows:
        resp = r.get("responsibility")
        line = []
        for c in columns:
            role = c.get("role")
            if role == "control":
                line.append(r.get("control_id", ""))
            elif role == "responsibility":
                line.append(RESPONSIBILITY_LABEL.get(resp, ""))
            elif role == "provider_statement":
                line.append(r.get("provider_statement", ""))
            elif role == "customer_statement":
                line.append(r.get("customer_statement", ""))
            elif role == "provider_mark":
                line.append(_mark(resp, ("provider", "shared")))
            elif role == "customer_mark":
                line.append(_mark(resp, ("customer", "shared")))
            else:
                line.append("")
        lines.append(line)
    return header, lines


def _split(parsed):
    """parse_upload returns rows with the header first; accept a tuple too."""
    if isinstance(parsed, tuple) and len(parsed) == 2:
        return parsed
    rows = list(parsed or [])
    return (rows[0] if rows else []), rows[1:]
