"""Application-wide container stored in application.bot_data['ctx']."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from config import Settings
from database.db import Database
from services.game_service import GameService
from services.leaderboard_service import LeaderboardService
from services.scoring import Scoring
from services.word_service import WordService
from utils.emoji import EmojiStore
from utils.ratelimit import Dedup, RateLimiter


@dataclass
class AppContext:
    settings: Settings
    db: Database
    words: WordService
    scoring: Scoring
    games: GameService
    boards: LeaderboardService
    emoji: EmojiStore
    started_at: float = field(default_factory=time.time)
    maintenance: bool = False
    banned: set[int] = field(default_factory=set)
    rate_guess: RateLimiter = field(default_factory=lambda: RateLimiter(12, 10))
    rate_cmd: RateLimiter = field(default_factory=lambda: RateLimiter(6, 8))
    rate_cb: RateLimiter = field(default_factory=lambda: RateLimiter(8, 8))
    seen_messages: Dedup = field(default_factory=Dedup)
    seen_callbacks: Dedup = field(default_factory=Dedup)
    user_cache: dict[int, tuple] = field(default_factory=dict)
    rich_failures: int = 0

    @property
    def rich_enabled(self) -> bool:
        return self.settings.board_style == "rich" and self.rich_failures < 3

    async def load_state(self) -> None:
        rows = await self.db.fetchall("SELECT user_id FROM users WHERE is_banned=1")
        self.banned = {r["user_id"] for r in rows}
        row = await self.db.fetchone("SELECT value FROM bot_settings WHERE key='maintenance'")
        self.maintenance = bool(row and row["value"] == "1")

    async def set_maintenance(self, on: bool) -> None:
        self.maintenance = on
        await self.db.execute(
            "INSERT INTO bot_settings(key,value) VALUES('maintenance',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("1" if on else "0",))


def build_context(settings: Settings) -> AppContext:
    db = Database(settings.db_path)
    words = WordService(settings.words_path, settings.answers_path, settings.meanings_path)
    scoring = Scoring(settings)
    return AppContext(settings, db, words, scoring, GameService(db, words, scoring, settings), LeaderboardService(db),
                      EmojiStore(settings.emoji_path, settings.custom_emoji))
