import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from database.db import Database
from database.models import Player
from services.context import build_context
from services.game_service import evaluate
from services.leaderboard_service import period_start
import dataclasses


class EvaluateTests(unittest.TestCase):
    def test_all_green(self):
        self.assertEqual(evaluate("peer", "peer"), "GGGG")

    def test_duplicate_letters_guess_has_more(self):
        # secret has two E, guess has three E -> only two E's coloured
        self.assertEqual(evaluate("speed", "eerie"), "YYBBB")
        self.assertEqual(evaluate("peer", "eeee"), "BGGB")

    def test_greens_take_priority(self):
        self.assertEqual(evaluate("abbey", "babes"), "YYGGB")
        self.assertEqual(evaluate("crane", "eerie"), "BBYBG")

    def test_absent(self):
        self.assertEqual(evaluate("word", "zzzz"), "BBBB")


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        s = dataclasses.replace(config.load_settings(), db_path=Path(self.tmp.name) / "s.db")
        self.settings = s
        self.ctx = build_context(s)
        await self.ctx.db.connect()
        self.g = self.ctx.games
        self.a, self.b = Player(1, "Alice"), Player(2, "Bob")
        for p in (self.a, self.b):
            await self.g.upsert_user(p)

    async def asyncTearDown(self):
        await self.ctx.db.close()
        self.tmp.cleanup()

    async def secret(self, chat):
        return (await self.ctx.db.fetchone("SELECT secret_word FROM games WHERE chat_id=? AND status='active'", (chat,)))[0]

    def wrongs(self, n, secret, count):
        return [w for w in sorted(self.ctx.words._valid[n]) if w != secret][:count]

    async def test_one_active_game_per_chat(self):
        r1 = await self.g.start(10, 4, self.a)
        r2 = await self.g.start(10, 6, self.b)
        self.assertTrue(r1.created)
        self.assertFalse(r2.created)
        self.assertEqual(r2.game.word_length, 4)

    async def test_all_lengths(self):
        for n in (4, 5, 6, 7):
            r = await self.g.start(100 + n, n, self.a)
            self.assertEqual(len(r.game.secret_word), n)
            self.assertTrue(self.ctx.words.is_valid(r.game.secret_word))

    async def test_invalid_and_duplicate_do_not_consume(self):
        await self.g.start(10, 4, self.a)
        out = await self.g.process_guess(10, self.a, "zzzq")
        self.assertEqual(out.kind, "invalid")
        sec = await self.secret(10)
        w = self.wrongs(4, sec, 2)
        self.assertEqual((await self.g.process_guess(10, self.a, w[0])).kind, "wrong")
        self.assertEqual((await self.g.process_guess(10, self.a, w[0])).kind, "duplicate")
        out = await self.g.process_guess(10, self.a, w[1])
        self.assertEqual(len(out.guesses), 2)

    async def test_win_awards_once_and_updates_stats(self):
        await self.g.start(10, 4, self.a)
        sec = await self.secret(10)
        out = await self.g.process_guess(10, self.a, sec)
        self.assertEqual(out.kind, "won")
        self.assertEqual(out.reward.total, 15)
        again = await self.g.process_guess(10, self.a, sec)
        self.assertEqual(again.kind, "no_game")
        u = await self.ctx.boards.user(1)
        self.assertEqual((u["total_points"], u["games_won"], u["games_played"], u["current_streak"]), (15, 1, 1, 1))
        tx = await self.ctx.db.fetchall("SELECT * FROM transactions")
        self.assertEqual(len(tx), 1)

    async def test_loss_after_30_valid_guesses(self):
        await self.g.start(10, 4, self.a)
        sec = await self.secret(10)
        outs = [await self.g.process_guess(10, self.a, w) for w in self.wrongs(4, sec, 30)]
        self.assertTrue(all(o.kind == "wrong" for o in outs[:29]))
        self.assertEqual(outs[-1].kind, "lost")
        self.assertEqual(len(outs[-1].guesses), 30)
        u = await self.ctx.boards.user(1)
        self.assertEqual((u["games_lost"], u["total_points"], u["current_streak"]), (1, 0, 0))
        self.assertIsNone(await self.g.get_active(10))
        self.assertTrue((await self.g.start(10, 4, self.a)).created)  # new game after finishing

    async def test_multiplayer_independent_chats_and_winner(self):
        await self.g.start(10, 5, self.a)
        await self.g.start(20, 5, self.b)
        s10, s20 = await self.secret(10), await self.secret(20)
        w = self.wrongs(5, s10, 1)[0]
        await self.g.process_guess(10, self.b, w)
        out = await self.g.process_guess(10, self.a, s10)
        self.assertEqual(out.kind, "won")
        ub = await self.ctx.boards.user(2)
        self.assertEqual((ub["games_lost"], ub["total_points"]), (1, 0))  # participant who didn't win
        self.assertIsNotNone(await self.g.get_active(20))                  # other chat untouched

    async def test_simultaneous_correct_guesses_single_winner(self):
        await self.g.start(10, 4, self.a)
        sec = await self.secret(10)
        res = await asyncio.gather(self.g.process_guess(10, self.a, sec), self.g.process_guess(10, self.b, sec))
        self.assertEqual(sorted(r.kind for r in res), ["no_game", "won"])
        tx = await self.ctx.db.fetchall("SELECT * FROM transactions")
        self.assertEqual(len(tx), 1)

    async def test_many_simultaneous_guesses_consistent(self):
        await self.g.start(10, 4, self.a)
        sec = await self.secret(10)
        words = self.wrongs(4, sec, 20)
        players = [Player(100 + i, f"P{i}") for i in range(20)]
        outs = await asyncio.gather(*[self.g.process_guess(10, p, w) for p, w in zip(players, words)])
        self.assertTrue(all(o.kind == "wrong" for o in outs))
        self.assertEqual(len(await self.g.get_guesses((await self.g.get_active(10)).game_id)), 20)

    async def test_streak_bonus_and_multiplayer_bonus(self):
        s = dataclasses.replace(self.settings, streak_bonus=5, streak_min=2, multiplayer_bonus=3)
        ctx = build_context(s)
        ctx.db = self.ctx.db  # share db
        from services.game_service import GameService
        g = GameService(self.ctx.db, ctx.words, ctx.scoring, s)
        totals = []
        for chat in (31, 32):
            await g.start(chat, 4, self.a)
            sec = await self.secret(chat)
            await g.process_guess(chat, self.b, self.wrongs(4, sec, 1)[0])
            out = await g.process_guess(chat, self.a, sec)
            totals.append(out.reward.total)
        self.assertEqual(totals, [15 + 3, 15 + 3 + 5])

    async def test_leaderboard_filters(self):
        for chat, n, p in ((10, 4, self.a), (20, 5, self.b), (10, 4, self.b)):
            await self.g.start(chat, n, p)
            await self.g.process_guess(chat, p, await self.secret(chat))
        lb = self.ctx.boards
        page = await lb.page(scope="g", chat_id=0, period="a", length=0)
        self.assertEqual({r.user_id: r.points for r in page.rows}, {1: 15, 2: 30})
        self.assertEqual(page.rows[0].user_id, 2)
        self.assertEqual((await lb.page(scope="c", chat_id=10, period="t", length=0)).total, 2)
        self.assertEqual((await lb.page(scope="c", chat_id=20, period="a", length=0)).total, 1)
        self.assertEqual((await lb.page(scope="g", chat_id=0, period="a", length=5)).rows[0].points, 15)
        self.assertEqual((await lb.page(scope="g", chat_id=0, period="a", length=6)).total, 0)
        # push one game to last year -> excluded from today/week/month/year, kept in all-time
        await self.ctx.db.execute("UPDATE games SET completed_at='2020-05-05 10:00:00' WHERE chat_id=20")
        self.assertEqual((await lb.page(scope="g", chat_id=0, period="t", length=0)).rows[0].points, 15)
        yr = await lb.page(scope="g", chat_id=0, period="y", length=0)
        self.assertEqual({r.user_id: r.points for r in yr.rows}, {1: 15, 2: 15})
        self.assertEqual((await lb.page(scope="g", chat_id=0, period="a", length=0)).total, 2)

    async def test_leaderboard_pagination(self):
        for i in range(25):
            p = Player(1000 + i, f"U{i}")
            await self.g.upsert_user(p)
            await self.g.start(500 + i, 4, p)
            await self.g.process_guess(500 + i, p, await self.secret(500 + i))
        p1 = await self.ctx.boards.page(scope="g", chat_id=0, period="a", length=0, page=1)
        p3 = await self.ctx.boards.page(scope="g", chat_id=0, period="a", length=0, page=3)
        self.assertEqual((p1.pages, len(p1.rows), len(p3.rows)), (3, 10, 5))

    async def test_period_start(self):
        now = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)  # Tuesday
        self.assertEqual(period_start("t", now), "2026-11-10 00:00:00")
        self.assertEqual(period_start("w", now), "2026-11-09 00:00:00")
        self.assertEqual(period_start("m", now), "2026-11-01 00:00:00")
        self.assertEqual(period_start("y", now), "2026-01-01 00:00:00")
        self.assertIsNone(period_start("a", now))

    async def test_daily_flow_and_rewards(self):
        r = await self.g.start_daily(50, self.a)
        self.assertEqual(r.kind, "new")
        again = await self.g.start_daily(50, self.a)
        self.assertEqual(again.kind, "resume")
        other = await self.g.start_daily(51, self.b)
        self.assertEqual(other.game.secret_word, r.game.secret_word)  # same word for all players
        out = await self.g.process_guess(50, self.a, r.game.secret_word)
        self.assertEqual(out.kind, "won")
        self.assertEqual(out.reward.total, 15 + 10 + 2)  # base + daily bonus + 1-day streak * 2
        done = await self.g.start_daily(50, self.a)
        self.assertEqual(done.kind, "done")
        self.assertEqual(done.status, "won")
        self.assertEqual(len(await self.ctx.boards.daily_ranking(r.game.daily_date)), 1)

    async def test_daily_streak_across_days(self):
        yday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        await self.ctx.db.execute("UPDATE users SET daily_streak=2, last_daily_win=? WHERE user_id=1", (yday,))
        r = await self.g.start_daily(50, self.a)
        out = await self.g.process_guess(50, self.a, r.game.secret_word)
        self.assertEqual(out.daily_streak, 3)
        self.assertEqual(out.reward.daily_streak_bonus, 6)

    async def test_daily_cancel_forfeits(self):
        await self.g.start_daily(50, self.a)
        await self.g.end_game(50, "cancelled")
        self.assertEqual((await self.g.start_daily(50, self.a)).status, "forfeit")

    async def test_hint_limit_and_skip_cancel(self):
        await self.g.start(10, 5, self.a)
        sec = await self.secret(10)
        h1, h2, h3 = [await self.g.hint(10) for _ in range(3)]
        self.assertEqual((h1.kind, h2.kind, h3.kind), ("ok", "ok", "limit"))
        self.assertEqual(h1.letter, sec[h1.position])
        ended = await self.g.end_game(10, "skipped")
        self.assertEqual(ended.secret_word, sec)
        self.assertIsNone(await self.g.end_game(10, "skipped"))

    async def test_expire_stale(self):
        await self.g.start(10, 4, self.a)
        await self.ctx.db.execute("UPDATE games SET last_activity='2020-01-01 00:00:00'")
        self.assertEqual(await self.g.expire_stale(24), 1)
        self.assertIsNone(await self.g.get_active(10))

    async def test_persistence_and_restart_recovery(self):
        await self.g.start(10, 4, self.a)
        sec = await self.secret(10)
        await self.g.process_guess(10, self.a, self.wrongs(4, sec, 1)[0])
        await self.ctx.db.close()
        ctx2 = build_context(self.settings)
        await ctx2.db.connect()
        game = await ctx2.games.get_active(10)
        self.assertEqual(game.secret_word, sec)
        self.assertEqual(len(await ctx2.games.get_guesses(game.game_id)), 1)
        out = await ctx2.games.process_guess(10, self.a, sec)
        self.assertEqual(out.kind, "won")
        await ctx2.db.close()
        await self.ctx.db.connect()  # for tearDown

    async def test_foreign_keys_and_sql_injection(self):
        import sqlite3
        with self.assertRaises(Exception):
            await self.ctx.db.execute("INSERT INTO guesses(game_id,user_id,guessed_word,result,created_at) VALUES(999,1,'abcd','BBBB','x')")
        p = Player(5, "x'); DROP TABLE users;--")
        await self.g.upsert_user(p)
        self.assertEqual((await self.ctx.boards.user(5))["first_name"], "x'); DROP TABLE users;--")
        self.assertIsNotNone(await self.ctx.boards.user(1))
