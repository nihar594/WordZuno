import dataclasses
import json
import unittest

from tests.helpers import BotTestCase

G = -1001  # group chat id


def buttons(params):
    kb = params["reply_markup"]
    kb = kb.to_dict() if hasattr(kb, "to_dict") else kb
    return [b for row in kb["inline_keyboard"] for b in row]


class StartAndHelp(BotTestCase):
    async def test_start_welcome_and_buttons(self):
        await self.say(1, "/start")
        p = self.fake.last_params("sendMessage")
        self.assertIn("Welcome to Word Zuno!", p["text"])
        self.assertIn("Use /new to start a new game", p["text"])
        labels = [b["text"] for b in buttons(p)]
        self.assertEqual(labels, ["Add me to your Group", "Updates", "Help", "Discussion", "💗 Donate"])
        bs = {b["text"]: b for b in buttons(p)}
        self.assertIn("startgroup=true", bs["Add me to your Group"]["url"])
        self.assertEqual(bs["Help"]["callback_data"], "help:open")
        self.assertTrue(all(bs[k]["url"].startswith("https://") for k in ("Updates", "Discussion", "💗 Donate")))

    async def test_start_with_banner_sends_photo(self):
        await self._shutdown()
        banner = self.settings.banner_path.parent / "banner.png"
        banner.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        self.settings = dataclasses.replace(self.settings, banner_path=banner)
        await self._boot()
        await self.say(1, "/start")
        self.assertEqual(self.fake.count("sendPhoto"), 1)
        self.assertIn("Welcome to Word Zuno!", self.fake.last_params("sendPhoto")["caption"])

    async def test_help_flow(self):
        await self.say(1, "/help")
        self.assertIn("Help", self.fake.last())
        for key in ("game", "player", "lb", "group", "daily", "info", "home"):
            await self.press(1, f"help:{key}")
        self.assertIn("Information", self.fake.last() if False else self.fake.texts()[-2])
        self.fake.clear()
        await self.press(1, "help:open")
        self.assertEqual(self.fake.count("sendMessage"), 1)  # Help button from welcome screen

    async def test_info_commands(self):
        await self.say(5, "/rules")
        self.assertIn("Game Rules", self.fake.last())
        await self.say(5, "/id")
        self.assertIn("<code>5</code>", self.fake.last())


