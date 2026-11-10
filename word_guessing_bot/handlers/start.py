from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from handlers.common import command_limited, ctx_of, safe_reply
from keyboards.main_menu import start_keyboard
from utils.formatting import esc
from utils.logger import get_logger

log = get_logger(__name__)


def welcome_text(name: str) -> str:
    return (
        f"<b>Welcome to {esc(name)}!</b>\n\n"
        "A fun and competitive Wordle-style game that you can play directly on Telegram.\n\n"
        "<blockquote><b>Quick Start:</b>\n"
        "• Use /new to start a new game\n"
        "• Add me to a group with admin permissions to play with friends\n"
        "• Use /help for detailed instructions and command list</blockquote>\n\n"
        "Ready to test your word skills? Let's play!"
    )


@command_limited
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg, chat = ctx_of(context), update.effective_message, update.effective_chat
    if context.args and context.args[0].lower() == "daily" and chat.type == ChatType.PRIVATE:
        from handlers.daily import daily_cmd
        return await daily_cmd(update, context)
    if chat.type != ChatType.PRIVATE:
        await safe_reply(msg, f"👋 <b>{esc(ctx.settings.bot_name)}</b> is ready! Use /new to start a game "
                              "or /help to see all commands.")
        return
    text, kb = welcome_text(ctx.settings.bot_name), start_keyboard(ctx.settings)
    banner = ctx.settings.banner_path
    if banner.exists():
        try:
            with banner.open("rb") as fh:
                await msg.reply_photo(fh, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except TelegramError as e:
            log.warning("banner send failed, falling back to text: %s", e)
    await safe_reply(msg, text, reply_markup=kb)
