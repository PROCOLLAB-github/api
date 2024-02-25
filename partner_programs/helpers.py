def date_to_iso(date: str) -> str:
    day, month, year = tuple(map(int, date.strip().split("-")))
    return f"{year:04d}-{month:02d}-{day:02d}"