class GameFlow(BotTestCase):
    async def test_private_game_full_flow(self):
        await self.say(1, "/new4")
        self.assertEqual(self.fake.last(), "Game started! Guess the 4-letter word!")
        sec = await self.secret(1)
        await self.say(1, "Peec")
        self.assertEqual(self.fake.last(), "peec is not a valid 4-letter word.")
        w1, w2 = self.wrong_words(4, sec, 2)
        await self.say(1, w1.capitalize())
        self.assertIn("4-letter mode", self.fake.last())
        self.assertIn("1/30 guesses", self.fake.last())
        await self.say(1, w2)
        self.assertIn("2/30 guesses", self.fake.last())
        self.assertEqual(self.fake.count("deleteMessage"), 1)  # previous board replaced
        await self.say(1, sec.upper())
        win = self.fake.last()
        self.assertIn("Congrats! You guessed it correctly.", win)
        self.assertIn(f"Correct Word: <b>{sec}</b>", win)
        self.assertIn("Added 15 to the leaderboard.", win)
        self.assertIn("Start with /new4", win)
        await self.say(1, "/new5")
        self.assertIn("Game started! Guess the 5-letter word!", self.fake.last())

    async def test_non_guess_chatter_ignored_in_group(self):
        await self.say(1, "/new4", chat_id=G)
        self.fake.clear()
        for t in ("hello everyone", "hi", "ok", "12345", "peer?", "ab cd"):
            await self.say(2, t, chat_id=G)
        self.assertEqual(self.fake.count("sendMessage"), 0)

    async def test_loss_message(self):
        await self.say(1, "/new4")
        sec = await self.secret(1)
        for w in self.wrong_words(4, sec, 30):
            await self.say(1, w)
        texts = self.fake.texts()
        self.assertIn("30/30 guesses", texts[-2])
        self.assertIn("Game Over!", texts[-1])
        self.assertIn(f"Correct Word: <b>{sec}</b>", texts[-1])
        self.assertIn("Better luck next time!", texts[-1])
        row = await self.ctx.db.fetchone("SELECT games_lost FROM users WHERE user_id=1")
        self.assertEqual(row[0], 1)

    async def test_group_multiplayer(self):
        await self.say(1, "/new5@WordZunoBot", chat_id=G, name="Alice")
        sec = await self.secret(G)
        w = self.wrong_words(5, sec, 1)[0]
        await self.say(2, w, chat_id=G, name="Bob")
        await self.say(3, sec, chat_id=G, name="Cara")
        self.assertIn("<b>Cara</b>", self.fake.last())
        self.assertIn("Added 15", self.fake.last())
        await self.say(1, "/leaderboard", chat_id=G)
        self.assertIn("Group Leaderboard", self.fake.last())
        self.assertIn("🥇 - Cara - 15 pts", self.fake.last())

    async def test_already_running_and_cancel_permissions(self):
        await self.say(1, "/new", chat_id=G)
        await self.say(2, "/new6", chat_id=G)
        self.assertIn("already running", self.fake.last())
        await self.say(2, "/cancel", chat_id=G)  # not starter, not admin
        self.assertIn("Only the player who started", self.fake.last())
        await self.say(777, "/skip", chat_id=G, name="Boss")  # bot admin may end
        self.assertIn("Game skipped", self.fake.last())
        await self.say(1, "/cancel", chat_id=G)
        self.assertIn("No active game", self.fake.last())

    async def test_hint_and_skip_private(self):
        await self.say(1, "/hint")
        self.assertIn("No active game", self.fake.last())
        await self.say(1, "/new5")
        sec = await self.secret(1)
        await self.say(1, "/hint")
        self.assertIn("Hint", self.fake.last())
        await self.say(1, "/skip")
        self.assertIn(sec, self.fake.last())

    async def test_duplicate_update_ignored(self):
        await self.say(1, "/new4")
        sec = await self.secret(1)
        w = self.wrong_words(4, sec, 1)[0]
        m = await self.say(1, w)
        n = self.fake.count("sendMessage")
        from telegram import Update
        await self.app.process_update(Update.de_json({"update_id": 1, "message": m}, self.app.bot))
        self.assertEqual(self.fake.count("sendMessage"), n)

    async def test_edit_mode_edits_single_board(self):
        await self._shutdown()
        self.settings = dataclasses.replace(self.settings, board_mode="edit")
        await self._boot()
        await self.say(1, "/new4")
        sec = await self.secret(1)
        w = self.wrong_words(4, sec, 2)
        await self.say(1, w[0])
        await self.say(1, w[1])
        self.assertEqual(self.fake.count("editMessageText"), 1)
        self.assertIn("2/30 guesses", self.fake.last())


class RateLimits(BotTestCase):
    relax_limits = False

    async def test_guess_spam_is_throttled(self):
        await self.say(1, "/new4")
        sec = await self.secret(1)
        for w in self.wrong_words(4, sec, 30):
            await self.say(1, w)
        n = await self.ctx.db.fetchone("SELECT COUNT(*) FROM guesses")
        self.assertEqual(n[0], 12)  # 12 per 10 seconds

    async def test_command_spam_is_throttled(self):
        for _ in range(10):
            await self.say(1, "/rules")
        self.assertEqual(self.fake.count("sendMessage"), 6)


