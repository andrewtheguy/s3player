import asyncio
import logging
from typing import Any

from asyncpg.pool import PoolConnectionProxy

from app.config import get_settings
from app.db import close_pool, get_pool
from app.parse_key import ParsedEpisode, parse_episode_key
from app.s3_client import get_s3_client

logger = logging.getLogger(__name__)

STATION_PREFIXES: dict[str, str] = {
    "shows/rthk/radio1/": "rthk-radio1",
    "shows/rthk/radio2/": "rthk-radio2",
}

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
        time_slot TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS episodes_show_id_idx ON episodes (show_id)",
    "CREATE INDEX IF NOT EXISTS episodes_aired_on_idx ON episodes (aired_on)",
)

_SHOW_UPSERT = """
INSERT INTO shows (station, name) VALUES ($1, $2)
ON CONFLICT (station, name) DO UPDATE SET name = EXCLUDED.name
RETURNING id
"""

_EPISODE_INSERT = """
INSERT INTO episodes (s3_key, show_id, aired_on, time_slot)
VALUES ($1, $2, $3, $4)
ON CONFLICT (s3_key) DO NOTHING
RETURNING id
"""


async def _bootstrap_schema(conn: PoolConnectionProxy) -> None:
    async with conn.transaction():
        for stmt in _SCHEMA_STATEMENTS:
            await conn.execute(stmt)


def _list_keys(client: Any, bucket: str, prefix: str) -> list[str]:
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            keys.append(item["Key"])
    return keys


async def _index_one(
    conn: PoolConnectionProxy,
    show_cache: dict[tuple[str, str], int],
    station: str,
    s3_key: str,
    parsed: ParsedEpisode,
) -> bool:
    cache_key = (station, parsed.show)
    show_id = show_cache.get(cache_key)
    if show_id is None:
        show_id = await conn.fetchval(_SHOW_UPSERT, station, parsed.show)
        if show_id is None:
            raise RuntimeError(
                f"shows upsert returned no id for station={station!r} show={parsed.show!r}"
            )
        show_cache[cache_key] = show_id
    inserted_id = await conn.fetchval(
        _EPISODE_INSERT, s3_key, show_id, parsed.aired_on, parsed.time_slot
    )
    return inserted_id is not None


async def _run() -> None:
    settings = get_settings()
    client = get_s3_client()
    pool = await get_pool()

    scanned = 0
    skipped_non_m4a = 0
    skipped_unparseable = 0
    inserted = 0
    already_present = 0

    try:
        async with pool.acquire() as conn:
            await _bootstrap_schema(conn)

            show_cache: dict[tuple[str, str], int] = {}
            for prefix, station in STATION_PREFIXES.items():
                logger.info("scanning %s (station=%s)", prefix, station)
                keys = await asyncio.to_thread(_list_keys, client, settings.s3_bucket, prefix)
                for key in keys:
                    scanned += 1
                    if not key.endswith(".m4a"):
                        skipped_non_m4a += 1
                        continue
                    parsed = parse_episode_key(key)
                    if parsed is None:
                        skipped_unparseable += 1
                        logger.warning("could not parse key: %s", key)
                        continue
                    if await _index_one(conn, show_cache, station, key, parsed):
                        inserted += 1
                    else:
                        already_present += 1
    finally:
        await close_pool()

    logger.info(
        "done: scanned=%d inserted=%d already_present=%d skipped_unparseable=%d skipped_non_m4a=%d",
        scanned,
        inserted,
        already_present,
        skipped_unparseable,
        skipped_non_m4a,
    )


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())
