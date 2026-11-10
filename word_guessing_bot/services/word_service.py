"""Dictionary loading, validation and secret word selection."""
from __future__ import annotations

import asyncio
import random
from pathlib import Path

from utils.logger import get_logger
from utils.validators import VALID_LENGTHS

log = get_logger(__name__)


class WordService:
    def __init__(self, words_path: Path, answers_path: Path, meanings_path: Path | None = None) -> None:
        self.meanings_path = Path(meanings_path) if meanings_path else None
        self._meanings: dict[str, dict] = {}
        self.words_path = Path(words_path)
        self.answers_path = Path(answers_path)
        self._valid: dict[int, frozenset[str]] = {}
        self._answers: dict[int, tuple[str, ...]] = {}
        self.load()

    @staticmethod
    def _read(path: Path) -> list[str]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            w = line.strip().lower()
            if w.isascii() and w.isalpha() and len(w) in VALID_LENGTHS:
                out.append(w)
        return out

    def load(self) -> None:
        words = self._read(self.words_path)
        answers = self._read(self.answers_path) or words
        if not words and not answers:
            raise RuntimeError(f"No words found in {self.words_path}")
        valid_sets, answer_lists = {}, {}
        for n in VALID_LENGTHS:
            v = {w for w in words if len(w) == n} | {w for w in answers if len(w) == n}
            a = sorted({w for w in answers if len(w) == n})
            if not a:
                a = sorted(v)
            valid_sets[n] = frozenset(v)
            answer_lists[n] = tuple(a)
        self._valid, self._answers = valid_sets, answer_lists  # atomic swap
        self._meanings = self._load_meanings()
        log.info("words loaded", extra={"ctx": {n: len(self._valid[n]) for n in VALID_LENGTHS}})

    def _load_meanings(self) -> dict[str, dict]:
        import json
        if not self.meanings_path or not self.meanings_path.exists():
            return {}
        try:
            return json.loads(self.meanings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("could not read meanings file")
            return {}

    def meaning_block(self, word: str) -> str:
        """Telegram-HTML blockquote with pronunciation / meaning / example, or '' when unknown."""
        from utils.formatting import esc
        d = self._meanings.get(word.lower())
        if not d or not (d.get("meaning") or d.get("pronunciation")):
            return ""
        parts = []
        if d.get("pronunciation"):
            parts.append(f"<b>{esc(word.capitalize())}</b> <code>{esc(d['pronunciation'])}</code>")
        if d.get("meaning"):
            parts.append(f"<b>Meaning</b>: {esc(d['meaning'])}")
        if d.get("example"):
            parts.append(f"<b>Example</b>: {esc(d['example'])}")
        return "<blockquote>" + "\n".join(parts) + "</blockquote>"

    async def reload(self) -> dict[int, int]:
        await asyncio.to_thread(self.load)
        return self.counts()

    def counts(self) -> dict[int, int]:
        return {n: len(self._valid[n]) for n in VALID_LENGTHS}

    def answer_counts(self) -> dict[int, int]:
        return {n: len(self._answers[n]) for n in VALID_LENGTHS}

    def is_valid(self, word: str) -> bool:
        return word in self._valid.get(len(word), frozenset())

    def random_answer(self, length: int) -> str:
        return random.choice(self._answers[length])
