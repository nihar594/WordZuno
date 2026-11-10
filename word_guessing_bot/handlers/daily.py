from __future__ import annotations

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from handlers.common import command_limited, ctx_of, player_of, safe_reply
from handlers.game import post_board
from keyboards.main_menu import private_daily_keyboard
from utils.formatting import esc, next_reset_text, today_utc

RANK_KB = InlineKeyboardMarkup([[B("🏆 Today's daily ranking", callback_data="daily:rank")]])


async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg, chat, user = ctx_of(context), update.effective_message, update.effective_chat, update.effective_user
    if not ctx.rate_cmd.allow(user.id):
        return
    if chat.type != ChatType.PRIVATE:
        await safe_reply(msg, "📅 The daily challenge is played in private chat.",
                         reply_markup=private_daily_keyboard(ctx.settings))
        return
    res = await ctx.games.start_daily(chat.id, player_of(user))
    streak = f"🔥 Daily streak: <b>{res.streak}</b>" if res.streak else ""
    s = ctx.settings
    if res.kind == "new":
        await safe_reply(msg, (
            f"📅 <b>Daily Challenge — {today_utc()}</b>\n\n"
            f"Guess today's <b>{res.game.word_length}-letter</b> word! Everyone gets the same word.\n"
            f"You have <b>{res.game.max_guesses}</b> guesses and one official attempt per day.\n"
            f"Win: {s.points_win} pts + {s.daily_bonus} daily bonus + streak bonus.\n"
            f"{streak}\n\n<i>/cancel forfeits today's attempt.</i>"), reply_markup=RANK_KB)
    elif res.kind == "resume":
        await safe_reply(msg, "📅 Your daily challenge is in progress — keep guessing!", reply_markup=RANK_KB)
        guesses = await ctx.games.get_guesses(res.game.game_id)
        if guesses:
            await post_board(context, chat.id, res.game, guesses)
    elif res.kind == "busy":
        await safe_reply(msg, "You have a normal game running here. Finish it, or use /cancel, then try /daily.")
    else:
        outcome = {"won": f"✅ Solved in <b>{res.attempts}</b> guesses (+{res.points} pts)",
                   "lost": "❌ Not solved this time"}.get(res.status, "🚫 Forfeited")
        await safe_reply(msg, (f"📅 <b>Daily Challenge</b>\n\nYou already played today's challenge.\n{outcome}\n"
                               f"{streak}\n\n⏳ Next word in <b>{next_reset_text()}</b> (00:00 UTC)."),
                         reply_markup=RANK_KB)


async def daily_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q, ctx = update.callback_query, ctx_of(context)
    if ctx.seen_callbacks.seen(q.id):
        return
    if not ctx.rate_cb.allow(q.from_user.id):
        await q.answer("Slow down a little ⏳")
        return
    rows = await ctx.boards.daily_ranking(today_utc())
    if not rows:
        await q.answer("Nobody has solved today's word yet!", show_alert=True)
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medals[i] if i < 3 else '🔆'} {esc(r['first_name'][:20])} — {r['attempts']} guesses (+{r['points_earned']})"
             for i, r in enumerate(rows)]
    await q.answer()
    await safe_reply(q.message, f"🏆 <b>Daily ranking — {today_utc()}</b>\n\n" + "\n".join(lines))
