"""Spreadsheet-safe CSV cells.

Characters a spreadsheet may interpret as the start of a formula. Any
user-controlled value beginning with one of them is prefixed with a quote so
an export can never execute as a formula when opened in Excel/Sheets.
"""
CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(row):
    """Prefix any cell a spreadsheet could read as a formula.

    The first character of the stripped value decides. Checking the raw first
    character would let "\n=cmd" and " =1+1" through, because Excel ignores
    leading whitespace when it decides what a cell is (L-7). The value itself
    is returned unchanged apart from the prefix: an export is evidence, and
    trimming it would alter the record.
    """
    out = []
    for value in row:
        if isinstance(value, str) and value.strip()[:1] in CSV_DANGEROUS and value.strip():
            value = "'" + value
        out.append(value)
    return out