class StatsAndLeaderboard(BotTestCase):
    async def play_win(self, uid, chat, name="P", length=4):
        await self.say(uid, f"/new{length}", chat_id=chat, name=name)
        await self.say(uid, await self.secret(chat), chat_id=chat, name=name)

    async def test_stats_profile_history_rank(self):
        await self.play_win(1, 1, "Nihar")
        for cmd, needle in (("/stats", "Games played: <b>1</b>"), ("/profile", "Nihar"),
                            ("/history", "Recent games"), ("/rank", "Global rank: <b>#1</b>")):
            await self.say(1, cmd, name="Nihar")
            self.assertIn(needle, self.fake.last(), cmd)
        await self.say(1, "/stats")
        self.assertIn("Win rate: <b>100.0%</b>", self.fake.last())
        self.assertIn("Favorite length: <b>4 letters</b>", self.fake.last())

    async def test_leaderboard_buttons_and_navigation(self):
        await self.play_win(1, G, "Alice")
        await self.play_win(2, G, "Bob")
        await self.say(1, "/leaderboard", chat_id=G)
        p = self.fake.last_params("sendMessage")
        labels = [b["text"] for b in buttons(p)]
        for needle in ("Global", "🔄", "« This chat »", "« Today »", "This week", "This month", "This year",
                       "All time", "4 letters", "« 5 letters »", "6 letters", "7 letters"):
            self.assertIn(needle, labels)
        self.assertIn("🏆 <b>Group Leaderboard</b> 🏆", p["text"])
        for data in ("lb|g|t|0|1", "lb|c|w|4|1", "lb|c|m|0|1", "lb|c|y|5|1", "lb|c|a|0|1", "lb|c|a|6|1", "lb|g|a|0|1"):
            self.fake.clear()
            await self.press(3, data, chat_id=G)
            self.assertEqual(self.fake.count("editMessageText"), 1, data)
        self.assertIn("Global Leaderboard", self.fake.last())
        self.fake.clear()
        await self.press(3, "lb|c|a|6|1", chat_id=G)
        self.assertIn("No games played yet", self.fake.last())
        sel = [b["text"] for b in buttons(self.fake.last_params("editMessageText"))]
        self.assertIn("« 6 letters »", sel)

    async def test_refresh_unchanged_does_not_crash_and_garbage_callback(self):
        await self.press(3, "lb|x|?|99|abc", chat_id=G)
        await self.press(3, "noop", chat_id=G)

    async def test_pagination_buttons(self):
        for i in range(12):
            await self.play_win(100 + i, G, f"U{i}", length=5)
        await self.say(1, "/leaderboard", chat_id=G)
        labels = [b["text"] for b in buttons(self.fake.last_params("sendMessage"))]
        self.assertIn("1/2", labels)
        await self.press(1, "lb|c|t|5|2", chat_id=G)
        self.assertIn("🔆", self.fake.last())


