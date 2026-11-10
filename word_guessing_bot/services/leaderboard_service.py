"""Leaderboards, rankings and player statistics (all real SQL, UTC date filters)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from database.db import Database

PERIODS = {"t": "Today", "w": "This week", "m": "This month", "y": "This year", "a": "All time"}
PER_PAGE = 10


def period_start(code: str, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    d = now.date()
    if code == "t":
        start = d
    elif code == "w":
        start = d - timedelta(days=d.weekday())
    elif code == "m":
        start = d.replace(day=1)
    elif code == "y":
        start = d.replace(month=1, day=1)
    else:
        return None
    return f"{start.isoformat()} 00:00:00"


@dataclass
class LBRow:
    user_id: int
    name: str
    username: str | None
    points: int


@dataclass
class LBPage:
    rows: list[LBRow]
    total: int
    page: int
    pages: int


class LeaderboardService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _where(scope: str, chat_id: int, period: str, length: int):
        sql = "g.status IN ('won','lost') AND gp.points_earned > 0 AND u.is_banned = 0"
        params: list = []
        start = period_start(period)
        if start:
            sql += " AND g.completed_at >= ?"
            params.append(start)
        if scope == "c":
            sql += " AND g.chat_id = ?"
            params.append(chat_id)
        if length in (4, 5, 6, 7):
            sql += " AND g.word_length = ?"
            params.append(length)
        return sql, params

    async def page(self, *, scope: str, chat_id: int, period: str, length: int, page: int = 1) -> LBPage:
        where, params = self._where(scope, chat_id, period, length)
        base = ("FROM game_players gp JOIN games g ON g.game_id = gp.game_id "
                "JOIN users u ON u.user_id = gp.user_id WHERE " + where)
        total_row = await self.db.fetchone(f"SELECT COUNT(DISTINCT gp.user_id) AS c {base}", params)
        total = total_row["c"]
        pages = max(1, -(-total // PER_PAGE))
        page = min(max(1, page), pages)
        rows = await self.db.fetchall(
            f"""SELECT u.user_id, u.first_name, u.username, SUM(gp.points_earned) AS pts {base}
                GROUP BY u.user_id ORDER BY pts DESC, MIN(g.completed_at) ASC, u.user_id ASC
                LIMIT ? OFFSET ?""",
            params + [PER_PAGE, (page - 1) * PER_PAGE])
        return LBPage([LBRow(r["user_id"], r["first_name"], r["username"], r["pts"]) for r in rows],
                      total, page, pages)

    # ---------------------------------------------------------------- user data
    async def user(self, user_id: int):
        return await self.db.fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))

    async def global_rank(self, user_id: int) -> int | None:
        row = await self.db.fetchone(
            """SELECT CASE WHEN games_played = 0 THEN NULL ELSE
                 (SELECT COUNT(*) + 1 FROM users o WHERE o.is_banned=0 AND o.games_played>0
                    AND o.total_points > u.total_points) END AS r
               FROM users u WHERE u.user_id=?""", (user_id,))
        return row["r"] if row else None

    async def chat_rank(self, chat_id: int, user_id: int) -> tuple[int | None, int]:
        where, params = self._where("c", chat_id, "a", 0)
        base = ("FROM game_players gp JOIN games g ON g.game_id=gp.game_id "
                "JOIN users u ON u.user_id=gp.user_id WHERE " + where)
        mine = await self.db.fetchone(f"SELECT SUM(gp.points_earned) AS s {base} AND gp.user_id=?", params + [user_id])
        total = (await self.db.fetchone(f"SELECT COUNT(DISTINCT gp.user_id) AS c {base}", params))["c"]
        if not mine or mine["s"] is None:
            return None, total
        ahead = await self.db.fetchone(
            f"""SELECT COUNT(*) AS c FROM (SELECT gp.user_id {base} GROUP BY gp.user_id
                HAVING SUM(gp.points_earned) > ?)""", params + [mine["s"]])
        return ahead["c"] + 1, total

    async def user_score(self, user_id: int, scope: str, chat_id: int, period: str, length: int):
        """(points, rank or None, wins) of one user for the given filters."""
        where, params = self._where(scope, chat_id, period, length)
        base = ("FROM game_players gp JOIN games g ON g.game_id=gp.game_id "
                "JOIN users u ON u.user_id=gp.user_id WHERE " + where)
        mine = await self.db.fetchone(
            f"SELECT SUM(gp.points_earned) AS s, SUM(gp.result='won') AS w {base} AND gp.user_id=?", params + [user_id])
        if not mine or mine["s"] is None:
            return 0, None, 0
        ahead = await self.db.fetchone(
            f"SELECT COUNT(*) AS c FROM (SELECT gp.user_id {base} GROUP BY gp.user_id "
            "HAVING SUM(gp.points_earned) > ?)", params + [mine["s"]])
        return mine["s"], ahead["c"] + 1, mine["w"] or 0

    async def stats(self, user_id: int) -> dict | None:
        u = await self.user(user_id)
        if not u:
            return None
        best = await self.db.fetchone("SELECT MAX(points_earned) AS m FROM game_players WHERE user_id=?", (user_id,))
        fav = await self.db.fetchone(
            """SELECT g.word_length AS l, COUNT(*) AS c FROM game_players gp JOIN games g ON g.game_id=gp.game_id
               WHERE gp.user_id=? AND g.status IN ('won','lost') GROUP BY g.word_length
               ORDER BY c DESC, g.word_length ASC LIMIT 1""", (user_id,))
        played = u["games_played"]
        return {
            "user": u,
            "win_pct": (u["games_won"] * 100 / played) if played else 0.0,
            "best_game": best["m"] or 0,
            "fav_length": fav["l"] if fav else None,
            "rank": await self.global_rank(user_id),
        }

    async def history(self, user_id: int, limit: int = 10):
        return await self.db.fetchall(
            """SELECT g.game_id, g.game_mode, g.word_length, g.secret_word, g.completed_at,
                      gp.result, gp.attempts, gp.points_earned
               FROM game_players gp JOIN games g ON g.game_id=gp.game_id
               WHERE gp.user_id=? AND g.status IN ('won','lost')
               ORDER BY g.completed_at DESC, g.game_id DESC LIMIT ?""", (user_id, limit))

    async def daily_ranking(self, date: str, limit: int = 10):
        return await self.db.fetchall(
            """SELECT u.user_id, u.first_name, d.attempts, d.points_earned
               FROM daily_results d JOIN users u ON u.user_id=d.user_id
               WHERE d.challenge_date=? AND d.status='won' AND u.is_banned=0
               ORDER BY d.attempts ASC, d.points_earned DESC, d.user_id ASC LIMIT ?""", (date, limit))
