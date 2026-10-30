"""Preview of stored evidence with no HTML in the pipeline: Office files are parsed here, with the standard library,
into a vocabulary the front end renders. PDFs and images stream inline only once their first bytes prove the type."""
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

from .ooxml import MAX_ELEMENTS, XmlRefused, safe_fromstring, unescape_xstring

MAX_PARAGRAPHS = 3000
MAX_TABLE_ROWS = 500
MAX_SHEET_ROWS = 1000
MAX_SHEET_COLS = 64
MAX_SHEETS = 12
MAX_UNZIPPED_BYTES = 40 * 1024 * 1024
MAX_PART_BYTES = 12 * 1024 * 1024
MAX_TEXT_BYTES = 512 * 1024

PDF_MAGIC = b"%PDF-"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
GIF_MAGICS = (b"GIF87a", b"GIF89a")
BMP_MAGIC = b"BM"
WEBP_RIFF = b"RIFF"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class PreviewError(Exception):
    """The file cannot be previewed; the message is safe to show to the user."""


def kind_for(name, head):
    """How a file may be shown: its magic bytes decide, and the extension never overrides them."""
    ext = posixpath.splitext(name or "")[1].lower()
    if head.startswith(PDF_MAGIC):
        return "pdf"
    if head.startswith(PNG_MAGIC) or head.startswith(JPEG_MAGIC) or head.startswith(GIF_MAGICS):
        return "image"
    if head.startswith(WEBP_RIFF) and head[8:12] == b"WEBP":
        return "image"
    if head.startswith(BMP_MAGIC) and ext == ".bmp":
        return "image"
    if head.startswith(b"PK\x03\x04"):
        if ext == ".docx":
            return "docx"
        if ext == ".xlsx":
            return "xlsx"
        return None
    if ext in (".txt", ".md", ".csv", ".log", ".json"):
        return "text"
    return None


def image_content_type(head):
    if head.startswith(PNG_MAGIC):
        return "image/png"
    if head.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if head.startswith(GIF_MAGICS):
        return "image/gif"
    if head.startswith(BMP_MAGIC):
        return "image/bmp"
    return "image/webp"


def _open_zip(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PreviewError("The file is not a valid Office document.")
    total = sum(i.file_size for i in zf.infolist())
    if total > MAX_UNZIPPED_BYTES:
        raise PreviewError("The document is too large to preview. Download it instead.")
    return zf


def _read_xml(zf, member):
    """Parse one part with two bounds: bytes are read up to a ceiling the zip header cannot override, and a part with an
    absurd tag count is refused before ElementTree builds a tree out of it."""
    try:
        with zf.open(member) as fh:
            raw = fh.read(MAX_PART_BYTES + 1)
    except KeyError:
        return None
    except (zipfile.BadZipFile, OSError, EOFError):
        raise PreviewError("The document's contents could not be read.")
    if len(raw) > MAX_PART_BYTES:
        raise PreviewError("The document is too large to preview. Download it instead.")
    if raw.count(b"<") > MAX_ELEMENTS:
        raise PreviewError("The document is too complex to preview. Download it instead.")
    try:
        return safe_fromstring(raw)
    except (ET.ParseError, XmlRefused):
        raise PreviewError("The document's contents could not be read.")


def _runs(paragraph):
    out = []
    for run in paragraph.iter(f"{W}r"):
        props = run.find(f"{W}rPr")
        bold = props is not None and props.find(f"{W}b") is not None
        italic = props is not None and props.find(f"{W}i") is not None
        text = ""
        for node in run:
            if node.tag == f"{W}t":
                text += node.text or ""
            elif node.tag == f"{W}tab":
                text += "\t"
            elif node.tag == f"{W}br":
                text += "\n"
        if text:
            out.append({"t": text, "b": bold, "i": italic})
    return out


def _para_style(paragraph):
    props = paragraph.find(f"{W}pPr")
    if props is None:
        return "", None
    style = props.find(f"{W}pStyle")
    name = style.get(f"{W}val", "") if style is not None else ""
    num = props.find(f"{W}numPr")
    level = None
    if num is not None:
        lvl = num.find(f"{W}ilvl")
        level = int(lvl.get(f"{W}val", "0")) if lvl is not None else 0
    return name, level


def _heading_level(style_name):
    m = re.match(r"(?i)heading\s*(\d)", style_name or "")
    if m:
        return int(m.group(1))
    if style_name and style_name.lower() == "title":
        return 1
    return None


def _table(tbl):
    rows = []
    for tr in tbl.findall(f"{W}tr"):
        cells = []
        for tc in tr.findall(f"{W}tc"):
            text = "\n".join(
                "".join(r["t"] for r in _runs(p)) for p in tc.findall(f"{W}p")
            ).strip()
            cells.append(text)
        rows.append(cells)
        if len(rows) >= MAX_TABLE_ROWS:
            break
    return {"type": "table", "rows": rows, "truncated": len(rows) >= MAX_TABLE_ROWS}


def render_docx(data):
    zf = _open_zip(data)
    root = _read_xml(zf, "word/document.xml")
    if root is None:
        raise PreviewError("This is not a Word document.")
    body = root.find(f"{W}body")
    blocks, count = [], 0
    for node in (body if body is not None else root):
        if node.tag == f"{W}p":
            runs = _runs(node)
            style, level = _para_style(node)
            if not runs and level is None:
                continue
            heading = _heading_level(style)
            if heading:
                blocks.append({"type": "heading", "level": min(heading, 4),
                               "text": "".join(r["t"] for r in runs)})
            elif level is not None:
                blocks.append({"type": "list_item", "level": min(level, 4), "runs": runs})
            else:
                blocks.append({"type": "paragraph", "runs": runs})
        elif node.tag == f"{W}tbl":
            blocks.append(_table(node))
        count += 1
        if count >= MAX_PARAGRAPHS:
            blocks.append({"type": "notice", "text": "Preview truncated. Download for the full document."})
            break
    return {"kind": "docx", "blocks": blocks}


def _shared_strings(zf):
    root = _read_xml(zf, "xl/sharedStrings.xml")
    if root is None:
        return []
    out = []
    for si in root.findall(f"{S}si"):
        out.append(unescape_xstring("".join(t.text or "" for t in si.iter(f"{S}t"))))
    return out


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref or "")
    n = 0
    for ch in (letters.group(0) if letters else "A"):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _sheet_parts(zf):
    wb = _read_xml(zf, "xl/workbook.xml")
    rels = _read_xml(zf, "xl/_rels/workbook.xml.rels")
    if wb is None:
        raise PreviewError("This is not an Excel workbook.")
    targets = {}
    if rels is not None:
        for rel in rels.findall(f"{PKG_REL}Relationship"):
            targets[rel.get("Id")] = rel.get("Target", "")
    sheets = []
    for sheet in wb.iter(f"{S}sheet"):
        rid = sheet.get(f"{R}id")
        target = targets.get(rid, "")
        member = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        if member.startswith("xl//"):
            member = "xl/" + member[4:]
        sheets.append((sheet.get("name", "Sheet"), member))
        if len(sheets) >= MAX_SHEETS:
            break
    return sheets


