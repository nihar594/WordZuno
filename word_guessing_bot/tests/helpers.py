"""Test harness: a fake Telegram network layer so real handlers run end-to-end."""
from __future__ import annotations

import dataclasses
import itertools
import json
import tempfile
import time
import unittest
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationBuilder
from telegram.request import BaseRequest

import config
import main

BOT = {"id": 999, "is_bot": True, "first_name": "Word Zuno", "username": "WordZunoBot",
       "can_join_groups": True, "can_read_all_group_messages": True, "supports_inline_queries": False}


class FakeRequest(BaseRequest):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._mid = itertools.count(1000)
        self.fail_rich = False

    @property
    def read_timeout(self):  # noqa: D401
        return 5

    async def initialize(self) -> None: ...
    async def shutdown(self) -> None: ...

    async def do_request(self, url, method, request_data=None, read_timeout=None, write_timeout=None,
                         connect_timeout=None, pool_timeout=None):
        name = url.rsplit("/", 1)[-1]
        p = dict(request_data.parameters) if request_data else {}
        self.calls.append((name, p))
        result: object = True
        if name == "getMe":
            result = BOT
        elif name in ("sendMessage", "sendPhoto", "editMessageText", "sendDocument"):
            cid = int(p.get("chat_id", 1))
            result = {"message_id": next(self._mid), "date": int(time.time()), "from": BOT,
                      "chat": {"id": cid, "type": "private" if cid > 0 else "supergroup", "title": "T"},
                      "text": p.get("text") or p.get("caption", "")}
        elif name == "sendRichMessage":
            if self.fail_rich:
                return 400, json.dumps({"ok": False, "error_code": 400,
                                        "description": "Bad Request: method is not supported"}).encode()
            result = {"message_id": next(self._mid), "date": int(time.time()), "from": BOT,
                      "chat": {"id": int(p["chat_id"]), "type": "private"}}
        elif name == "getStickerSet":
            result = {"name": p.get("name"), "title": "L", "sticker_type": "custom_emoji", "stickers": [
                {"file_id": f"f{i}", "file_unique_id": f"u{i}", "type": "custom_emoji", "width": 100, "height": 100,
                 "is_animated": False, "is_video": False, "emoji": "🙂", "custom_emoji_id": str(5000000 + i)}
                for i in range(78)]}
        elif name == "copyMessage":
            result = {"message_id": next(self._mid)}
        elif name == "getChatMember":
            result = {"status": "administrator" if p.get("user_id") == 777 else "member",
                      "user": {"id": p.get("user_id", 1), "is_bot": False, "first_name": "x"}}
        return 200, json.dumps({"ok": True, "result": result}).encode()

    # convenience ------------------------------------------------------
    def texts(self) -> list[str]:
        return [p.get("text") or p.get("caption") or "" for n, p in self.calls
                if n in ("sendMessage", "editMessageText", "sendPhoto")]

    def last(self) -> str:
        t = self.texts()
        return t[-1] if t else ""

    def rich_html(self) -> str:
        rm = [p for n, p in self.calls if n == "sendRichMessage"][-1]["rich_message"]
        return (json.loads(rm) if isinstance(rm, str) else rm)["html"]

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.calls if n == name)

    def last_params(self, name: str) -> dict:
        return [p for n, p in self.calls if n == name][-1]

    def clear(self) -> None:
        self.calls.clear()


class BotTestCase(unittest.IsolatedAsyncioTestCase):
    ADMIN = 777
    extra_settings: dict = {}
    relax_limits = True

    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        base = config.load_settings()
        self.settings = dataclasses.replace(
            base, bot_token="123:ABC", admin_ids=frozenset({self.ADMIN}), db_path=tmp / "t.db",
            log_dir=tmp / "logs", board_style="text", banner_path=tmp / "no-banner.png", **self.extra_settings)
        await self._boot()
        self._uid = itertools.count(1)

    async def _boot(self) -> None:
        self.fake = FakeRequest()
        builder = ApplicationBuilder().token("123:ABC").request(self.fake).get_updates_request(FakeRequest())
        self.app = main.build_application(self.settings, builder)
        await self.app.initialize()
        await main.post_init(self.app)
        self.ctx = self.app.bot_data["ctx"]
        if self.relax_limits:
            from utils.ratelimit import RateLimiter
            for n in ("rate_guess", "rate_cmd", "rate_cb"):
                setattr(self.ctx, n, RateLimiter(10**6, 1))

    async def _shutdown(self) -> None:
        await main.post_shutdown(self.app)
        await self.app.shutdown()

    async def asyncTearDown(self) -> None:
        await self._shutdown()
        self.tmp.cleanup()

    # ------------------------------------------------------------ helpers
    def _msg(self, uid: int, chat_id: int, text: str, name: str = "Tester", reply_to: dict | None = None) -> dict:
        m = {"message_id": next(self._uid) + 5000, "date": int(time.time()),
             "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup", "title": "Grp"},
             "from": {"id": uid, "is_bot": False, "first_name": name}, "text": text}
        if text.startswith("/"):
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        if reply_to:
            m["reply_to_message"] = reply_to
        return m

    async def say(self, uid: int, text: str, chat_id: int | None = None, name: str = "Tester", **kw) -> dict:
        chat_id = uid if chat_id is None else chat_id
        msg = self._msg(uid, chat_id, text, name, **kw)
        await self.app.process_update(Update.de_json({"update_id": next(self._uid) + 9000, "message": msg}, self.app.bot))
        return msg

    async def press(self, uid: int, data: str, chat_id: int | None = None, name: str = "Tester") -> None:
        chat_id = uid if chat_id is None else chat_id
        msg = self._msg(999, chat_id, "board")
        msg["from"] = BOT
        upd = {"update_id": next(self._uid) + 9000,
               "callback_query": {"id": f"cb{next(self._uid)}", "chat_instance": "x", "data": data,
                                  "from": {"id": uid, "is_bot": False, "first_name": name}, "message": msg}}
        await self.app.process_update(Update.de_json(upd, self.app.bot))

    async def secret(self, chat_id: int) -> str:
        row = await self.ctx.db.fetchone("SELECT secret_word FROM games WHERE chat_id=? AND status='active'", (chat_id,))
        return row["secret_word"]

    def wrong_words(self, length: int, secret: str, n: int) -> list[str]:
        words = sorted(w for w in self.ctx.words._valid[length] if w != secret)
        return words[:n]
