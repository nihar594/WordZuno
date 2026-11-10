from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from handlers.common import command_limited, ctx_of, is_admin, safe_reply
from handlers.help_pages import PAGES
from keyboards.help_menu import help_keyboard, rich_help_keyboard
from utils.formatting import esc
from utils.logger import get_logger
from utils.rich import edit_rich, send_rich

log = get_logger(__name__)

HOME = (
    "📖 <b>{name} — Help</b>\n\n"
    "Guess the hidden word in up to {n} tries. 🟩 right spot · 🟨 wrong spot · ⬛ not in word.\n\n"
    "Pick a category below to see its commands:"
)

SECTIONS = {
    "game": (
        "🎮 <b>Game Commands</b>\n\n"
        "/new — start a game ({d}-letter)\n/new4 /new5 /new6 /new7 — choose word length\n"
        "/hint — reveal one letter (limited per game)\n/skip — reveal the word &amp; end the game\n"
        "/cancel — cancel the current game\n\n"
        "Just type a word to guess. Invalid words don't cost an attempt."),
    "player": (
        "👤 <b>Player Commands</b>\n\n"
        "/stats — your statistics\n/profile — your profile\n/history — your recent games\n"
        "/rank — your global &amp; chat rank\n/score [@user] [group|global] [today|week|month|year|all] [4-7] — scores\n/myscore — your score\n\nReply to someone's message with a command to see theirs."),
    "lb": (
        "🏆 <b>Leaderboard Commands</b>\n\n"
        "/leaderboard — open the leaderboard\n\n"
        "Use the buttons to switch between Global / This chat, Today / Week / Month / Year / All time "
        "and 4–7 letter modes. Press 🔄 to refresh."),
    "group": (
        "👥 <b>Group Commands</b>\n\n"
        "Add me to a group (admin recommended so I can read messages). Everyone races to guess the "
        "same word — the first correct guess wins the points.\n\n"
        "/new — start a group game\n/end, /cancel &amp; /skip — game starter or group admins only\n/allowonlylen 5 4 — limit word lengths (admins)\n"
        "/leaderboard — group ranking"),
    "daily": (
        "📅 <b>Daily Challenge</b>\n\n"
        "/daily — today's word, the same for everyone (resets 00:00 UTC)\n"
        "One official attempt per day, bonus points and a daily streak. Play it in private chat."),
    "info": (
        "ℹ️ <b>Information</b>\n\n"
        "/start — welcome screen\n/help — this guide\n/rules — game rules\n"
        "/id — show your Telegram &amp; chat IDs"),
}


def _text(ctx, key: str) -> str:
    s = ctx.settings
    if key == "home":
        return HOME.format(name=esc(s.bot_name), n=s.max_guesses)
    return SECTIONS[key].format(d=s.default_length) if key == "game" else SECTIONS[key]


async def _send_rich_help(context, chat_id: int, user_id: int, is_private: bool) -> bool:
    """WordSeek-style help (rich message). Returns False if Telegram refused (caller falls back to text help)."""
    ctx = ctx_of(context)
    if not ctx.rich_enabled:
        return False
    show_admin = is_private and is_admin(context, user_id)
    try:
        await send_rich(context.bot, chat_id, PAGES["howto"](ctx.settings),
                        rich_help_keyboard(ctx.settings, "howto", show_admin))
        ctx.rich_failures = 0
        return True
    except TelegramError as e:
        ctx.rich_failures += 1
        log.warning("rich help failed (%s/3): %s", ctx.rich_failures, e)
        return False


@command_limited
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    if await _send_rich_help(context, chat.id, user.id, chat.type == ChatType.PRIVATE):
        return
    await safe_reply(update.effective_message, _text(ctx_of(context), "home"), reply_markup=help_keyboard("home"))


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    ctx = ctx_of(context)
    if ctx.seen_callbacks.seen(q.id):
        return
    key = q.data.split(":", 1)[1]
    if key == "open":  # from the welcome screen (photo message) -> send a new message
        await q.answer()
        chat = q.message.chat
        if not await _send_rich_help(context, chat.id, q.from_user.id, chat.type == ChatType.PRIVATE):
            await safe_reply(q.message, _text(ctx, "home"), reply_markup=help_keyboard("home"))
        return
    if key in PAGES:  # rich help pages
        private = q.message.chat.type == ChatType.PRIVATE
        if key == "admin" and not (private and is_admin(context, q.from_user.id)):
            await q.answer("Admins only.", show_alert=True)
            return
        try:
            await edit_rich(context.bot, q.message.chat.id, q.message.message_id, PAGES[key](ctx.settings),
                            rich_help_keyboard(ctx.settings, key, private and is_admin(context, q.from_user.id)))
            await q.answer()
        except BadRequest as e:
            await q.answer("" if "not modified" in str(e).lower() else "Couldn't update")
        except TelegramError as e:
            log.warning("rich help edit failed: %s", e)
            await q.answer("Couldn't update")
        return
    if key != "home" and key not in SECTIONS:
        await q.answer()
        return
    try:
        await q.edit_message_text(_text(ctx, key), parse_mode="HTML", reply_markup=help_keyboard(key))
    except BadRequest:
        pass
    await q.answer()


@command_limited
async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = ctx_of(context).settings
    await safe_reply(update.effective_message, (
        "📜 <b>Game Rules</b>\n\n"
        f"• Guess the secret word (4–7 letters) in at most <b>{s.max_guesses}</b> valid guesses.\n"
        "• 🟩 correct letter &amp; position · 🟨 letter in the word, wrong position · ⬛ letter not in the word "
        "(duplicate letters are counted correctly).\n"
        "• Invalid words and repeated words don't use an attempt.\n"
        f"• In groups everyone plays the same word — the first correct guess wins <b>{s.points_win}</b> points.\n"
        "• Use /hint for a letter, /skip to give up, /cancel to stop.\n"
        "• /daily gives one shared word per day (resets 00:00 UTC) with bonus points."))
