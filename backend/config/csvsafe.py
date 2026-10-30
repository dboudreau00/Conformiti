CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(row):
    """Prefix any cell a spreadsheet could read as a formula. The stripped value decides, since Excel skips leading
    whitespace; the value is otherwise returned unchanged, because an export is evidence."""
    out = []
    for value in row:
        if isinstance(value, str) and value.strip()[:1] in CSV_DANGEROUS and value.strip():
            value = "'" + value
        out.append(value)
    return out
