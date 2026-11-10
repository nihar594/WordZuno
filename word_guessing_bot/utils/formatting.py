"""Text formatting helpers (Telegram HTML)."""
from __future__ import annotations

import html
from datetime import date, datetime, timezone

TILES = {"G": "🟩", "Y": "🟨", "B": "⬛"}


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def clip(text: str, n: int = 22) -> str:
    text = (text or "").strip() or "Player"
    return text if len(text) <= n else text[: n - 1] + "…"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def fmt_pts(n: int) -> str:
    return f"{int(n):,}"


def fullwidth(word: str) -> str:
    """ASCII letters -> full-width capitals so they line up under emoji tiles."""
    return "".join(chr(ord(c) - 0x41 + 0xFF21) if "A" <= c <= "Z" else c for c in word.upper())


def render_guess_row(word: str, pattern: str) -> str:
    tiles = " ".join(TILES[c] for c in pattern)
    letters = " ".join(fullwidth(ch) for ch in word)
    return f"{tiles}\n{letters}"


PILL_BUDGET = 90  # Telegram caps entities per message; older rows fall back to plain tiles


def render_board(game, guesses, emoji=None) -> str:
    title = "📅 Daily challenge" if game.game_mode == "daily" else f"{game.word_length}-letter mode"
    head = f"<b>{title}</b>\n\n<i>{len(guesses)}/{game.max_guesses} guesses</i>\n"
    budget, parts = PILL_BUDGET, []
    for g in reversed(guesses):  # newest rows get pills first
        if emoji is not None and emoji.ready and budget >= len(g.guessed_word):
            parts.append(emoji.row(g.guessed_word, g.result))
            budget -= len(g.guessed_word)
        else:
            parts.append(render_guess_row(g.guessed_word, g.result))
    rows = "\n".join(reversed(parts))
    return f"{head}\n{rows}" if rows else head


def mode_command(game) -> str:
    return "/daily" if game.game_mode == "daily" else f"/new{game.word_length}"


def next_reset_text() -> str:
    now = datetime.now(timezone.utc)
    nxt = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    secs = int(86400 - (now - nxt).total_seconds())
    return f"{secs // 3600}h {secs % 3600 // 60}m"


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()
