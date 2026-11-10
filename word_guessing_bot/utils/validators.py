"""Input validation helpers."""
from __future__ import annotations

import re

_GUESS_RE = re.compile(r"[A-Za-z]+")
VALID_LENGTHS = (4, 5, 6, 7)


def clean_guess(text: str | None) -> str | None:
    """Return a lowercase alphabetic single word of 4-7 letters, else None."""
    if not text:
        return None
    text = text.strip()
    if not _GUESS_RE.fullmatch(text):
        return None
    if len(text) not in VALID_LENGTHS:
        return None
    return text.lower()


def parse_user_id(text: str | None) -> int | None:
    if not text:
        return None
    text = text.strip()
    return int(text) if re.fullmatch(r"-?\d{1,15}", text) else None
