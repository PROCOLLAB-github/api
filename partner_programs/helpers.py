def date_to_iso(date: str) -> str:
    d, m, y = tuple(map(int, date.strip().split("-")))
    return f"{y:04d}-{m:02d}-{d:02d}"
