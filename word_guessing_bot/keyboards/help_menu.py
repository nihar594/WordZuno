from __future__ import annotations

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup

SECTIONS = {
    "game": "🎮 Game",
    "player": "👤 Player",
    "lb": "🏆 Leaderboard",
    "group": "👥 Group",
    "daily": "📅 Daily",
    "info": "ℹ️ Info",
}


def help_keyboard(current: str = "home") -> InlineKeyboardMarkup:
    keys = list(SECTIONS)
    rows = []
    for i in range(0, len(keys), 3):
        rows.append([B(("« " + SECTIONS[k] + " »") if k == current else SECTIONS[k], callback_data=f"help:{k}")
                     for k in keys[i:i + 3]])
    if current != "home":
        rows.append([B("🏠 Home", callback_data="help:home")])
    return InlineKeyboardMarkup(rows)


RICH_SECTIONS = ("howto", "scores", "group", "other", "admin")


def rich_help_keyboard(s, active: str = "howto", show_admin: bool = False) -> InlineKeyboardMarkup:
    def b(label: str, key: str) -> B:
        on = active == key
        return B(f"« {label} »" if on else label, callback_data=f"help:{key}", **({"style": "primary"} if on else {}))

    third = [b("Other Commands", "other")]
    rows = [[b("How to Play", "howto"), b("Leaderboard & Scores", "scores")],
            [b("Group Settings", "group")] + third]
    if s.github_url:
        rows[1].append(B("GitHub Repo", url=s.github_url))
    if show_admin:
        rows.append([b("👑 Admin Commands", "admin")])
    rows.append([B("📢 Updates", url=s.updates_url), B("💗 Donate", url=s.donate_url, style="success"),
                 B("💬 Discussion", url=s.discussion_url)])
    return InlineKeyboardMarkup(rows)
