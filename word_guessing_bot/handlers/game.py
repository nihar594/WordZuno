from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from database.models import Game
from handlers.common import command_limited, ctx_of, is_admin, player_of, safe_reply, safe_send, NO_PREVIEW
from utils.formatting import esc, fmt_pts, mode_command, render_board
from utils.rich import HINTS, edit_rich, rich_board_html, send_rich
from utils.logger import get_logger
from utils.validators import clean_guess

log = get_logger(__name__)


# ------------------------------------------------------------------- board
async def post_board(context: ContextTypes.DEFAULT_TYPE, chat_id: int, game: Game, guesses) -> None:
    ctx = ctx_of(context)
    old_id = game.board_message_id
    if ctx.rich_enabled:  # colored pill letters (rich message); falls back to emoji text if Telegram refuses
        html = rich_board_html(game, guesses)
        try:
            if ctx.settings.board_mode == "edit" and old_id:
                try:
                    await edit_rich(context.bot, chat_id, old_id, html)
                    ctx.rich_failures = 0
                    return
                except BadRequest as e:
                    if "not modified" in str(e).lower():
                        return
            mid = await send_rich(context.bot, chat_id, html)
            ctx.rich_failures = 0
            await ctx.games.set_board_message(game.game_id, mid)
            if old_id and ctx.settings.board_mode == "resend":
                try:
                    await context.bot.delete_message(chat_id, old_id)
                except TelegramError:
                    pass
            return
        except TelegramError as e:
            ctx.rich_failures += 1
            log.warning("rich board failed (%s/3), using text board: %s", ctx.rich_failures, e)
    text = render_board(game, guesses, ctx.emoji)
    if ctx.settings.board_mode == "edit" and old_id:
        try:
            await context.bot.edit_message_text(text, chat_id, old_id, parse_mode=ParseMode.HTML)
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
        except TelegramError:
            pass
    sent = await safe_send(context.bot, chat_id, text)
    if sent:
        await ctx.games.set_board_message(game.game_id, sent.message_id)
        if old_id and ctx.settings.board_mode == "resend":
            try:
                await context.bot.delete_message(chat_id, old_id)
            except TelegramError:
                pass


