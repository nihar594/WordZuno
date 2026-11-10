from __future__ import annotations

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup

from config import Settings

SUCCESS = "success"  # green button (needs Telegram app updated after Feb 2026; older apps ignore it)


def start_keyboard(s: Settings) -> InlineKeyboardMarkup:
    add_url = f"{s.bot_link}?startgroup=true&admin=delete_messages+pin_messages"
    return InlineKeyboardMarkup([
        [B("Add me to your Group", url=add_url)],
        [B("Updates", url=s.updates_url), B("Help", callback_data="help:open"),
         B("Discussion", url=s.discussion_url)],
        [B("💗 Donate", url=s.donate_url, style=SUCCESS)],
    ])


def links_keyboard(s: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[B("📢 Updates", url=s.updates_url), B("💬 Discussion", url=s.discussion_url)]])


def private_daily_keyboard(s: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[B("📅 Play daily in private", url=f"{s.bot_link}?start=daily")]])
