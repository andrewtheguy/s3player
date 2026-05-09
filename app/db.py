import json
from collections.abc import AsyncIterator

import asyncpg
from asyncpg.pool import PoolConnectionProxy

from app.config import get_settings

_pool: asyncpg.Pool | None = None

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS shows (
        id      SERIAL PRIMARY KEY,
        station TEXT NOT NULL,
        name    TEXT NOT NULL,
        UNIQUE (station, name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS shows_station_idx ON shows (station)",
    """
    CREATE TABLE IF NOT EXISTS episodes (
        id        SERIAL PRIMARY KEY,
        s3_key    TEXT NOT NULL UNIQUE,
        show_id   INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
        aired_on  DATE NOT NULL,
        chapters  JSONB,
        time_slot TEXT,
        deleted   BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,
    "CREATE INDEX IF NOT EXISTS episodes_show_id_idx ON episodes (show_id)",
    "CREATE INDEX IF NOT EXISTS episodes_aired_on_idx ON episodes (aired_on)",
    """
    CREATE TABLE IF NOT EXISTS player_session (
        id            SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        session_token TEXT NOT NULL,
        claimed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS episode_play_state (
        episode_id     INTEGER PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
        position_ms    BIGINT NOT NULL DEFAULT 0,
        duration_ms    BIGINT,
        last_played_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        completed      BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,
    "CREATE INDEX IF NOT EXISTS episode_play_state_recent_idx "
    "ON episode_play_state (last_played_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS favorite_shows (
        show_id      INTEGER PRIMARY KEY REFERENCES shows(id) ON DELETE CASCADE,
        favorited_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS favorite_shows_recent_idx ON favorite_shows (favorited_at DESC)",
)


async def bootstrap_schema(conn: PoolConnectionProxy) -> None:
    async with conn.transaction():
        for stmt in _SCHEMA_STATEMENTS:
            await conn.execute(stmt)


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=5,
            init=_init_conn,
        )
    return _pool


async def get_conn() -> AsyncIterator[PoolConnectionProxy]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
