from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from handlers.common import command_limited, ctx_of, player_of, safe_reply
from utils.formatting import esc, fmt_pts, today_utc
from datetime import datetime, timedelta, timezone


def _target(update: Update):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
        return msg.reply_to_message.from_user
    return update.effective_user


async def _stats(update, context):
    ctx, target = ctx_of(context), _target(update)
    await ctx.games.upsert_user(player_of(target))
    return ctx, target, await ctx.boards.stats(target.id)


def _daily_streak(u) -> int:
    last = u["last_daily_win"]
    if not last:
        return 0
    today = datetime.now(timezone.utc).date()
    ok = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
    return u["daily_streak"] if last in ok else 0


@command_limited
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, target, st = await _stats(update, context)
    u = st["user"]
    fav = f"{st['fav_length']} letters" if st["fav_length"] else "—"
    rank = f"#{st['rank']}" if st["rank"] else "unranked"
    hist = await ctx.boards.history(target.id, 3)
    recent = "\n".join(
        f"{'✅' if h['result'] == 'won' else '❌'} {esc(h['secret_word'])} · {h['attempts']} tries · +{h['points_earned']}"
        for h in hist) or "No games yet."
    await safe_reply(update.effective_message, (
        f"📊 <b>Statistics — {esc(u['first_name'])}</b>\n\n"
        f"🎮 Games played: <b>{u['games_played']}</b>\n"
        f"✅ Won: <b>{u['games_won']}</b>   ❌ Lost: <b>{u['games_lost']}</b>\n"
        f"📈 Win rate: <b>{st['win_pct']:.1f}%</b>\n"
        f"⭐ Total points: <b>{fmt_pts(u['total_points'])}</b>\n"
        f"🌍 Global rank: <b>{rank}</b>\n"
        f"🔥 Current streak: <b>{u['current_streak']}</b>   🏅 Best: <b>{u['best_streak']}</b>\n"
        f"🎯 Highest scoring game: <b>{st['best_game']}</b> pts\n"
        f"🔤 Favorite length: <b>{fav}</b>\n\n"
        f"🕘 <b>Recent games</b>\n{recent}"))


@command_limited
async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, target, st = await _stats(update, context)
    u = st["user"]
    uname = f"@{esc(u['username'])}" if u["username"] else "—"
    rank = f"#{st['rank']}" if st["rank"] else "unranked"
    await safe_reply(update.effective_message, (
        f"👤 <b>{esc(u['first_name'])}</b>\n"
        f"🔗 Username: {uname}\n🆔 ID: <code>{u['user_id']}</code>\n"
        f"📅 Joined: {esc(u['joined_at'][:10])}\n\n"
        f"⭐ Points: <b>{fmt_pts(u['total_points'])}</b>  ·  🌍 Rank: <b>{rank}</b>\n"
        f"🎮 Played: <b>{u['games_played']}</b>  ·  ✅ Won: <b>{u['games_won']}</b>  "
        f"·  📈 <b>{st['win_pct']:.0f}%</b>\n"
        f"🔥 Streak: <b>{u['current_streak']}</b> (best {u['best_streak']})\n"
        f"📅 Daily streak: <b>{_daily_streak(u)}</b> (best {u['best_daily_streak']})"))


@command_limited
async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, target, _ = await _stats(update, context)
    rows = await ctx.boards.history(target.id, 10)
    if not rows:
        await safe_reply(update.effective_message, "No finished games yet. Start with /new")
        return
    lines = []
    for h in rows:
        icon = "✅" if h["result"] == "won" else "❌"
        mode = "📅" if h["game_mode"] == "daily" else f"{h['word_length']}L"
        lines.append(f"{icon} <code>{esc(h['secret_word'])}</code> · {mode} · {h['attempts']} tries · "
                     f"+{h['points_earned']} · {esc((h['completed_at'] or '')[:10])}")
    await safe_reply(update.effective_message, "🕘 <b>Recent games</b>\n\n" + "\n".join(lines))


@command_limited
async def rank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, target, st = await _stats(update, context)
    chat = update.effective_chat
    u = st["user"]
    g = f"#{st['rank']}" if st["rank"] else "unranked"
    crank, total = await ctx.boards.chat_rank(chat.id, target.id)
    c = f"#{crank} of {total}" if crank else "unranked here"
    await safe_reply(update.effective_message, (
        f"🏅 <b>{esc(u['first_name'])}</b>\n\n🌍 Global rank: <b>{g}</b>\n💬 This chat: <b>{c}</b>\n"
        f"⭐ Points: <b>{fmt_pts(u['total_points'])}</b>"))


PERIOD_WORDS = {"today": "t", "daily": "t", "week": "w", "weekly": "w", "month": "m", "monthly": "m",
                "year": "y", "yearly": "y", "all": "a", "alltime": "a"}
PERIOD_NAMES = {"t": "Today", "w": "This week", "m": "This month", "y": "This year", "a": "All time"}


async def _score(update: Update, context: ContextTypes.DEFAULT_TYPE, own_only: bool) -> None:
    """/score [@user|id] [group|global] [today|week|month|year|all] [4|5|6|7]  (reply to a user to see theirs)"""
    ctx, msg, chat = ctx_of(context), update.effective_message, update.effective_chat
    scope = "c" if chat.type != "private" else "g"
    period, length, target_id, target_user = "t", ctx.settings.default_length, None, None
    for tok in ([] if own_only else context.args):
        t = tok.lower()
        if t in ("group", "chat", "this"):
            scope = "c"
        elif t == "global":
            scope = "g"
        elif t in PERIOD_WORDS:
            period = PERIOD_WORDS[t]
        elif t in ("4", "5", "6", "7"):
            length = int(t)
        elif t.startswith("@"):
            row = await ctx.db.fetchone("SELECT user_id FROM users WHERE lower(username)=?", (t[1:],))
            if not row:
                return await safe_reply(msg, "User not found.")
            target_id = row["user_id"]
        elif t.isdigit():
            target_id = int(t)
    if target_id is None:
        target_user = update.effective_user if own_only else _target(update)
        target_id = target_user.id
        await ctx.games.upsert_user(player_of(target_user))
    u = await ctx.boards.user(target_id)
    if not u:
        return await safe_reply(msg, "User not found.")
    pts, rank, wins = await ctx.boards.user_score(target_id, scope, chat.id, period, length)
    where = "globally" if scope == "g" else "in this chat"
    flt = f"{PERIOD_NAMES[period]}" + (f" · {length} letters" if length else "")
    if not pts:
        return await safe_reply(msg, f"<b>{esc(u['first_name'])}</b> has no scores {where} for <i>{flt}</i> yet.\n"
                                     "Try /score global all")
    await safe_reply(msg, (
        f"<blockquote><b>🏆 {esc(u['first_name'])} — Score</b></blockquote>\n"
        f"<b>{fmt_pts(pts)}</b> points {where} (<i>{flt}</i>)\n"
        f"Rank: <b>#{rank}</b> · Wins: <b>{wins}</b>\n\n"
        f"<blockquote><b>🔥 Streaks</b></blockquote>\n"
        f"Win streak: <b>{u['current_streak']}</b> (best {u['best_streak']})\n"
        f"Daily streak: <b>{_daily_streak(u)}</b> days (best {u['best_daily_streak']})"))


@command_limited
async def score_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _score(update, context, own_only=False)


@command_limited
async def myscore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _score(update, context, own_only=True)
