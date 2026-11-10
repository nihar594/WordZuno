"""Plain dataclasses mapped from database rows."""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class Player:
    user_id: int
    name: str
    username: str | None = None


@dataclass
class Game:
    game_id: int
    chat_id: int
    game_mode: str
    word_length: int
    secret_word: str
    status: str
    max_guesses: int
    started_by: int | None
    winner_id: int | None
    daily_date: str | None
    hints_used: int
    board_message_id: int | None
    created_at: str
    last_activity: str
    completed_at: str | None

    @classmethod
    def from_row(cls, row: Any) -> "Game":
        return cls(**{f.name: row[f.name] for f in fields(cls)})

    @property
    def is_daily(self) -> bool:
        return self.game_mode == "daily"


@dataclass
class GuessRow:
    guess_id: int
    game_id: int
    user_id: int
    guessed_word: str
    result: str
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> "GuessRow":
        return cls(**{f.name: row[f.name] for f in fields(cls)})
