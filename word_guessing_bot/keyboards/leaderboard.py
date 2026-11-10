from __future__ import annotations

from telegram import InlineKeyboardButton as _B, InlineKeyboardMarkup

from config import Settings


def cd(scope: str, period: str, length: int, page: int = 1) -> str:
    return f"lb|{scope}|{period}|{length}|{page}"


def leaderboard_keyboard(s: Settings, scope: str, period: str, length: int, page: int, pages: int) -> InlineKeyboardMarkup:
    def sel(label: str, on: bool) -> str:
        return f"« {label} »" if on else label

    def B(text, **kw):  # selected buttons (text starts with «) are shown in blue
        if text.startswith("«"):
            kw["style"] = "primary"
        return _B(text, **kw)

    rows = [
        [B(sel("Global", scope == "g"), callback_data=cd("g", period, length)),
         B("🔄", callback_data=cd(scope, period, length, page)),
         B(sel("This chat", scope == "c"), callback_data=cd("c", period, length))],
        [B(sel("Today", period == "t"), callback_data=cd(scope, "t", length)),
         B(sel("This week", period == "w"), callback_data=cd(scope, "w", length)),
         B(sel("This month", period == "m"), callback_data=cd(scope, "m", length))],
        [B(sel("This year", period == "y"), callback_data=cd(scope, "y", length)),
         B(sel("All time", period == "a"), callback_data=cd(scope, "a", length))],
        [B(sel(f"{n} letters", length == n), callback_data=cd(scope, period, 0 if length == n else n))
         for n in (4, 5, 6, 7)],
    ]
    if pages > 1:
        rows.append([
            B("◀️ Prev", callback_data=cd(scope, period, length, max(1, page - 1))),
            B(f"{page}/{pages}", callback_data="noop"),
            B("Next ▶️", callback_data=cd(scope, period, length, min(pages, page + 1))),
        ])
    rows.append([B("📢 Updates", url=s.updates_url), B("💗 Donate", url=s.donate_url, style="success"),
                 B("💬 Discussion", url=s.discussion_url)])
    return InlineKeyboardMarkup(rows)
