"""Helpers for the two code paths that read a workbook's text: the spreadsheet
importers (governance/risk_import.py) and the in-browser preview
(documents/preview.py). Standard library only, so the importer still runs
without Django.
"""
import re

# ST_Xstring (ECMA-376 part 1, 22.4.2.4). XML cannot carry most control
# characters, so a workbook writes one as _xHHHH_, the four hex digits of its
# UTF-16 code unit: Excel does it for the carriage return inside a cell
# ("_x000D_"). A literal "_xHHHH_" in the text has its first underscore
# written as _x005F_, so it survives a round trip. The scan runs left to
# right and a match consumes its closing underscore, which is what makes
# "_x005F_x0041_" read as the literal "_x0041_". The first alternative joins a
# high and a low surrogate written one after the other into one character.
_ESCAPE = re.compile(
    r"_x([Dd][89ABab][0-9A-Fa-f]{2})__x([Dd][C-Fc-f][0-9A-Fa-f]{2})_"
    r"|_x([0-9A-Fa-f]{4})_"
)


def _decode(match):
    high, low, unit = match.groups()
    if high:
        return chr(0x10000 + ((int(high, 16) - 0xD800) << 10) + (int(low, 16) - 0xDC00))
    code = int(unit, 16)
    # A NUL cannot be stored in a PostgreSQL text column, and a lone surrogate
    # cannot be encoded as UTF-8 at all, so both stay as written rather than
    # turn an import into a server error.
    if code == 0 or 0xD800 <= code <= 0xDFFF:
        return match.group(0)
    return chr(code)


def unescape_xstring(text):
    """The text a workbook meant, with its _xHHHH_ escapes decoded.

    Exactly four hex digits, either case, and a lowercase x: anything else
    that merely looks like an escape ("_x12_", "_xZZZZ_") is left as it is."""
    if not text or "_x" not in text:
        return text
    return _ESCAPE.sub(_decode, text)
