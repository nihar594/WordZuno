"""Central configuration. Everything comes from environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


def _path(name: str, default: str) -> Path:
    p = Path(_str(name, default))
    return p if p.is_absolute() else BASE_DIR / p


def _ids(raw: str) -> frozenset[int]:
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return frozenset(out)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    bot_name: str
    bot_username: str
    admin_ids: frozenset[int]
    updates_url: str
    discussion_url: str
    donate_url: str
    db_path: Path
    words_path: Path
    answers_path: Path
    banner_path: Path
    logo_path: Path
    log_dir: Path
    log_level: str
    max_guesses: int
    daily_max_guesses: int
    default_length: int
    hints_per_game: int
    game_timeout_hours: int
    board_mode: str
    points_win: int
    daily_bonus: int
    daily_streak_bonus: int
    daily_streak_cap: int
    streak_bonus: int
    streak_min: int
    multiplayer_bonus: int
    daily_length: int
    health_port: int
    emoji_path: Path
    custom_emoji: bool
    board_style: str
    scoring_mode: str
    reactions: bool
    meanings_path: Path
    github_url: str

    @property
    def bot_link(self) -> str:
        return f"https://t.me/{self.bot_username}"


def load_settings() -> Settings:
    username = _str("BOT_USERNAME", "WordZunoBot").lstrip("@")
    link = f"https://t.me/{username}"
    mode = _str("BOARD_MODE", "resend").lower()
    return Settings(
        bot_token=_str("BOT_TOKEN", ""),
        bot_name=_str("BOT_NAME", "Word Zuno"),
        bot_username=username,
        admin_ids=_ids(os.getenv("ADMIN_IDS", "")),
        updates_url=_str("UPDATES_URL", link),
        discussion_url=_str("DISCUSSION_URL", link),
        donate_url=_str("DONATE_URL", link),
        db_path=_path("DB_PATH", "storage/wordzuno.db"),
        words_path=_path("WORDS_PATH", "data/words.txt"),
        answers_path=_path("ANSWERS_PATH", "data/answers.txt"),
        banner_path=_path("BANNER_PATH", "assets/banner.png"),
        logo_path=_path("LOGO_PATH", "assets/logo.png"),
        log_dir=_path("LOG_DIR", "logs"),
        log_level=_str("LOG_LEVEL", "INFO").upper(),
        max_guesses=max(1, _int("MAX_GUESSES", 30)),
        daily_max_guesses=max(1, _int("DAILY_MAX_GUESSES", 30)),
        default_length=_int("DEFAULT_LENGTH", 5) if _int("DEFAULT_LENGTH", 5) in (4, 5, 6, 7) else 5,
        hints_per_game=max(0, _int("HINTS_PER_GAME", 2)),
        game_timeout_hours=max(1, _int("GAME_TIMEOUT_HOURS", 24)),
        board_mode=mode if mode in ("resend", "edit") else "resend",
        points_win=_int("POINTS_WIN", 15),
        daily_bonus=_int("DAILY_BONUS", 10),
        daily_streak_bonus=_int("DAILY_STREAK_BONUS", 2),
        daily_streak_cap=max(1, _int("DAILY_STREAK_CAP", 7)),
        streak_bonus=_int("STREAK_BONUS", 0),
        streak_min=max(1, _int("STREAK_MIN", 3)),
        multiplayer_bonus=_int("MULTIPLAYER_BONUS", 0),
        daily_length=5,
        health_port=_int("PORT", 0),
        emoji_path=_path("EMOJI_PATH", "") if os.getenv("EMOJI_PATH") else _path("DB_PATH", "storage/wordzuno.db").parent / "emoji.json",
        board_style=_str("BOARD_STYLE", "rich").lower() if _str("BOARD_STYLE", "rich").lower() in ("rich", "text") else "rich",
        scoring_mode=_str("SCORING_MODE", "fixed").lower() if _str("SCORING_MODE", "fixed").lower() in ("fixed", "remaining") else "fixed",
        reactions=_str("REACTIONS", "on").lower() not in ("off", "0", "false", "no"),
        github_url=_str("GITHUB_URL", ""),
        meanings_path=_path("MEANINGS_PATH", "data/meanings.json"),
        custom_emoji=_str("CUSTOM_EMOJI", "on").lower() not in ("off", "0", "false", "no"),
    )
