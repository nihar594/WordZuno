from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from handlers.common import command_limited, ctx_of, safe_reply
from keyboards.leaderboard import leaderboard_keyboard
from services.leaderboard_service import PER_PAGE
from utils.formatting import clip, esc, fmt_pts
from utils.logger import get_logger

log = get_logger(__name__)
MEDALS = ["🥇", "🥈", "🥉"]


def render(ctx, scope: str, chat_type: str, page) -> str:
    if scope == "g":
        title = "Global Leaderboard"
    elif chat_type == ChatType.PRIVATE:
        title = "Private Leaderboard"
    else:
        title = "Group Leaderboard"
    head = f"<blockquote>🏆 <b>{title}</b> 🏆</blockquote>\n\n"
    if not page.rows:
        return head + "No games played yet — start one with /new!"
    first = (page.page - 1) * PER_PAGE
    top, rest = [], []
    for i, r in enumerate(page.rows):
        rank = first + i
        line = f"{{}} - {esc(clip(r.name))} - {fmt_pts(r.points)} pts"
        if rank < 3:
            top.append(line.format(MEDALS[rank]))
        else:
            rest.append(line.format("🔆"))
    out = head + f"<blockquote>{chr(10).join(top)}</blockquote>"
    if rest:
        out += f"\n<blockquote>{chr(10).join(rest)}</blockquote>"
    return out


async def _build(ctx, chat, scope, period, length, page_no):
    page = await ctx.boards.page(scope=scope, chat_id=chat.id, period=period, length=length, page=page_no)
    return (render(ctx, scope, chat.type, page),
            leaderboard_keyboard(ctx.settings, scope, period, length, page.page, page.pages))


PERIODS = {"today": "t", "daily": "t", "week": "w", "weekly": "w", "month": "m", "monthly": "m",
           "year": "y", "yearly": "y", "all": "a", "alltime": "a"}


@command_limited
async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/leaderboard [group|global] [today|week|month|year|all] [4-7]  — any order, all optional."""
    ctx, chat = ctx_of(context), update.effective_chat
    scope, period, length = "c", "t", ctx.settings.default_length
    for tok in context.args:
        t = tok.lower()
        if t in ("group", "chat", "this"):
            scope = "c"
        elif t == "global":
            scope = "g"
        elif t in PERIODS:
            period = PERIODS[t]
        elif t in ("4", "5", "6", "7"):
            length = int(t)
    text, kb = await _build(ctx, chat, scope, period, length, 1)
    await safe_reply(update.effective_message, text, reply_markup=kb)


async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q, ctx = update.callback_query, ctx_of(context)
    if ctx.seen_callbacks.seen(q.id):
        return
    if not ctx.rate_cb.allow(q.from_user.id):
        await q.answer("Slow down a little ⏳")
        return
    try:
        _, scope, period, length, page = q.data.split("|")
        length, page = int(length), int(page)
        if scope not in ("g", "c") or period not in ("t", "w", "m", "y", "a") or length not in (0, 4, 5, 6, 7):
            raise ValueError
    except ValueError:
        await q.answer()
        return
    text, kb = await _build(ctx, q.message.chat, scope, period, length, page)
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        await q.answer()
    except BadRequest as e:
        await q.answer("Already up to date ✅" if "not modified" in str(e).lower() else "Couldn't update")
    except TelegramError as e:
        log.warning("leaderboard edit failed: %s", e)
        await q.answer()


async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