class DailyAndAdmin(BotTestCase):
    async def test_daily_private_flow(self):
        await self.say(1, "/daily")
        self.assertIn("Daily Challenge", self.fake.last())
        sec = await self.secret(1)
        await self.say(1, sec)
        self.assertIn("Added 27 to the leaderboard", self.fake.last())
        await self.say(1, "/daily")
        self.assertIn("already played", self.fake.last())
        await self.press(1, "daily:rank")
        self.assertIn("Daily ranking", self.fake.last())

    async def test_daily_in_group_redirects(self):
        await self.say(1, "/daily", chat_id=G)
        self.assertIn("private chat", self.fake.last())
        await self.say(1, "/start daily")
        self.assertIn("Daily Challenge", self.fake.last())

    async def test_admin_permissions(self):
        for cmd in ("/admin", "/broadcast hi", "/ban 5", "/unban 5", "/userinfo 5", "/botstats",
                    "/maintenance on", "/reloadwords", "/backup"):
            self.fake.clear()
            await self.say(5, cmd)
            self.assertIn("not authorized", self.fake.last(), cmd)
        self.assertFalse(self.ctx.maintenance)

    async def test_admin_commands_work(self):
        await self.say(5, "/new4", name="Victim")
        await self.say(self.ADMIN, "/admin")
        self.assertIn("Admin panel", self.fake.last())
        await self.say(self.ADMIN, "/botstats")
        self.assertIn("Bot statistics", self.fake.last())
        await self.say(self.ADMIN, "/userinfo 5")
        self.assertIn("Victim", self.fake.last())
        await self.say(self.ADMIN, "/reloadwords")
        self.assertIn("reloaded", self.fake.last())
        await self.say(self.ADMIN, "/ban 5 spam")
        self.assertIn("banned", self.fake.last())
        self.fake.clear()
        await self.say(5, "/new4")
        self.assertIn("banned", self.fake.last())
        await self.say(self.ADMIN, "/unban 5")
        await self.say(5, "/stats")
        self.assertIn("Statistics", self.fake.last())
        await self.say(self.ADMIN, f"/ban {self.ADMIN}")
        self.assertIn("cannot ban an admin", self.fake.last())

    async def test_maintenance_mode(self):
        await self.say(self.ADMIN, "/maintenance on")
        await self.say(5, "/new4")
        self.assertIn("maintenance", self.fake.last())
        await self.say(self.ADMIN, "/new4")
        self.assertIn("Game started", self.fake.last())
        await self._shutdown()
        await self._boot()  # restart keeps maintenance flag
        self.assertTrue(self.ctx.maintenance)
        await self.say(self.ADMIN, "/maintenance off")
        await self.say(5, "/new4")
        self.assertIn("Game started", self.fake.last())

    async def test_broadcast_and_backup(self):
        await self.say(5, "/start")
        await self.say(6, "/start")
        self.fake.clear()
        await self.say(self.ADMIN, "/broadcast Hello everyone")
        sent = [p for n, p in self.fake.calls if n == "sendMessage" and p["chat_id"] in (5, 6)]
        self.assertEqual({p["text"] for p in sent}, {"Hello everyone"})
        self.assertIn("Sent: <b>3</b>", self.fake.last())
        await self.say(self.ADMIN, "/backup")
        self.assertEqual(self.fake.count("sendDocument"), 1)

    async def test_restart_recovery_of_active_game(self):
        await self.say(1, "/new4")
        sec = await self.secret(1)
        await self._shutdown()
        await self._boot()
        await self.say(1, sec)
        self.assertIn("Congrats!", self.fake.last())

    async def test_simultaneous_users_in_group(self):
        import asyncio
        await self.say(1, "/new4", chat_id=G)
        sec = await self.secret(G)
        words = self.wrong_words(4, sec, 15)
        await asyncio.gather(*[self.say(10 + i, w, chat_id=G) for i, w in enumerate(words)])
        row = await self.ctx.db.fetchone("SELECT COUNT(*) FROM guesses")
        self.assertEqual(row[0], 15)


if __name__ == "__main__":
    unittest.main()


class PillLetters(BotTestCase):
    async def test_emoji_pack_setup_and_board_pills(self):
        await self.say(5, "/emojipack Pack GYB")
        self.assertIn("not authorized", self.fake.last())
        await self.say(self.ADMIN, "/emojipack")
        self.assertIn("Pill letters", self.fake.last())
        await self.say(self.ADMIN, "/emojipack Pack GYB")
        self.assertIn("Status: <b>ON", self.fake.last())
        self.assertTrue(self.ctx.emoji.ready)
        await self.say(self.ADMIN, "/emojitest")
        self.assertIn('<tg-emoji emoji-id="5000000">', self.fake.last())
        await self.say(1, "/new4")
        sec = await self.secret(1)
        w = self.wrong_words(4, sec, 1)[0]
        await self.say(1, w)
        board = self.fake.last()
        self.assertEqual(board.count("<tg-emoji"), 4)
        self.assertNotIn("Ａ", board)
        # persisted across restart
        await self._shutdown()
        await self._boot()
        self.assertTrue(self.ctx.emoji.ready)
        await self.say(self.ADMIN, "/emojireset")
        self.assertFalse(self.ctx.emoji.ready)

    async def test_emojiset_needs_26(self):
        await self.say(self.ADMIN, "/emojiset G")
        self.assertIn("Pill letters", self.fake.last())

    async def test_entity_budget_falls_back_for_old_rows(self):
        from utils.emoji import EmojiStore
        from utils.formatting import render_board
        from database.models import Game, GuessRow
        st = EmojiStore(self.settings.db_path.parent / "e2.json")
        for c in "GYB":
            st.set_color(c, [str(i) for i in range(26)])
        g = Game(1, 1, "7", 7, "abcdefg", "active", 30, 1, None, None, 0, None, "", "", None)
        rows = [GuessRow(i, 1, 1, "abcdefg", "GYBGYBG", "") for i in range(30)]
        text = render_board(g, rows, st)
        self.assertLessEqual(text.count("<tg-emoji"), 90)
        self.assertGreater(text.count("<tg-emoji"), 60)
        self.assertIn("Ａ", text)  # oldest rows are plain
        self.assertLess(len(text), 4096)