def _cell_value(cell, shared):
    kind = cell.get("t")
    v = cell.find(f"{S}v")
    if kind == "s":
        try:
            return shared[int(v.text)] if v is not None else ""
        except (ValueError, IndexError):
            return ""
    if kind == "inlineStr":
        return unescape_xstring("".join(t.text or "" for t in cell.iter(f"{S}t")))
    if kind == "b":
        return "TRUE" if (v is not None and v.text == "1") else "FALSE"
    text = v.text if v is not None and v.text is not None else ""
    # A formula that returns text carries it in <v> with the same escapes.
    return unescape_xstring(text) if kind == "str" else text


def render_xlsx(data):
    zf = _open_zip(data)
    shared = _shared_strings(zf)
    sheets_out = []
    for name, member in _sheet_parts(zf):
        root = _read_xml(zf, member)
        if root is None:
            continue
        rows, truncated = [], False
        for row in root.iter(f"{S}row"):
            cells = {}
            for c in row.findall(f"{S}c"):
                idx = _col_index(c.get("r", "A1"))
                if idx >= MAX_SHEET_COLS:
                    continue
                cells[idx] = _cell_value(c, shared)
            width = max(cells) + 1 if cells else 0
            rows.append([cells.get(i, "") for i in range(width)])
            if len(rows) >= MAX_SHEET_ROWS:
                truncated = True
                break
        sheets_out.append({"name": name, "rows": rows, "truncated": truncated})
    return {"kind": "xlsx", "sheets": sheets_out}


def render_text(data, name=""):
    raw = data[:MAX_TEXT_BYTES]
    text = raw.decode("utf-8", "replace")
    ext = posixpath.splitext(name or "")[1].lower()
    if ext == ".csv":
        import csv
        rows = list(csv.reader(io.StringIO(text)))[:MAX_SHEET_ROWS]
        return {"kind": "xlsx", "sheets": [{"name": "CSV", "rows": rows,
                                            "truncated": len(data) > MAX_TEXT_BYTES}]}
    return {"kind": "text", "text": text, "truncated": len(data) > MAX_TEXT_BYTES}


def render(file_field, name):
    """Preview of an Office/text file, or ``{"kind": "pdf"|"image"}`` for streamable ones; raises PreviewError.
    ``name`` is the document title, often typed without an extension; the stored file's name decides the kind then."""
    if not posixpath.splitext(name or "")[1]:
        name = posixpath.basename(str(getattr(file_field, "name", "") or "")) or name
    with file_field.open("rb") as fh:
        head = fh.read(64)
        kind = kind_for(name, head)
        if kind in ("pdf", "image"):
            return {"kind": kind}
        if kind is None:
            raise PreviewError("No preview is available for this file type. Download it instead.")
        fh.seek(0)
        data = fh.read(MAX_UNZIPPED_BYTES + 1)
        if len(data) > MAX_UNZIPPED_BYTES:
            raise PreviewError("The file is too large to preview. Download it instead.")
    if kind == "docx":
        return render_docx(data)
    if kind == "xlsx":
        return render_xlsx(data)
    return render_text(data, name)
