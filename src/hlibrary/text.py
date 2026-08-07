from __future__ import annotations

import re
import unicodedata

_NATURAL_PARTS = re.compile(r"([0-9]+)")


def normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold().strip()


def search_terms(value: str) -> list[str]:
    return [term for part in value.split(",") if (term := normalize_text(part))]


def natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isascii() and part.isdigit() else normalize_text(part)
        for part in _NATURAL_PARTS.split(value)
        if part
    )
