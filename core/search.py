import re


def unicode_literal_pattern(value):
    """Match literal text without relying on the database's Unicode case rules."""
    return "".join(
        "(?:"
        + "|".join(
            re.escape(variant) for variant in sorted({char, char.lower(), char.upper()})
        )
        + ")"
        for char in value
    )
