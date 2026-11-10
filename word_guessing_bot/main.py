"""Word Zuno — Telegram word guessing bot. Entry point."""
from __future__ import annotations

import asyncio
import sys

from telegram import BotCommand, Update
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler, ChatMemberHandler,
                          CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters)

from config import Settings, load_settings
from handlers import admin, daily, game, help as help_h, leaderboard, profile, start
from services.context import AppContext, build_context
from utils.logger import get_logger, setup_logging

log = get_logger("main")

COMMANDS = [
    ("new", "Start a new game"), ("new4", "Start a 4-letter game"), ("new5", "Start a 5-letter game"),
    ("new6", "Start a 6-letter game"), ("new7", "Start a 7-letter game"), ("hint", "Get a hint"),
    ("skip", "Reveal the word and end the game"), ("cancel", "Cancel the current game"),
    ("daily", "Daily word challenge"), ("leaderboard", "Show the leaderboard"),
    ("stats", "Your statistics"), ("score", "Score: /score @user global week"), ("myscore", "Your score"),
    ("end", "End the current game"), ("allowonlylen", "Allowed word lengths (admins)"), ("profile", "Your profile"), ("rank", "Your rank"),
    ("history", "Your recent games"), ("rules", "Game rules"), ("help", "Help & commands"),
    ("id", "Show your Telegram & chat IDs"), ("start", "Welcome screen"),
]


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, (TimedOut, NetworkError)) and not isinstance(err, BadRequest):
        log.warning("network problem: %s", err)
        return
    log.error("unhandled error", exc_info=err, extra={"ctx": {"update": str(update)[:300]}})


async def _expire_loop(ctx: AppContext) -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            n = await ctx.games.expire_stale(ctx.settings.game_timeout_hours)
            if n:
                log.info("expired stale games", extra={"ctx": {"count": n}})
        except Exception:  # noqa: BLE001
            log.exception("expire loop failed")


async def _health_server(port: int):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(reader.read(1024), 5)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()
    return await asyncio.start_server(handle, "0.0.0.0", port)


async def post_init(app: Application) -> None:
    ctx: AppContext = app.bot_data["ctx"]
    await ctx.db.connect()
    await ctx.load_state()
    expired = await ctx.games.expire_stale(ctx.settings.game_timeout_hours)
    try:
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
    except Exception as e:  # noqa: BLE001
        log.warning("set_my_commands failed: %s", e)
    app.bot_data["tasks"] = [asyncio.create_task(_expire_loop(ctx))]
    if ctx.settings.health_port:
        app.bot_data["health"] = await _health_server(ctx.settings.health_port)
    me = await app.bot.get_me()
    log.info("bot started", extra={"ctx": {"username": me.username, "expired_on_boot": expired}})
    if me.username.lower() != ctx.settings.bot_username.lower():
        log.warning("BOT_USERNAME (%s) differs from the real username (%s)", ctx.settings.bot_username, me.username)


async def post_shutdown(app: Application) -> None:
    for t in app.bot_data.get("tasks", []):
        t.cancel()
    if srv := app.bot_data.get("health"):
        srv.close()
    await app.bot_data["ctx"].db.close()
    log.info("shutdown complete")


def build_application(settings: Settings, builder: ApplicationBuilder | None = None) -> Application:
    ctx = build_context(settings)
    b = builder or ApplicationBuilder().token(settings.bot_token)
    app = b.concurrent_updates(True).post_init(post_init).post_shutdown(post_shutdown).build()
    app.bot_data["ctx"] = ctx
    M = filters.UpdateType.MESSAGE

    app.add_handler(TypeHandler(Update, admin.access_guard), group=-1)

    def cmd(names, fn):
        app.add_handler(CommandHandler(names, fn, filters=M))

    cmd("start", start.start_cmd)
    cmd("help", help_h.help_cmd)
    cmd("rules", help_h.rules_cmd)
    cmd("new", game.make_new(None))
    for n in (4, 5, 6, 7):
        cmd(f"new{n}", game.make_new(n))
    cmd("hint", game.hint_cmd)
    cmd("skip", game.make_end("skipped"))
    cmd("cancel", game.make_end("cancelled"))
    cmd("id", game.id_cmd)
    cmd("daily", daily.daily_cmd)
    cmd("leaderboard", leaderboard.leaderboard_cmd)
    cmd("stats", profile.stats_cmd)
    cmd("profile", profile.profile_cmd)
    cmd("history", profile.history_cmd)
    cmd("rank", profile.rank_cmd)
    cmd("score", profile.score_cmd)
    cmd("myscore", profile.myscore_cmd)
    cmd("end", game.make_end("cancelled"))
    cmd("allowonlylen", game.allowonlylen_cmd)
    cmd("transfer", admin.transfer_cmd)
    cmd("admin", admin.admin_cmd)
    cmd("botstats", admin.botstats_cmd)
    cmd("broadcast", admin.broadcast_cmd)
    cmd("ban", admin.ban_cmd)
    cmd("unban", admin.unban_cmd)
    cmd("userinfo", admin.userinfo_cmd)
    cmd("maintenance", admin.maintenance_cmd)
    cmd("reloadwords", admin.reloadwords_cmd)
    cmd("backup", admin.backup_cmd)
    cmd("emojipack", admin.emojipack_cmd)
    cmd("emojiset", admin.emojiset_cmd)
    cmd("emojitest", admin.emojitest_cmd)
    cmd("richtest", admin.richtest_cmd)
    cmd("emojireset", admin.emojireset_cmd)

    app.add_handler(CallbackQueryHandler(help_h.help_callback, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(leaderboard.leaderboard_callback, pattern=r"^lb\|"))
    app.add_handler(CallbackQueryHandler(daily.daily_callback, pattern=r"^daily:rank$"))
    app.add_handler(CallbackQueryHandler(game.hint_letter_callback, pattern=r"^wh:"))
    app.add_handler(CallbackQueryHandler(leaderboard.noop_callback, pattern=r"^noop$"))
    app.add_handler(ChatMemberHandler(admin.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & M, game.on_text))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level, settings.log_dir)
    if not settings.bot_token:
        log.error("BOT_TOKEN is missing. Copy .env.example to .env and set it.")
        sys.exit(1)
    app = build_application(settings)
    log.info("starting polling")
    app.run_polling(
        allowed_updates=["message", "callback_query", "my_chat_member"],
        bootstrap_retries=-1,  # keep retrying if Telegram is unreachable at boot
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
