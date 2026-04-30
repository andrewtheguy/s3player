import asyncio
import json
import logging
import subprocess
from typing import Any

from asyncpg.pool import PoolConnectionProxy
from botocore.exceptions import ClientError

from app.chapters import Chapter, normalize_chapters
from app.config import Settings, get_settings
from app.db import close_pool, get_pool
from app.parse_key import ParsedEpisode, parse_episode_key
from app.s3_client import get_s3_client

logger = logging.getLogger(__name__)

STATION_PREFIXES: dict[str, str] = {
    "shows/rthk/radio1/": "rthk-radio1",
    "shows/rthk/radio2/": "rthk-radio2",
}

FFPROBE_PRESIGN_EXPIRES_IN = 300
FFPROBE_TIMEOUT_SECONDS = 60

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

_EPISODE_SET_CHAPTERS = "UPDATE episodes SET chapters = $1::jsonb WHERE id = $2"

_EPISODE_SOFT_DELETE_MISSING = """
UPDATE episodes SET deleted = TRUE
WHERE deleted = FALSE AND s3_key <> ALL($1::text[])
"""

_EPISODE_RESTORE_PRESENT = """
UPDATE episodes SET deleted = FALSE
WHERE deleted = TRUE AND s3_key = ANY($1::text[])
"""


def _parse_update_count(status: str) -> int:
    parts = status.split()
    if len(parts) >= 2 and parts[0] == "UPDATE":
        try:
            return int(parts[1])
        except ValueError:
            return 0
    return 0


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


def _ffprobe_chapters(url: str) -> list[Chapter] | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_chapters",
                url,
            ],
            capture_output=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=True,
        )
    except FileNotFoundError:
        logger.warning("ffprobe binary not found on PATH; chapters will be NULL")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out reading %s", url)
        return None
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        logger.warning("ffprobe failed for %s: %s", url, stderr.strip() or e)
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.warning("ffprobe returned non-JSON for %s: %s", url, e)
        return None
    raw = data.get("chapters")
    if not isinstance(raw, list):
        return []
    return normalize_chapters(raw)


async def _store_chapters(
    conn: PoolConnectionProxy,
    client: Any,
    settings: Settings,
    episode_id: int,
    s3_key: str,
) -> bool:
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": s3_key},
            ExpiresIn=FFPROBE_PRESIGN_EXPIRES_IN,
        )
    except ClientError as e:
        logger.warning("presign failed for %s: %s", s3_key, e)
        return False
    chapters = await asyncio.to_thread(_ffprobe_chapters, url)
    if chapters is None:
        return False
    await conn.execute(_EPISODE_SET_CHAPTERS, chapters, episode_id)
    return True


async def _index_one(
    conn: PoolConnectionProxy,
    show_cache: dict[tuple[str, str], int],
    station: str,
    s3_key: str,
    parsed: ParsedEpisode,
) -> int | None:
    cache_key = (station, parsed.show)
    show_id = show_cache.get(cache_key)
    if show_id is None:
        show_id = await conn.fetchval(_SHOW_UPSERT, station, parsed.show)
        if show_id is None:
            raise RuntimeError(
                f"shows upsert returned no id for station={station!r} show={parsed.show!r}"
            )
        show_cache[cache_key] = show_id
    return await conn.fetchval(_EPISODE_INSERT, s3_key, show_id, parsed.aired_on, parsed.time_slot)


async def _run() -> None:
    settings = get_settings()
    client = get_s3_client()
    pool = await get_pool()

    scanned = 0
    skipped_non_m4a = 0
    skipped_unparseable = 0
    inserted = 0
    already_present = 0
    chapters_filled = 0
    soft_deleted = 0
    restored = 0
    present_keys: set[str] = set()

    try:
        async with pool.acquire() as conn:
            await _bootstrap_schema(conn)

            show_cache: dict[tuple[str, str], int] = {}
            for prefix, station in STATION_PREFIXES.items():
                logger.info("scanning %s (station=%s)", prefix, station)
                keys = await asyncio.to_thread(_list_keys, client, settings.s3_bucket, prefix)
                total = len(keys)
                logger.info("found %d keys under %s", total, prefix)
                for i, key in enumerate(keys, 1):
                    progress = f"[{i}/{total}]"
                    scanned += 1
                    if not key.endswith(".m4a"):
                        skipped_non_m4a += 1
                        logger.info("%s skip non-m4a: %s", progress, key)
                        continue
                    present_keys.add(key)
                    parsed = parse_episode_key(key)
                    if parsed is None:
                        skipped_unparseable += 1
                        logger.warning("%s could not parse: %s", progress, key)
                        continue
                    new_id = await _index_one(conn, show_cache, station, key, parsed)
                    if new_id is None:
                        already_present += 1
                        logger.info("%s already indexed: %s", progress, key)
                        continue
                    inserted += 1
                    if await _store_chapters(conn, client, settings, new_id, key):
                        chapters_filled += 1
                        logger.info("%s inserted with chapters: %s", progress, key)
                    else:
                        logger.info("%s inserted (no chapters): %s", progress, key)

            present_list = list(present_keys)
            soft_deleted = _parse_update_count(
                await conn.execute(_EPISODE_SOFT_DELETE_MISSING, present_list)
            )
            restored = _parse_update_count(
                await conn.execute(_EPISODE_RESTORE_PRESENT, present_list)
            )
    finally:
        await close_pool()

    logger.info(
        "done: scanned=%d inserted=%d already_present=%d "
        "skipped_unparseable=%d skipped_non_m4a=%d chapters_filled=%d "
        "soft_deleted=%d restored=%d",
        scanned,
        inserted,
        already_present,
        skipped_unparseable,
        skipped_non_m4a,
        chapters_filled,
        soft_deleted,
        restored,
    )


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())