class RichBoard(BotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self._shutdown()
        self.settings = dataclasses.replace(self.settings, board_style="rich")
        await self._boot()

    async def test_rich_pill_board(self):
        await self.say(1, "/new4")
        sec = await self.secret(1)
        w = self.wrong_words(4, sec, 2)
        await self.say(1, w[0])
        html = self.fake.rich_html()
        self.assertIn("<h3>4-letter mode</h3>", html)
        self.assertIn("1/30 guesses", html)
        self.assertEqual(html.count("<tg-button"), 4)
        self.assertIn('data="wh:', html)
        await self.say(1, w[1])
        html = self.fake.rich_html()
        self.assertEqual(html.count("<tg-button"), 8)
        self.assertEqual(self.fake.count("deleteMessage"), 1)

    async def test_pill_colors(self):
        from utils.rich import rich_row
        row = rich_row("peer", "GYBB")
        self.assertIn('style="success" data="wh:correct:P"', row)
        self.assertIn('data="wh:present:E"', row)
        self.assertNotIn('style="primary"', row)
        self.assertEqual(row.count('style="danger"'), 2)

    async def test_letter_tap_explains(self):
        await self.press(1, "wh:correct:P")
        p = self.fake.last_params("answerCallbackQuery")
        self.assertIn('"P" is in the word and in the right spot', p["text"])

    async def test_fallback_to_text_board_when_rich_refused(self):
        self.fake.fail_rich = True
        await self.say(1, "/new4")
        sec = await self.secret(1)
        w = self.wrong_words(4, sec, 4)
        for x in w:
            await self.say(1, x)
        self.assertIn("4/30 guesses", self.fake.last())      # text board still delivered
        self.assertFalse(self.ctx.rich_enabled)              # disabled after repeated refusals

    async def test_richtest_command(self):
        await self.say(self.ADMIN, "/richtest")
        self.assertIn("works", self.fake.last())
        self.fake.fail_rich = True
        await self.say(self.ADMIN, "/richtest")
        self.assertIn("refused", self.fake.last())


class WordSeekExtras(BotTestCase):
    async def force_secret(self, chat, word):
        await self.ctx.db.execute("UPDATE games SET secret_word=? WHERE chat_id=? AND status='active'", (word, chat))

    async def test_meaning_pronunciation_example_on_win_and_reaction(self):
        await self.say(1, "/new5")
        await self.force_secret(1, "aback")
        await self.say(1, "aback")
        win = self.fake.texts()[-1]
        self.assertIn("<b>Meaning</b>: Toward the back or rear", win)
        self.assertIn("<code>/əˈbæk/</code>", win)
        self.assertIn("<b>Example</b>:", win)
        self.assertIn("Start with /new5", win)
        self.assertEqual(self.fake.count("setMessageReaction"), 1)

    async def test_meaning_on_skip_and_loss_for_known_word(self):
        await self.say(1, "/new5")
        await self.force_secret(1, "abase")
        await self.say(1, "/skip")
        self.assertIn("Meaning", self.fake.last())

    async def test_duplicate_message_text(self):
        await self.say(1, "/new4", chat_id=G)
        w = self.wrong_words(4, await self.secret(G), 1)[0]
        await self.say(1, w, chat_id=G)
        await self.say(2, w, chat_id=G)
        self.assertEqual(self.fake.last(), "Someone has already guessed your word. Please try another one!")

    async def test_score_and_myscore(self):
        await self.say(1, "/new5", chat_id=G, name="Nihar")
        await self.say(1, await self.secret(G), chat_id=G, name="Nihar")
        await self.say(1, "/myscore", chat_id=G, name="Nihar")
        self.assertIn("<b>15</b> points in this chat", self.fake.last())
        self.assertIn("Rank: <b>#1</b>", self.fake.last())
        await self.say(2, "/score global week 5 @nobody", chat_id=G)
        self.assertIn("User not found", self.fake.last())
        await self.say(2, "/score 1 global today 5", chat_id=G)
        self.assertIn("globally", self.fake.last())
        self.assertIn("Today · 5 letters", self.fake.last())
        await self.say(2, "/score 1 global today 6", chat_id=G)
        self.assertIn("no scores", self.fake.last())
        await self.say(2, "/score @" + "ghost", chat_id=G)
        self.assertIn("User not found", self.fake.last())

    async def test_allowonlylen_and_end(self):
        await self.say(1, "/allowonlylen", chat_id=G)
        self.assertIn("4, 5, 6, 7", self.fake.last())
        await self.say(2, "/allowonlylen 5 4", chat_id=G)           # regular member (fake getChatMember -> member)
        self.assertIn("Only group admins", self.fake.last())
        await self.say(777, "/allowonlylen 5 4", chat_id=G, name="Boss")
        self.assertIn("Default length: <b>5</b>", self.fake.last())
        await self.say(1, "/new6", chat_id=G)
        self.assertIn("Only 5, 4-letter games are allowed", self.fake.last())
        await self.say(1, "/new4", chat_id=G)
        self.assertIn("Game started", self.fake.last())
        await self.say(1, "/end", chat_id=G)
        self.assertIn("Game cancelled", self.fake.last())
        await self.say(777, "/allowonlylen all", chat_id=G, name="Boss")
        await self.say(1, "/new7", chat_id=G)
        self.assertIn("Game started! Guess the 7-letter word!", self.fake.last())
        await self.say(777, "/allowonlylen 9", chat_id=G, name="Boss")
        self.assertIn("only: 4, 5, 6, 7", self.fake.last())

    async def test_transfer_and_username_ban(self):
        for uid, name in ((1, "Old"), (2, "New")):
            await self.say(uid, "/new4", name=name)
            await self.say(uid, await self.secret(uid), name=name)
        await self.ctx.db.execute("UPDATE users SET username='oldy' WHERE user_id=1")
        await self.ctx.db.execute("UPDATE users SET username='newy' WHERE user_id=2")
        await self.say(5, "/transfer @oldy @newy")
        self.assertIn("not authorized", self.fake.last())
        await self.say(self.ADMIN, "/transfer @oldy")
        self.assertIn("Usage", self.fake.last())
        await self.say(self.ADMIN, "/transfer @oldy @oldy")
        self.assertIn("same user", self.fake.last())
        await self.say(self.ADMIN, "/transfer @oldy @newy")
        self.assertIn("Points: <b>15</b>", self.fake.last())
        old, new = await self.ctx.boards.user(1), await self.ctx.boards.user(2)
        self.assertEqual((old["total_points"], new["total_points"], new["games_won"]), (0, 30, 2))
        page = await self.ctx.boards.page(scope="g", chat_id=0, period="a", length=0)
        self.assertEqual([(r.user_id, r.points) for r in page.rows], [(2, 30)])
        await self.say(self.ADMIN, "/ban @newy spam")
        self.assertIn("banned", self.fake.last())
        self.assertIn(2, self.ctx.banned)
        await self.say(self.ADMIN, "/unban @newy")
        self.assertNotIn(2, self.ctx.banned)
        await self.say(self.ADMIN, "/ban @nobody")
        self.assertIn("Usage", self.fake.last())


class ScoringModes(unittest.TestCase):
    def test_remaining_mode(self):
        from services.scoring import Scoring
        import config
        s = dataclasses.replace(config.load_settings(), scoring_mode="remaining")
        sc = Scoring(s)
        self.assertEqual(sc.for_win(streak_after=1, participants=1, daily=False, attempts=2, max_guesses=30).base, 28)
        self.assertEqual(sc.for_win(streak_after=1, participants=1, daily=False, attempts=30, max_guesses=30).base, 1)
        fixed = Scoring(dataclasses.replace(s, scoring_mode="fixed"))
        self.assertEqual(fixed.for_win(streak_after=1, participants=1, daily=False, attempts=2).base, 15)


class RichHelp(BotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self._shutdown()
        self.settings = dataclasses.replace(self.settings, board_style="rich", github_url="https://github.com/x/y")
        await self._boot()

    def kb_labels(self, params):
        return [b["text"] for b in buttons(params)]

    async def test_help_is_rich_with_wordseek_layout(self):
        await self.say(1, "/help")
        html = self.fake.rich_html()
        self.assertIn("<h3>How to Play Word Zuno</h3>", html)
        self.assertIn("<h4>Reading the colors</h4>", html)
        self.assertIn('<table bordered compact>', html)
        self.assertIn("<details><summary>Daily Mode (Private Chat Only)</summary>", html)
        self.assertIn('style="success" data="wh:correct:S"', html)
        self.assertEqual(html.count("<tg-button"), 8)  # 3 legend + 5 example pills
        p = self.fake.last_params("sendRichMessage")
        labels = self.kb_labels(p)
        self.assertEqual(labels, ["« How to Play »", "Leaderboard & Scores", "Group Settings", "Other Commands",
                                  "GitHub Repo", "📢 Updates", "💗 Donate", "💬 Discussion"])
        self.assertNotIn("Admin", " ".join(labels))

    async def test_help_navigation_and_admin_page(self):
        await self.say(1, "/help")
        for key, needle in (("scores", "Leaderboard &amp; Scores"), ("group", "Group Settings (Admin Only)"),
                            ("other", "Other Commands"), ("howto", "How to Play")):
            self.fake.clear()
            await self.press(1, f"help:{key}")
            edit = self.fake.last_params("editMessageText")
            rm = edit["rich_message"]
            html = (json.loads(rm) if isinstance(rm, str) else rm)["html"]
            self.assertIn(needle, html, key)
            self.assertIn("« ", "".join(self.kb_labels(edit)))
        self.fake.clear()
        await self.press(1, "help:admin")  # not an admin
        self.assertEqual(self.fake.count("editMessageText"), 0)
        await self.say(self.ADMIN, "/help")
        self.assertIn("👑 Admin Commands", self.kb_labels(self.fake.last_params("sendRichMessage")))
        await self.press(self.ADMIN, "help:admin")
        self.assertIn("Admin Commands (Bot Owner Only)", json.dumps(self.fake.last_params("editMessageText")["rich_message"]))

    async def test_help_in_group_has_no_admin_button_and_fallback(self):
        await self.say(self.ADMIN, "/help", chat_id=G)
        self.assertNotIn("👑 Admin Commands", self.kb_labels(self.fake.last_params("sendRichMessage")))
        self.fake.fail_rich = True
        self.fake.clear()
        await self.say(1, "/help")
        self.assertIn("Help", self.fake.last())  # plain-text help fallback

    async def test_welcome_help_button_sends_rich_help(self):
        await self.press(1, "help:open")
        self.assertEqual(self.fake.count("sendRichMessage"), 1)


class CommandArgs(BotTestCase):
    async def test_new_with_space_argument_and_leaderboard_args(self):
        await self.say(1, "/new 4", chat_id=G)
        self.assertIn("Guess the 4-letter word", self.fake.last())
        await self.say(1, await self.secret(G), chat_id=G, name="Ann")
        for args, title in (("", "Group Leaderboard"), ("global week 4", "Global Leaderboard"), ("4", "Group Leaderboard")):
            await self.say(1, f"/leaderboard {args}".strip(), chat_id=G)
            self.assertIn(title, self.fake.last())
        await self.say(1, "/leaderboard 4", chat_id=G)
        self.assertIn("- 15 pts", self.fake.last())
        await self.say(1, "/leaderboard", chat_id=G)  # default = today, 5-letter -> nothing yet
        self.assertIn("No games played yet", self.fake.last())
