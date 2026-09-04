"""Spreadsheet-safe CSV cells.

Characters a spreadsheet may interpret as the start of a formula. Any
user-controlled value beginning with one of them is prefixed with a quote so
an export can never execute as a formula when opened in Excel/Sheets.
"""
CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(row):
    out = []
    for value in row:
        if isinstance(value, str) and value and value[0] in CSV_DANGEROUS:
            value = "'" + value
        out.append(value)
    return out
