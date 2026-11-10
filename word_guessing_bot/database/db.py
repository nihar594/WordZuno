"""aiosqlite wrapper: one connection, WAL mode, serialized transactions."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, NamedTuple, Sequence

import aiosqlite

from database.migrations import run_migrations
from utils.logger import get_logger

log = get_logger(__name__)


class Result(NamedTuple):
    rowcount: int
    lastrowid: int | None


class Executor:
    """Query helpers bound to a connection (no locking; used inside a transaction)."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        cur = await self.conn.execute(sql, params)
        res = Result(cur.rowcount, cur.lastrowid)
        await cur.close()
        return res


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None
        self._ex: Executor | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> autocommit; we issue BEGIN/COMMIT ourselves.
        self._conn = await aiosqlite.connect(self.path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA synchronous = NORMAL")
        await self._conn.execute("PRAGMA busy_timeout = 5000")
        await run_migrations(self._conn)
        self._ex = Executor(self._conn)
        log.info("database ready", extra={"ctx": {"path": self.path}})

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def ex(self) -> Executor:
        if self._ex is None:
            raise RuntimeError("Database not connected")
        return self._ex

    async def fetchone(self, sql: str, params: Sequence[Any] = ()):
        async with self._lock:
            return await self.ex.fetchone(sql, params)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()):
        async with self._lock:
            return await self.ex.fetchall(sql, params)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        async with self._lock:
            return await self.ex.execute(sql, params)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Executor]:
        """Serialized write transaction. Do NOT call db.fetch*/execute inside it."""
        async with self._lock:
            ex = self.ex
            await ex.conn.execute("BEGIN IMMEDIATE")
            try:
                yield ex
            except BaseException:
                await ex.conn.execute("ROLLBACK")
                raise
            else:
                await ex.conn.execute("COMMIT")

    async def backup_to(self, dest: Path) -> None:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        async with self._lock:
            await self.ex.conn.execute("VACUUM INTO ?", (str(dest),))
