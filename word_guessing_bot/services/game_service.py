"""Core game logic: starting games, evaluating guesses, scoring, daily challenge."""
from __future__ import annotations

import asyncio
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from config import Settings
from database.db import Database, Executor
from database.models import Game, GuessRow, Player
from services.scoring import Reward, Scoring
from services.word_service import WordService
from utils.formatting import parse_date, today_utc, utcnow
from utils.logger import get_logger

log = get_logger(__name__)


class AlreadyFinished(Exception):
    pass


def evaluate(secret: str, guess: str) -> str:
    """Wordle rules with correct duplicate-letter handling. G=green, Y=yellow, B=absent."""
    res = ["B"] * len(secret)
    remaining: Counter[str] = Counter()
    for i, (s, g) in enumerate(zip(secret, guess)):
        if s == g:
            res[i] = "G"
        else:
            remaining[s] += 1
    for i, g in enumerate(guess):
        if res[i] == "G":
            continue
        if remaining[g] > 0:
            res[i] = "Y"
            remaining[g] -= 1
    return "".join(res)


@dataclass
class StartResult:
    game: Game
    created: bool


@dataclass
class GuessOutcome:
    kind: Literal["no_game", "ignore", "invalid", "duplicate", "wrong", "won", "lost"]
    game: Game | None = None
    word: str = ""
    guesses: list[GuessRow] = field(default_factory=list)
    reward: Reward | None = None
    streak: int = 0
    daily_streak: int = 0


@dataclass
class DailyStart:
    kind: Literal["new", "resume", "done", "busy"]
    game: Game | None = None
    status: str = ""
    attempts: int = 0
    points: int = 0
    streak: int = 0


@dataclass
class HintResult:
    kind: Literal["ok", "limit", "no_game"]
    game: Game | None = None
    position: int = 0
    letter: str = ""


