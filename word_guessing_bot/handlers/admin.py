"""Access guard (ban / maintenance / user registration) and admin commands."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from handlers.common import admin_only, ctx_of, is_admin, player_of, safe_reply, safe_send
from utils.formatting import esc, fmt_pts, today_utc, utcnow
from utils.logger import get_logger
from utils.validators import parse_user_id

log = get_logger(__name__)


# -------------------------------------------------------------------- guard
async def access_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, user, chat = ctx_of(context), update.effective_user, update.effective_chat
    if user is None or user.is_bot or chat is None:
        return
    player = player_of(user)
    private = chat.type == ChatType.PRIVATE
    sig = (player.name, player.username, private)
    cached = ctx.user_cache.get(user.id)
    if cached is None or cached[0] != sig or time.monotonic() - cached[1] > 600:
        await ctx.games.upsert_user(player, private=private)
        if not private:
            await ctx.games.upsert_group(chat.id, chat.title)
        if len(ctx.user_cache) > 50_000:
            ctx.user_cache.clear()
        ctx.user_cache[user.id] = (sig, time.monotonic())
    admin = is_admin(context, user.id)
    if user.id in ctx.banned and not admin:
        if private and update.effective_message:
            await safe_reply(update.effective_message, "🚫 You are banned from using this bot.")
        raise ApplicationHandlerStop
    if ctx.maintenance and not admin:
        if update.effective_message and (update.effective_message.text or "").startswith("/"):
            await safe_reply(update.effective_message, "🛠 The bot is under maintenance. Please try again soon.")
        elif update.callback_query:
            await update.callback_query.answer("🛠 Maintenance — try again soon.", show_alert=True)
        raise ApplicationHandlerStop


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, ev = ctx_of(context), update.my_chat_member
    chat = ev.chat
    if chat.type == ChatType.PRIVATE:
        if ev.new_chat_member.status in (ChatMemberStatus.BANNED, ChatMemberStatus.LEFT):
            await ctx.db.execute("UPDATE users SET blocked=1 WHERE user_id=?", (ev.from_user.id,))
        return
    if ev.new_chat_member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
        await ctx.games.upsert_group(chat.id, chat.title)
        await safe_send(context.bot, chat.id, (
            f"👋 Thanks for adding <b>{esc(ctx.settings.bot_name)}</b>!\n\n"
            "Use /new to start a group game, /help for all commands.\n"
            "<i>Tip: make me an admin so I can read every message in the group.</i>"))


# ----------------------------------------------------------------- commands
@admin_only
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    await safe_reply(update.effective_message, (
        "🛡 <b>Admin panel</b>\n\n"
        "/botstats — bot statistics\n/broadcast &lt;text&gt; — message all users (or reply to a message)\n"
        "/ban &lt;id|@user&gt; [reason] · /unban &lt;id|@user&gt;\n/transfer &lt;from&gt; &lt;to&gt; — move all points\n/userinfo &lt;id&gt; — user details\n"
        "/maintenance on|off — toggle maintenance\n/reloadwords — reload dictionaries\n"
        "/backup — send a database backup\n/emojipack — pill letters setup (custom emoji)\n\n"
        f"Maintenance: <b>{'ON' if ctx.maintenance else 'OFF'}</b>"))


@admin_only
async def botstats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    q = ctx.db.fetchone
    users = (await q("SELECT COUNT(*) c, SUM(is_banned) b, SUM(dm_ok) d FROM users"))
    groups = (await q("SELECT COUNT(*) c FROM groups"))["c"]
    games = await q("SELECT COUNT(*) c, SUM(status='active') a, SUM(status='won') w, SUM(status='lost') l FROM games")
    guesses = (await q("SELECT COUNT(*) c FROM guesses"))["c"]
    today = utcnow()[:10] + " 00:00:00"
    active_today = (await q("SELECT COUNT(*) c FROM users WHERE last_seen >= ?", (today,)))["c"]
    daily = (await q("SELECT COUNT(*) c FROM daily_results WHERE challenge_date=?", (today_utc(),)))["c"]
    pts = (await q("SELECT COALESCE(SUM(points),0) s FROM transactions"))["s"]
    size = Path(ctx.db.path).stat().st_size / 1_048_576 if Path(ctx.db.path).exists() else 0
    up = int(time.time() - ctx.started_at)
    await safe_reply(update.effective_message, (
        "📈 <b>Bot statistics</b>\n\n"
        f"👥 Users: <b>{users['c']}</b> (DM-able {users['d'] or 0}, banned {users['b'] or 0})\n"
        f"🏘 Groups: <b>{groups}</b>\n🟢 Active today: <b>{active_today}</b>\n"
        f"🎮 Games: <b>{games['c']}</b> (active {games['a'] or 0}, won {games['w'] or 0}, lost {games['l'] or 0})\n"
        f"🔤 Guesses: <b>{fmt_pts(guesses)}</b>\n📅 Daily players today: <b>{daily}</b>\n"
        f"⭐ Points awarded: <b>{fmt_pts(pts)}</b>\n"
        f"📚 Words: {ctx.words.counts()}\n💾 DB: {size:.2f} MB\n"
        f"⏱ Uptime: {up // 3600}h {up % 3600 // 60}m\n🛠 Maintenance: {'ON' if ctx.maintenance else 'OFF'}"))


async def _resolve(ctx, token: str) -> int | None:
    """User id from '123456' or '@username' (must have used the bot before)."""
    uid = parse_user_id(token)
    if uid:
        return uid
    if token.startswith("@"):
        row = await ctx.db.fetchone("SELECT user_id FROM users WHERE lower(username)=?", (token[1:].lower(),))
        return row["user_id"] if row else None
    return None


async def _target_id_async(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if context.args and context.args[0].startswith("@"):
        return await _resolve(ctx_of(context), context.args[0])
    return _target_id(update, context)


def _target_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    msg = update.effective_message
    if context.args:
        uid = parse_user_id(context.args[0])
        if uid:
            return uid
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    return None


@admin_only
async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    uid = await _target_id_async(update, context)
    if uid is None:
        return await safe_reply(msg, "Usage: /ban &lt;user_id&gt; [reason] (or reply to a user)")
    if uid in ctx.settings.admin_ids:
        return await safe_reply(msg, "You cannot ban an admin.")
    reason = " ".join(context.args[1:])[:200] if context.args and (parse_user_id(context.args[0]) or context.args[0].startswith("@")) else ""
    res = await ctx.db.execute("UPDATE users SET is_banned=1, ban_reason=? WHERE user_id=?", (reason or None, uid))
    if res.rowcount:
        ctx.banned.add(uid)
        await safe_reply(msg, f"🚫 User <code>{uid}</code> banned.")
    else:
        await safe_reply(msg, "That user is not in the database yet.")


@admin_only
async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    uid = await _target_id_async(update, context)
    if uid is None:
        return await safe_reply(msg, "Usage: /unban &lt;user_id&gt;")
    res = await ctx.db.execute("UPDATE users SET is_banned=0, ban_reason=NULL WHERE user_id=?", (uid,))
    ctx.banned.discard(uid)
    await safe_reply(msg, f"✅ User <code>{uid}</code> unbanned." if res.rowcount else "User not found.")


@admin_only
async def userinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    uid = await _target_id_async(update, context)
    if uid is None:
        return await safe_reply(msg, "Usage: /userinfo &lt;user_id&gt; (or reply to a user)")
    u = await ctx.boards.user(uid)
    if not u:
        return await safe_reply(msg, "User not found.")
    st = await ctx.boards.stats(uid)
    await safe_reply(msg, (
        f"👤 <b>{esc(u['first_name'])}</b> (<code>{uid}</code>)\n"
        f"Username: {('@' + esc(u['username'])) if u['username'] else '—'}\n"
        f"Joined: {esc(u['joined_at'])}\nLast seen: {esc(u['last_seen'] or '—')}\n"
        f"Points: {fmt_pts(u['total_points'])} · Rank: {st['rank'] or '—'}\n"
        f"Games: {u['games_played']} (W {u['games_won']} / L {u['games_lost']})\n"
        f"Streak: {u['current_streak']} (best {u['best_streak']})\n"
        f"Banned: {'yes — ' + esc(u['ban_reason'] or 'no reason') if u['is_banned'] else 'no'} · "
        f"DM: {'yes' if u['dm_ok'] else 'no'} · Blocked bot: {'yes' if u['blocked'] else 'no'}"))


@admin_only
async def maintenance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    arg = (context.args[0].lower() if context.args else "")
    if arg not in ("on", "off"):
        return await safe_reply(msg, f"Maintenance is <b>{'ON' if ctx.maintenance else 'OFF'}</b>.\nUsage: /maintenance on|off")
    await ctx.set_maintenance(arg == "on")
    await safe_reply(msg, f"🛠 Maintenance mode <b>{'enabled' if ctx.maintenance else 'disabled'}</b>.")


@admin_only
async def reloadwords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    try:
        counts = await ctx.words.reload()
        await safe_reply(update.effective_message, f"📚 Dictionaries reloaded: {counts}")
    except Exception as e:  # noqa: BLE001 - report any file problem to the admin
        log.exception("reloadwords failed")
        await safe_reply(update.effective_message, f"❌ Reload failed: {esc(e)} (old words kept)")


@admin_only
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    path = ctx.settings.db_path.parent / f"backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"
    try:
        await ctx.db.backup_to(path)
        with path.open("rb") as fh:
            await msg.reply_document(fh, filename=path.name, caption="💾 Database backup")
    except (OSError, TelegramError) as e:
        await safe_reply(msg, f"❌ Backup failed: {esc(e)}")
    finally:
        path.unlink(missing_ok=True)


@admin_only
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    reply = msg.reply_to_message
    text = msg.text.partition(" ")[2].strip() if msg.text else ""
    if not reply and not text:
        return await safe_reply(msg, "Usage: /broadcast &lt;text&gt; — or reply to a message with /broadcast")
    rows = await ctx.db.fetchall("SELECT user_id FROM users WHERE dm_ok=1 AND blocked=0 AND is_banned=0")
    status = await safe_reply(msg, f"📣 Broadcasting to {len(rows)} users…")
    sent = failed = 0
    for r in rows:
        uid = r["user_id"]
        for attempt in range(2):
            try:
                if reply:
                    await context.bot.copy_message(uid, reply.chat_id, reply.message_id)
                else:
                    await context.bot.send_message(uid, text)
                sent += 1
                break
            except RetryAfter as e:
                await asyncio.sleep(float(e.retry_after) + 0.5)
            except Forbidden:
                await ctx.db.execute("UPDATE users SET blocked=1 WHERE user_id=?", (uid,))
                failed += 1
                break
            except TelegramError:
                failed += 1
                break
        await asyncio.sleep(0.05)  # ~20 msgs/s, under Telegram's limit
    summary = f"📣 Broadcast finished.\n✅ Sent: <b>{sent}</b>\n❌ Failed: <b>{failed}</b>"
    if status:
        try:
            await status.edit_text(summary, parse_mode="HTML")
            return
        except TelegramError:
            pass
    await safe_reply(msg, summary)


# ------------------------------------------------------ custom emoji (pills)
def _emoji_help() -> str:
    return (
        "🎨 <b>Pill letters (custom emoji)</b>\n\n"
        "<code>/emojipack &lt;pack_name&gt; &lt;colors&gt;</code>\n"
        "Reads a custom-emoji pack and maps A–Z per color, in pack order. "
        "<code>colors</code> = G (green), Y (yellow), B (grey/red). One letter per 26-emoji block, "
        "e.g. <code>/emojipack MyLetters GYB</code> (first 26 = green, next 26 = yellow, last 26 = grey).\n\n"
        "<code>/emojiset G</code> + 26 custom emojis (A→Z) in the same message → one color manually.\n"
        "<code>/emojitest</code> — preview A–Z for each color.\n"
        "<code>/emojireset</code> — go back to 🟩🟨⬛ tiles.\n\n"
        "Pack link <code>t.me/addemoji/NAME</code> → pack name is NAME.")


async def _emoji_status(ctx) -> str:
    st = ctx.emoji.status()
    state = "ON ✅" if ctx.emoji.ready else "OFF (incomplete or disabled)"
    return f"Status: <b>{state}</b> — G {st['G']}/26 · Y {st['Y']}/26 · B {st['B']}/26"


@admin_only
async def emojipack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    if len(context.args) != 2 or not set(context.args[1].upper()) <= set("GYB") or not context.args[1]:
        return await safe_reply(msg, _emoji_help() + "\n\n" + await _emoji_status(ctx))
    name, colors = context.args[0].strip(), context.args[1].upper()
    try:
        sset = await context.bot.get_sticker_set(name)
    except TelegramError as e:
        return await safe_reply(msg, f"❌ Could not load pack <code>{esc(name)}</code>: {esc(e)}")
    ids = [s.custom_emoji_id for s in sset.stickers if s.custom_emoji_id]
    need = 26 * len(colors)
    if len(ids) < need:
        return await safe_reply(msg, f"❌ Pack has {len(ids)} custom emojis, need {need} for “{esc(colors)}”.")
    for i, c in enumerate(colors):
        ctx.emoji.set_color(c, ids[i * 26:(i + 1) * 26])
    await safe_reply(msg, "✅ Saved.\n" + await _emoji_status(ctx) + "\nCheck with /emojitest")


@admin_only
async def emojiset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    color = context.args[0].upper() if context.args else ""
    ents = [e for e in (msg.entities or []) if e.type == "custom_emoji"]
    if color not in ("G", "Y", "B") or not ents:
        return await safe_reply(msg, _emoji_help() + "\n\n" + await _emoji_status(ctx))
    ids = [e.custom_emoji_id for e in ents]
    if len(ids) != 26:
        return await safe_reply(msg, f"❌ Found {len(ids)} custom emojis, need exactly 26 (A→Z).")
    ctx.emoji.set_color(color, ids)
    await safe_reply(msg, f"✅ {color} saved.\n" + await _emoji_status(ctx))


@admin_only
async def emojitest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg = ctx_of(context), update.effective_message
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    lines = [await _emoji_status(ctx), ""]
    for c in "GYB":
        if len(ctx.emoji.data.get(c, {})) == 26:
            lines.append(f"<b>{c}</b>: " + "".join(ctx.emoji.tile(ch, c) for ch in alphabet))
    lines.append("\nIf you see plain 🟩🟨⬛ squares instead of letter pills, Telegram is not allowing this bot to use "
                 "custom emoji (see README) — run /emojireset.")
    await safe_reply(msg, "\n".join(lines))


@admin_only
async def emojireset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx_of(context).emoji.clear()
    await safe_reply(update.effective_message, "♻️ Custom emoji cleared — using 🟩🟨⬛ tiles again.")


@admin_only
async def richtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a sample colored-pill board so you can check Telegram accepts rich messages for this bot."""
    from utils.rich import rich_row, send_rich
    ctx, msg = ctx_of(context), update.effective_message
    html = "<h3>4-letter mode</h3><p><i>2/30 guesses</i></p>" + rich_row("word", "BBYB") + rich_row("pest", "GGBB")
    try:
        await send_rich(context.bot, msg.chat_id, html)
        ctx.rich_failures = 0
        await safe_reply(msg, "✅ Rich pill board works for this bot. (BOARD_STYLE=rich is active)")
    except TelegramError as e:
        await safe_reply(msg, f"❌ Telegram refused the rich message: {esc(e)}\nThe bot will use the emoji text board instead.")


