"""Shared handler helpers: context access, safe sending, decorators."""
from __future__ import annotations

import asyncio
from functools import wraps

from telegram import LinkPreviewOptions, Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from database.models import Player
from services.context import AppContext
from utils.logger import get_logger

log = get_logger(__name__)
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def ctx_of(context: ContextTypes.DEFAULT_TYPE) -> AppContext:
    return context.application.bot_data["ctx"]


def player_of(user) -> Player:
    return Player(user.id, user.full_name or user.first_name or "Player", user.username)


def is_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return user_id in ctx_of(context).settings.admin_ids


async def _retry(call, *, retries: int = 1):
    for attempt in range(retries + 1):
        try:
            return await call()
        except RetryAfter as e:
            if attempt == retries:
                raise
            await asyncio.sleep(float(e.retry_after) + 0.5)


async def safe_reply(message: Message, text: str, **kw) -> Message | None:
    kw.setdefault("parse_mode", ParseMode.HTML)
    kw.setdefault("link_preview_options", NO_PREVIEW)
    try:
        return await _retry(lambda: message.reply_text(text, **kw))
    except BadRequest as e:
        if "not found" in str(e).lower():  # original message deleted -> plain send
            return await safe_send(message.get_bot(), message.chat_id, text, **kw)
        log.warning("reply failed: %s", e)
    except Forbidden:
        pass
    except TelegramError as e:
        log.warning("reply failed: %s", e)
    return None


async def safe_send(bot, chat_id: int, text: str, **kw) -> Message | None:
    kw.setdefault("parse_mode", ParseMode.HTML)
    kw.setdefault("link_preview_options", NO_PREVIEW)
    try:
        return await _retry(lambda: bot.send_message(chat_id, text, **kw))
    except Forbidden:
        return None
    except TelegramError as e:
        log.warning("send failed: %s", e)
        return None


def command_limited(func):
    """Per-user rate limit for commands."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user and not ctx_of(context).rate_cmd.allow(user.id):
            return
        return await func(update, context)
    return wrapper


def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not is_admin(context, user.id):
            if update.effective_message:
                await safe_reply(update.effective_message, "⛔ You are not authorized to use this command.")
            return
        return await func(update, context)
    return wrapper
