"""Custom-emoji "pill" letters (A-Z in green / yellow / grey), stored in a small JSON file."""
from __future__ import annotations

import json
import os
from pathlib import Path

from utils.logger import get_logger

log = get_logger(__name__)
COLORS = "GYB"
FALLBACK = {"G": "🟩", "Y": "🟨", "B": "⬛"}
COLOR_NAMES = {"G": "green (correct)", "Y": "yellow (wrong spot)", "B": "grey/red (absent)"}


class EmojiStore:
    def __init__(self, path: Path, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.data: dict[str, dict[str, str]] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = {c: dict(raw.get(c, {})) for c in COLORS}
        except (OSError, ValueError):
            self.data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def ready(self) -> bool:
        return self.enabled and all(len(self.data.get(c, {})) == 26 for c in COLORS)

    def status(self) -> dict[str, int]:
        return {c: len(self.data.get(c, {})) for c in COLORS}

    def set_color(self, color: str, ids: list[str]) -> None:
        if color not in COLORS or len(ids) != 26 or not all(i.isdigit() for i in ids):
            raise ValueError("need exactly 26 numeric custom emoji ids (A-Z)")
        self.data[color] = {chr(97 + i): ids[i] for i in range(26)}
        self._save()

    def clear(self) -> None:
        self.data = {}
        self.path.unlink(missing_ok=True)

    def tile(self, letter: str, color: str) -> str:
        eid = self.data[color][letter.lower()]
        return f'<tg-emoji emoji-id="{eid}">{FALLBACK[color]}</tg-emoji>'

    def row(self, word: str, pattern: str) -> str:
        return " ".join(self.tile(ch, c) for ch, c in zip(word, pattern))
