"""Schema + automatic migrations (tracked with PRAGMA user_version)."""
from __future__ import annotations

import aiosqlite

MIGRATIONS: list[str] = [
    # ---- v1: initial schema ----
    """
    CREATE TABLE users (
        user_id        INTEGER PRIMARY KEY,
        username       TEXT,
        first_name     TEXT NOT NULL DEFAULT '',     -- full display name
        joined_at      TEXT NOT NULL,
        last_seen      TEXT,
        total_points   INTEGER NOT NULL DEFAULT 0,
        games_played   INTEGER NOT NULL DEFAULT 0,
        games_won      INTEGER NOT NULL DEFAULT 0,
        games_lost     INTEGER NOT NULL DEFAULT 0,
        current_streak INTEGER NOT NULL DEFAULT 0,
        best_streak    INTEGER NOT NULL DEFAULT 0,
        daily_streak   INTEGER NOT NULL DEFAULT 0,
        best_daily_streak INTEGER NOT NULL DEFAULT 0,
        last_daily_win TEXT,
        is_banned      INTEGER NOT NULL DEFAULT 0,
        ban_reason     TEXT,
        dm_ok          INTEGER NOT NULL DEFAULT 0,   -- user has opened a private chat
        blocked        INTEGER NOT NULL DEFAULT 0    -- user blocked the bot
    );

    CREATE TABLE groups (
        chat_id     INTEGER PRIMARY KEY,
        group_title TEXT,
        added_at    TEXT NOT NULL
    );

    CREATE TABLE daily_challenges (
        challenge_date TEXT PRIMARY KEY,
        secret_word    TEXT NOT NULL
    );

    CREATE TABLE games (
        game_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id          INTEGER NOT NULL,
        game_mode        TEXT NOT NULL,              -- '4'..'7' or 'daily'
        word_length      INTEGER NOT NULL,
        secret_word      TEXT NOT NULL,
        status           TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active','won','lost','cancelled','skipped','expired')),
        max_guesses      INTEGER NOT NULL,
        started_by       INTEGER REFERENCES users(user_id),
        winner_id        INTEGER REFERENCES users(user_id),
        daily_date       TEXT REFERENCES daily_challenges(challenge_date),
        hints_used       INTEGER NOT NULL DEFAULT 0,
        board_message_id INTEGER,
        created_at       TEXT NOT NULL,
        last_activity    TEXT NOT NULL,
        completed_at     TEXT
    );
    CREATE UNIQUE INDEX ux_games_one_active ON games(chat_id) WHERE status = 'active';
    CREATE INDEX ix_games_completed ON games(completed_at);
    CREATE INDEX ix_games_chat_status ON games(chat_id, status);
    CREATE INDEX ix_games_activity ON games(status, last_activity);

    CREATE TABLE game_players (
        game_id       INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
        user_id       INTEGER NOT NULL REFERENCES users(user_id),
        attempts      INTEGER NOT NULL DEFAULT 0,
        result        TEXT NOT NULL DEFAULT 'playing',
        points_earned INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (game_id, user_id)
    );
    CREATE INDEX ix_gp_user ON game_players(user_id);

    CREATE TABLE guesses (
        guess_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id      INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
        user_id      INTEGER NOT NULL REFERENCES users(user_id),
        guessed_word TEXT NOT NULL,
        result       TEXT NOT NULL,                  -- e.g. 'GYBBG'
        created_at   TEXT NOT NULL,
        UNIQUE (game_id, guessed_word)
    );
    CREATE INDEX ix_guesses_game ON guesses(game_id, guess_id);

    CREATE TABLE daily_results (
        user_id        INTEGER NOT NULL REFERENCES users(user_id),
        challenge_date TEXT NOT NULL REFERENCES daily_challenges(challenge_date),
        attempts       INTEGER NOT NULL DEFAULT 0,
        status         TEXT NOT NULL DEFAULT 'playing',  -- playing/won/lost/forfeit
        points_earned  INTEGER NOT NULL DEFAULT 0,
        game_id        INTEGER REFERENCES games(game_id),
        PRIMARY KEY (user_id, challenge_date)
    );
    CREATE INDEX ix_daily_date ON daily_results(challenge_date, status);

    CREATE TABLE transactions (
        transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER NOT NULL REFERENCES users(user_id),
        points         INTEGER NOT NULL,
        reason         TEXT NOT NULL,
        game_id        INTEGER REFERENCES games(game_id),
        created_at     TEXT NOT NULL
    );
    CREATE INDEX ix_tx_user ON transactions(user_id);
    CREATE UNIQUE INDEX ux_tx_once ON transactions(user_id, game_id, reason) WHERE game_id IS NOT NULL;

    CREATE TABLE bot_settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # ---- v2: per-chat settings (allowed word lengths) ----
    """
    CREATE TABLE chat_settings (
        chat_id         INTEGER PRIMARY KEY,
        allowed_lengths TEXT          -- e.g. '4,5'; NULL = all lengths
    );
    """,
]


async def run_migrations(conn: aiosqlite.Connection) -> None:
    async with conn.execute("PRAGMA user_version") as cur:
        row = await cur.fetchone()
    current = row[0] if row else 0
    for version in range(current, len(MIGRATIONS)):
        await conn.execute("BEGIN")
        try:
            for stmt in _split(MIGRATIONS[version]):
                await conn.execute(stmt)
            await conn.execute(f"PRAGMA user_version = {version + 1}")
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise


def _split(script: str) -> list[str]:
    # strip "-- comments", then split on ';' (no ';' inside our statements)
    lines = [ln.split("--")[0] for ln in script.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