async def hint_letter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tapping a pill explains its color (same as the reference bot)."""
    q = update.callback_query
    try:
        _, state, letter = q.data.split(":")
        await q.answer(HINTS.get(state, "Unknown hint.").format(l=letter[:1]))
    except (ValueError, TelegramError):
        await q.answer()


# ----------------------------------------------------------------- /new*
def make_new(length: int | None):
    @command_limited
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ctx, msg, chat, user = ctx_of(context), update.effective_message, update.effective_chat, update.effective_user
        allowed = await ctx.games.get_allowed(chat.id)
        arg = int(context.args[0]) if length is None and context.args and context.args[0] in ("4", "5", "6", "7") else None
        n = length or arg or (ctx.settings.default_length if ctx.settings.default_length in allowed else allowed[0])
        if n not in allowed:
            await safe_reply(msg, f"Only {', '.join(map(str, allowed))}-letter games are allowed in this chat. "
                                  f"Start with /new{allowed[0]}")
            return
        res = await ctx.games.start(chat.id, n, player_of(user))
        if res.created:
            await safe_reply(msg, f"Game started! Guess the {n}-letter word!")
            return
        g = res.game
        if g.is_daily:
            await safe_reply(msg, "📅 Your daily challenge is in progress — finish it first (or /cancel to forfeit it).")
        else:
            await safe_reply(msg, f"A game is already running! Guess the {g.word_length}-letter word.\n"
                                  "Use /cancel to end it.")
        guesses = await ctx.games.get_guesses(g.game_id)
        if guesses:
            await post_board(context, chat.id, g, guesses)
    return handler


# ----------------------------------------------------------- guess handler
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not user or user.is_bot or not msg.text:
        return
    word = clean_guess(msg.text)
    if not word:
        return
    ctx = ctx_of(context)
    if ctx.seen_messages.seen((chat.id, msg.message_id)):
        return
    if not ctx.rate_guess.allow(user.id):
        log.info("guess rate-limited", extra={"ctx": {"user": user.id}})
        return
    out = await ctx.games.process_guess(chat.id, player_of(user), word)
    k = out.kind
    if k in ("no_game", "ignore"):
        return
    if k == "invalid":
        await safe_reply(msg, f"{esc(word)} is not a valid {out.game.word_length}-letter word.")
        return
    if k == "duplicate":
        await safe_reply(msg, "Someone has already guessed your word. Please try another one!")
        return
    game = out.game
    if k == "wrong":
        await post_board(context, chat.id, game, out.guesses)
        return
    name = esc(player_of(user).name)
    if k == "won":
        r = out.reward
        lines = ["Congrats! You guessed it correctly.", f"Correct Word: <b>{esc(game.secret_word)}</b>",
                 f"Added {fmt_pts(r.total)} to the leaderboard."]
        if r.bonus_total:
            parts = []
            if r.streak_bonus:
                parts.append(f"🔥 streak +{r.streak_bonus}")
            if r.multiplayer_bonus:
                parts.append(f"👥 group +{r.multiplayer_bonus}")
            if r.daily_bonus:
                parts.append(f"📅 daily +{r.daily_bonus}")
            if r.daily_streak_bonus:
                parts.append(f"🔥 daily streak ({out.daily_streak}) +{r.daily_streak_bonus}")
            lines.append("Bonus: " + ", ".join(parts))
        tail = "Come back tomorrow for a new /daily word!" if game.is_daily else f"Start with /new{game.word_length}"
        meaning = ctx.words.meaning_block(game.secret_word)
        await safe_reply(msg, f"<b>{name}</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>\n"
                         + (meaning + "\n" if meaning else "") + tail)
        await react_random(msg, ctx)
        return
    if k == "lost":
        await post_board(context, chat.id, game, out.guesses)
        tail = "Come back tomorrow for a new /daily word!" if game.is_daily else f"Start with /new{game.word_length}"
        await safe_send(context.bot, chat.id,
                        f"<b>Game Over!</b>\n\nCorrect Word: <b>{esc(game.secret_word)}</b>\n\n"
                        f"{ctx.words.meaning_block(game.secret_word)}\n"
                        f"Better luck next time!\n\n{tail}")


REACTIONS = ["🎉", "🏆", "🤩", "⚡", "🫡", "💯", "❤\u200d🔥", "🦄"]


async def react_random(msg, ctx) -> None:
    """React to the winning guess with a random emoji (skips emojis the chat doesn't allow)."""
    if not ctx.settings.reactions:
        return
    import random
    for emoji in random.sample(REACTIONS, len(REACTIONS)):
        try:
            await msg.set_reaction(emoji)
            return
        except BadRequest as e:
            if "REACTION" in str(e).upper() or "reaction" in str(e):
                continue
            return
        except TelegramError:
            return


@command_limited
async def allowonlylen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg, chat, user = ctx_of(context), update.effective_message, update.effective_chat, update.effective_user
    current = await ctx.games.get_allowed(chat.id)
    if not context.args:
        await safe_reply(msg, f"Allowed word lengths here: <b>{', '.join(map(str, current))}</b>\n"
                              "Change (admins): /allowonlylen 5 4 — or /allowonlylen all")
        return
    if chat.type != ChatType.PRIVATE and not is_admin(context, user.id):
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            ok = member.status in ("administrator", "creator")
        except TelegramError:
            ok = False
        if not ok:
            await safe_reply(msg, "Only group admins can change this.")
            return
    if context.args[0].lower() == "all":
        await ctx.games.set_allowed(chat.id, None)
        await safe_reply(msg, "✅ All word lengths (4–7) are allowed again.")
        return
    lengths = []
    for a in context.args:
        if a.isdigit() and int(a) in (4, 5, 6, 7) and int(a) not in lengths:
            lengths.append(int(a))
    if not lengths:
        await safe_reply(msg, "Allowed lengths are only: 4, 5, 6, 7\nExample: /allowonlylen 5 4")
        return
    await ctx.games.set_allowed(chat.id, lengths)
    await safe_reply(msg, f"✅ Allowed word lengths updated.\nDefault length: <b>{lengths[0]}</b>\n"
                          f"Allowed: <b>{', '.join(map(str, lengths))}</b>")


# ------------------------------------------------- /cancel /skip /hint /id
async def _can_end(update: Update, context: ContextTypes.DEFAULT_TYPE, game: Game) -> bool:
    chat, user = update.effective_chat, update.effective_user
    if chat.type == ChatType.PRIVATE or user.id == game.started_by or is_admin(context, user.id):
        return True
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False


def make_end(status: str):
    @command_limited
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ctx, msg, chat = ctx_of(context), update.effective_message, update.effective_chat
        game = await ctx.games.get_active(chat.id)
        if not game:
            await safe_reply(msg, "No active game here. Start one with /new")
            return
        if not await _can_end(update, context, game):
            await safe_reply(msg, "Only the player who started the game or a group admin can do that.")
            return
        ended = await ctx.games.end_game(chat.id, status)
        if not ended:
            return
        if status == "skipped":
            await safe_reply(msg, f"⏭ Game skipped.\n\nCorrect Word: <b>{esc(ended.secret_word)}</b>\n"
                                  f"{ctx.words.meaning_block(ended.secret_word)}\n"
                                  f"Start with {mode_command(ended)}")
        else:
            extra = " Your daily attempt for today is forfeited." if ended.is_daily else ""
            await safe_reply(msg, f"🛑 Game cancelled.{extra}\n\nStart with {mode_command(ended)}")
    return handler


@command_limited
async def hint_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx, msg, chat = ctx_of(context), update.effective_message, update.effective_chat
    res = await ctx.games.hint(chat.id)
    if res.kind == "no_game":
        await safe_reply(msg, "No active game here. Start one with /new")
    elif res.kind == "limit":
        await safe_reply(msg, f"💡 No more hints available for this game (max {ctx.settings.hints_per_game}).")
    else:
        left = ctx.settings.hints_per_game - res.game.hints_used
        await safe_reply(msg, f"💡 <b>Hint:</b> letter {res.position + 1} is <b>{res.letter.upper()}</b>\n"
                              f"<i>{left} hint(s) left</i>")


@command_limited
async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, chat, msg = update.effective_user, update.effective_chat, update.effective_message
    lines = [f"👤 <b>Your ID:</b> <code>{user.id}</code>", f"💬 <b>Chat ID:</b> <code>{chat.id}</code>"]
    if msg.reply_to_message and msg.reply_to_message.from_user:
        lines.append(f"↩️ <b>Replied user ID:</b> <code>{msg.reply_to_message.from_user.id}</code>")
    await safe_reply(msg, "\n".join(lines))