class GameService:
    def __init__(self, db: Database, words: WordService, scoring: Scoring, settings: Settings) -> None:
        self.db, self.words, self.scoring, self.s = db, words, scoring, settings
        self._locks: dict[int, asyncio.Lock] = {}

    # ------------------------------------------------------------------ helpers
    def lock(self, chat_id: int) -> asyncio.Lock:
        lk = self._locks.get(chat_id)
        if lk is None:
            if len(self._locks) > 5000:  # drop idle locks
                for k in [k for k, v in self._locks.items() if not v.locked()]:
                    self._locks.pop(k, None)
            lk = self._locks[chat_id] = asyncio.Lock()
        return lk

    async def upsert_user(self, player: Player, *, private: bool = False) -> None:
        async with self.db.transaction() as tx:
            await self._ensure_user(tx, player, private)

    @staticmethod
    async def _ensure_user(tx: Executor, p: Player, private: bool = False) -> None:
        now = utcnow()
        await tx.execute(
            """INSERT INTO users(user_id, username, first_name, joined_at, last_seen, dm_ok)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, first_name=excluded.first_name,
                 last_seen=excluded.last_seen,
                 dm_ok=MAX(users.dm_ok, excluded.dm_ok),
                 blocked=CASE WHEN excluded.dm_ok=1 THEN 0 ELSE users.blocked END""",
            (p.user_id, p.username, p.name[:64], now, now, 1 if private else 0),
        )

    async def upsert_group(self, chat_id: int, title: str | None) -> None:
        await self.db.execute(
            """INSERT INTO groups(chat_id, group_title, added_at) VALUES(?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET group_title=excluded.group_title""",
            (chat_id, title, utcnow()),
        )

    async def get_active(self, chat_id: int) -> Game | None:
        row = await self.db.fetchone("SELECT * FROM games WHERE chat_id=? AND status='active'", (chat_id,))
        return Game.from_row(row) if row else None

    async def get_guesses(self, game_id: int) -> list[GuessRow]:
        rows = await self.db.fetchall("SELECT * FROM guesses WHERE game_id=? ORDER BY guess_id", (game_id,))
        return [GuessRow.from_row(r) for r in rows]

    async def set_board_message(self, game_id: int, message_id: int) -> None:
        await self.db.execute("UPDATE games SET board_message_id=? WHERE game_id=?", (message_id, game_id))

    # ------------------------------------------------------- per-chat settings
    async def get_allowed(self, chat_id: int) -> list[int]:
        row = await self.db.fetchone("SELECT allowed_lengths FROM chat_settings WHERE chat_id=?", (chat_id,))
        if not row or not row["allowed_lengths"]:
            return [4, 5, 6, 7]
        return [int(x) for x in row["allowed_lengths"].split(",")]

    async def set_allowed(self, chat_id: int, lengths: list[int] | None) -> None:
        value = ",".join(str(n) for n in lengths) if lengths else None
        await self.db.execute(
            "INSERT INTO chat_settings(chat_id, allowed_lengths) VALUES(?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET allowed_lengths=excluded.allowed_lengths", (chat_id, value))

    # ----------------------------------------------------------------- transfer
    async def transfer_points(self, from_id: int, to_id: int) -> dict:
        """Move ALL leaderboard data (games, points, stats) from one user to another (admin tool)."""
        if from_id == to_id:
            raise ValueError("same user")
        async with self.db.transaction() as tx:
            f = await tx.fetchone("SELECT * FROM users WHERE user_id=?", (from_id,))
            t = await tx.fetchone("SELECT * FROM users WHERE user_id=?", (to_id,))
            if not f or not t:
                raise LookupError("user not found")
            entries = (await tx.fetchone(
                "SELECT COUNT(*) c FROM game_players WHERE user_id=? AND points_earned>0", (from_id,)))["c"]
            both = await tx.fetchall(
                """SELECT a.game_id, a.attempts, a.points_earned FROM game_players a
                   JOIN game_players b ON a.game_id=b.game_id WHERE a.user_id=? AND b.user_id=?""", (from_id, to_id))
            for r in both:
                await tx.execute(
                    "UPDATE game_players SET attempts=attempts+?, points_earned=points_earned+? WHERE game_id=? AND user_id=?",
                    (r["attempts"], r["points_earned"], r["game_id"], to_id))
                await tx.execute("DELETE FROM game_players WHERE game_id=? AND user_id=?", (r["game_id"], from_id))
            await tx.execute("UPDATE game_players SET user_id=? WHERE user_id=?", (to_id, from_id))
            await tx.execute("UPDATE guesses SET user_id=? WHERE user_id=?", (to_id, from_id))
            await tx.execute("UPDATE games SET winner_id=? WHERE winner_id=?", (to_id, from_id))
            await tx.execute("UPDATE games SET started_by=? WHERE started_by=?", (to_id, from_id))
            await tx.execute("UPDATE transactions SET user_id=? WHERE user_id=?", (to_id, from_id))
            await tx.execute(
                """DELETE FROM daily_results WHERE user_id=? AND challenge_date IN
                   (SELECT challenge_date FROM daily_results WHERE user_id=?)""", (from_id, to_id))
            await tx.execute("UPDATE daily_results SET user_id=? WHERE user_id=?", (to_id, from_id))
            await tx.execute(
                """UPDATE users SET total_points=total_points+?, games_played=games_played+?, games_won=games_won+?,
                   games_lost=games_lost+?, best_streak=MAX(best_streak,?), best_daily_streak=MAX(best_daily_streak,?)
                   WHERE user_id=?""",
                (f["total_points"], f["games_played"], f["games_won"], f["games_lost"],
                 f["best_streak"], f["best_daily_streak"], to_id))
            await tx.execute(
                """UPDATE users SET total_points=0, games_played=0, games_won=0, games_lost=0, current_streak=0,
                   best_streak=0, daily_streak=0, best_daily_streak=0, last_daily_win=NULL WHERE user_id=?""", (from_id,))
            return {"from": f["first_name"], "to": t["first_name"], "entries": entries,
                    "points": f["total_points"]}

    # -------------------------------------------------------------------- start
    async def start(self, chat_id: int, length: int, player: Player) -> StartResult:
        async with self.lock(chat_id):
            async with self.db.transaction() as tx:
                await self._ensure_user(tx, player)
                row = await tx.fetchone("SELECT * FROM games WHERE chat_id=? AND status='active'", (chat_id,))
                if row:
                    return StartResult(Game.from_row(row), False)
                now = utcnow()
                res = await tx.execute(
                    """INSERT INTO games(chat_id, game_mode, word_length, secret_word, max_guesses,
                                         started_by, created_at, last_activity)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (chat_id, str(length), length, self.words.random_answer(length),
                     self.s.max_guesses, player.user_id, now, now),
                )
                row = await tx.fetchone("SELECT * FROM games WHERE game_id=?", (res.lastrowid,))
                return StartResult(Game.from_row(row), True)

    async def start_daily(self, chat_id: int, player: Player) -> DailyStart:
        today = today_utc()
        async with self.lock(chat_id):
            async with self.db.transaction() as tx:
                await self._ensure_user(tx, player)
                ch = await tx.fetchone("SELECT secret_word FROM daily_challenges WHERE challenge_date=?", (today,))
                if ch is None:
                    await tx.execute(
                        "INSERT OR IGNORE INTO daily_challenges(challenge_date, secret_word) VALUES(?,?)",
                        (today, self.words.random_answer(self.s.daily_length)),
                    )
                    ch = await tx.fetchone("SELECT secret_word FROM daily_challenges WHERE challenge_date=?", (today,))
                streak = await self._current_daily_streak(tx, player.user_id, today)
                done = await tx.fetchone(
                    "SELECT * FROM daily_results WHERE user_id=? AND challenge_date=?", (player.user_id, today))
                if done:
                    if done["status"] == "playing":
                        g = await tx.fetchone(
                            "SELECT * FROM games WHERE game_mode='daily' AND daily_date=? AND started_by=? AND status='active'",
                            (today, player.user_id))
                        if g and g["chat_id"] == chat_id:
                            return DailyStart("resume", Game.from_row(g), "playing", done["attempts"], 0, streak)
                    return DailyStart("done", None, done["status"], done["attempts"], done["points_earned"], streak)
                if await tx.fetchone("SELECT 1 FROM games WHERE chat_id=? AND status='active'", (chat_id,)):
                    return DailyStart("busy", None, "", 0, 0, streak)
                now = utcnow()
                res = await tx.execute(
                    """INSERT INTO games(chat_id, game_mode, word_length, secret_word, max_guesses,
                                         started_by, daily_date, created_at, last_activity)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (chat_id, "daily", self.s.daily_length, ch["secret_word"], self.s.daily_max_guesses,
                     player.user_id, today, now, now),
                )
                await tx.execute(
                    "INSERT INTO daily_results(user_id, challenge_date, status, game_id) VALUES(?,?, 'playing', ?)",
                    (player.user_id, today, res.lastrowid))
                row = await tx.fetchone("SELECT * FROM games WHERE game_id=?", (res.lastrowid,))
                return DailyStart("new", Game.from_row(row), "playing", 0, 0, streak)

    @staticmethod
    async def _current_daily_streak(tx: Executor, user_id: int, today: str) -> int:
        row = await tx.fetchone("SELECT daily_streak, last_daily_win FROM users WHERE user_id=?", (user_id,))
        if not row or not row["last_daily_win"]:
            return 0
        yesterday = (parse_date(today) - timedelta(days=1)).isoformat()
        return row["daily_streak"] if row["last_daily_win"] in (today, yesterday) else 0

    # ------------------------------------------------------------------ guessing
    async def process_guess(self, chat_id: int, player: Player, word: str) -> GuessOutcome:
        async with self.lock(chat_id):
            game = await self.get_active(chat_id)
            if game is None:
                return GuessOutcome("no_game")
            if len(word) != game.word_length:
                return GuessOutcome("ignore", game)
            if not self.words.is_valid(word):
                return GuessOutcome("invalid", game, word)
            try:
                async with self.db.transaction() as tx:
                    st = await tx.fetchone("SELECT status FROM games WHERE game_id=?", (game.game_id,))
                    if not st or st["status"] != "active":
                        return GuessOutcome("no_game")
                    await self._ensure_user(tx, player)
                    if await tx.fetchone("SELECT 1 FROM guesses WHERE game_id=? AND guessed_word=?",
                                         (game.game_id, word)):
                        return GuessOutcome("duplicate", game, word)
                    cnt = await tx.fetchone("SELECT COUNT(*) AS c FROM guesses WHERE game_id=?", (game.game_id,))
                    attempts = cnt["c"] + 1
                    now = utcnow()
                    await tx.execute(
                        "INSERT INTO guesses(game_id, user_id, guessed_word, result, created_at) VALUES(?,?,?,?,?)",
                        (game.game_id, player.user_id, word, evaluate(game.secret_word, word), now))
                    await tx.execute(
                        """INSERT INTO game_players(game_id, user_id, attempts) VALUES(?,?,1)
                           ON CONFLICT(game_id, user_id) DO UPDATE SET attempts = attempts + 1""",
                        (game.game_id, player.user_id))
                    await tx.execute("UPDATE games SET last_activity=? WHERE game_id=?", (now, game.game_id))
                    if game.is_daily:
                        await tx.execute(
                            "UPDATE daily_results SET attempts=? WHERE user_id=? AND challenge_date=?",
                            (attempts, game.started_by, game.daily_date))
                    kind, reward, streak, dstreak = "wrong", None, 0, 0
                    if word == game.secret_word:
                        kind = "won"
                        reward, streak, dstreak = await self._finish(tx, game, "won", player.user_id, attempts)
                    elif attempts >= game.max_guesses:
                        kind = "lost"
                        await self._finish(tx, game, "lost", None, attempts)
                    rows = await tx.fetchall("SELECT * FROM guesses WHERE game_id=? ORDER BY guess_id", (game.game_id,))
                    guesses = [GuessRow.from_row(r) for r in rows]
                    game.status = kind if kind in ("won", "lost") else "active"
                    return GuessOutcome(kind, game, word, guesses, reward, streak, dstreak)
            except AlreadyFinished:
                return GuessOutcome("no_game")

    async def _finish(self, tx: Executor, game: Game, outcome: str, winner_id: int | None, attempts: int):
        now = utcnow()
        res = await tx.execute(
            "UPDATE games SET status=?, winner_id=?, completed_at=? WHERE game_id=? AND status='active'",
            (outcome, winner_id, now, game.game_id))
        if res.rowcount != 1:
            raise AlreadyFinished()
        players = await tx.fetchall("SELECT user_id FROM game_players WHERE game_id=?", (game.game_id,))
        reward, streak, dstreak = None, 0, 0
        for p in players:
            uid = p["user_id"]
            if outcome == "won" and uid == winner_id:
                await tx.execute(
                    """UPDATE users SET games_played=games_played+1, games_won=games_won+1,
                       current_streak=current_streak+1, best_streak=MAX(best_streak, current_streak+1)
                       WHERE user_id=?""", (uid,))
            else:
                await tx.execute(
                    "UPDATE users SET games_played=games_played+1, games_lost=games_lost+1, current_streak=0 WHERE user_id=?",
                    (uid,))
        if outcome == "won":
            row = await tx.fetchone("SELECT current_streak FROM users WHERE user_id=?", (winner_id,))
            streak = row["current_streak"]
            if game.is_daily:
                dstreak = await self._current_daily_streak(tx, winner_id, game.daily_date)
                if await tx.fetchone("SELECT 1 FROM users WHERE user_id=? AND last_daily_win=?", (winner_id, game.daily_date)):
                    pass  # already counted today (cannot normally happen)
                else:
                    dstreak += 1
                    await tx.execute(
                        """UPDATE users SET daily_streak=?, last_daily_win=?,
                           best_daily_streak=MAX(best_daily_streak, ?) WHERE user_id=?""",
                        (dstreak, game.daily_date, dstreak, winner_id))
            reward = self.scoring.for_win(
                streak_after=streak, participants=len(players), daily=game.is_daily, daily_streak=dstreak,
                attempts=attempts, max_guesses=game.max_guesses)
            await tx.execute("UPDATE game_players SET result='won', points_earned=? WHERE game_id=? AND user_id=?",
                             (reward.total, game.game_id, winner_id))
            await tx.execute("UPDATE game_players SET result='lost' WHERE game_id=? AND user_id<>?",
                             (game.game_id, winner_id))
            await tx.execute("UPDATE users SET total_points=total_points+? WHERE user_id=?", (reward.total, winner_id))
            await tx.execute(
                "INSERT INTO transactions(user_id, points, reason, game_id, created_at) VALUES(?,?,?,?,?)",
                (winner_id, reward.total, "daily_win" if game.is_daily else "win", game.game_id, now))
        else:
            await tx.execute("UPDATE game_players SET result='lost' WHERE game_id=?", (game.game_id,))
        if game.is_daily:
            await tx.execute(
                "UPDATE daily_results SET status=?, attempts=?, points_earned=? WHERE user_id=? AND challenge_date=?",
                (outcome, attempts, reward.total if reward else 0, game.started_by, game.daily_date))
        return reward, streak, dstreak

    # --------------------------------------------------------------- end / hint
    async def end_game(self, chat_id: int, status: str) -> Game | None:
        """status: 'cancelled' or 'skipped'. Returns the ended game (with secret) or None."""
        assert status in ("cancelled", "skipped")
        async with self.lock(chat_id):
            async with self.db.transaction() as tx:
                row = await tx.fetchone("SELECT * FROM games WHERE chat_id=? AND status='active'", (chat_id,))
                if not row:
                    return None
                game = Game.from_row(row)
                await tx.execute("UPDATE games SET status=?, completed_at=? WHERE game_id=?",
                                 (status, utcnow(), game.game_id))
                await tx.execute("UPDATE game_players SET result=? WHERE game_id=?", (status, game.game_id))
                if game.is_daily:
                    await tx.execute(
                        "UPDATE daily_results SET status='forfeit' WHERE user_id=? AND challenge_date=? AND status='playing'",
                        (game.started_by, game.daily_date))
                game.status = status
                return game

    async def hint(self, chat_id: int) -> HintResult:
        async with self.lock(chat_id):
            async with self.db.transaction() as tx:
                row = await tx.fetchone("SELECT * FROM games WHERE chat_id=? AND status='active'", (chat_id,))
                if not row:
                    return HintResult("no_game")
                game = Game.from_row(row)
                if game.hints_used >= self.s.hints_per_game:
                    return HintResult("limit", game)
                rows = await tx.fetchall("SELECT result FROM guesses WHERE game_id=?", (game.game_id,))
                known = {i for r in rows for i, c in enumerate(r["result"]) if c == "G"}
                options = [i for i in range(game.word_length) if i not in known]
                if not options:
                    return HintResult("limit", game)
                pos = random.choice(options)
                await tx.execute("UPDATE games SET hints_used=hints_used+1 WHERE game_id=?", (game.game_id,))
                game.hints_used += 1
                return HintResult("ok", game, pos, game.secret_word[pos])

    async def expire_stale(self, hours: int) -> int:
        cutoff = (parse_dt(utcnow()) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        async with self.db.transaction() as tx:
            rows = await tx.fetchall("SELECT * FROM games WHERE status='active' AND last_activity < ?", (cutoff,))
            for r in rows:
                await tx.execute("UPDATE games SET status='expired', completed_at=? WHERE game_id=?",
                                 (utcnow(), r["game_id"]))
                if r["game_mode"] == "daily":
                    await tx.execute(
                        "UPDATE daily_results SET status='forfeit' WHERE user_id=? AND challenge_date=? AND status='playing'",
                        (r["started_by"], r["daily_date"]))
            return len(rows)


def parse_dt(s: str):
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
