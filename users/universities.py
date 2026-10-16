"""University directory search; profile education remains an independent text snapshot."""

import re
import unicodedata


def normalize_university_search(value):
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return " ".join(re.findall(r"\w+", value))
