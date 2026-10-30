"""Shared by the spreadsheet importers and the preview. Standard library only, so the importer runs without Django."""
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

# ST_Xstring (ECMA-376 22.4.2.4): "_xHHHH_" writes a character XML cannot carry; "_x005F_" is a literal underscore.
# A match consumes its closing underscore ("_x005F_x0041_" reads "_x0041_"); the first branch joins a surrogate pair.
_ESCAPE = re.compile(
    r"_x([Dd][89ABab][0-9A-Fa-f]{2})__x([Dd][C-Fc-f][0-9A-Fa-f]{2})_"
    r"|_x([0-9A-Fa-f]{4})_"
)


def _decode(match):
    high, low, unit = match.groups()
    if high:
        return chr(0x10000 + ((int(high, 16) - 0xD800) << 10) + (int(low, 16) - 0xDC00))
    code = int(unit, 16)
    # A NUL cannot be stored in a PostgreSQL text column and a lone surrogate cannot be encoded as UTF-8:
    # both stay as written instead of turning an import into a server error.
    if code == 0 or 0xD800 <= code <= 0xDFFF:
        return match.group(0)
    return chr(code)


def unescape_xstring(text):
    """Decode _xHHHH_ escapes: exactly four hex digits and a lowercase x; look-alikes are left as written."""
    if not text or "_x" not in text:
        return text
    return _ESCAPE.sub(_decode, text)


class XmlRefused(ValueError):
    """A part refused before it is parsed: it declares a DOCTYPE or has more elements than a document needs."""


class _ReachedRoot(Exception):
    pass


# More tags than this is a bomb, not a document: a few megabytes of empty rows expand to a tree many times larger.
MAX_ELEMENTS = 400_000


def safe_fromstring(raw):
    """``ElementTree.fromstring`` for an uploaded part: refuses a DOCTYPE (entity expansion) and a bomb of tags.
    A malformed part is left for ``ElementTree`` to report."""
    if raw.count(b"<") > MAX_ELEMENTS:
        raise XmlRefused("The part has more elements than a document needs.")
    # A DOCTYPE can only precede the root: expat stops there, reading encodings (UTF-16 too) as the real parse will.
    probe = expat.ParserCreate()

    def refuse(*_args):
        raise XmlRefused("The part declares a DOCTYPE, which is not accepted.")

    def reached_root(*_args):
        raise _ReachedRoot

    probe.StartDoctypeDeclHandler = refuse
    probe.StartElementHandler = reached_root
    try:
        probe.Parse(raw, True)
    except _ReachedRoot:
        pass
    except expat.ExpatError:
        pass
    return ET.fromstring(raw)