@admin_only
async def transfer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/transfer <from> <to> — move ALL points/games/stats from one user to another (id or @username)."""
    ctx, msg = ctx_of(context), update.effective_message
    if len(context.args) != 2:
        return await safe_reply(msg, "Usage: /transfer &lt;from_user&gt; &lt;to_user&gt;\n"
                                     "Example: /transfer @user1 @user2 — or with numeric IDs")
    a, b = await _resolve(ctx, context.args[0]), await _resolve(ctx, context.args[1])
    if a is None or b is None:
        return await safe_reply(msg, "❌ User not found (they must have used the bot before).")
    if a == b:
        return await safe_reply(msg, "❌ Cannot transfer to the same user.")
    try:
        r = await ctx.games.transfer_points(a, b)
    except LookupError:
        return await safe_reply(msg, "❌ User not found in the database.")
    ctx.user_cache.pop(a, None)
    ctx.user_cache.pop(b, None)
    await safe_reply(msg, (f"✅ Transferred leaderboard data\n\nFrom: {esc(r['from'])} (<code>{a}</code>)\n"
                           f"To: {esc(r['to'])} (<code>{b}</code>)\n\nEntries: <b>{r['entries']}</b>\n"
                           f"Points: <b>{fmt_pts(r['points'])}</b>"))
