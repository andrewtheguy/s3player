import asyncio
import json
import logging
from typing import Any

from asyncpg.pool import PoolConnectionProxy
from botocore.exceptions import ClientError

from app.chapters import normalize_chapters
from app.config import Settings, get_settings
from app.db import bootstrap_schema, close_pool, get_pool
from app.parse_key import ParsedEpisode, parse_episode_key
from app.s3_client import get_s3_client

logger = logging.getLogger(__name__)

STATION_PREFIXES: dict[str, str] = {
    "shows/rthk-radio1/": "rthk-radio1",
    "shows/rthk-radio2/": "rthk-radio2",
}

METADATA_SUFFIX = ".metadata.json"

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


def _list_keys(client: Any, bucket: str, prefix: str) -> list[str]:
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            keys.append(item["Key"])
    return keys


def _fetch_metadata(client: Any, bucket: str, metadata_key: str) -> dict[str, Any] | None:
    try:
        obj = client.get_object(Bucket=bucket, Key=metadata_key)
        body_stream = obj["Body"]
        try:
            body = body_stream.read()
        finally:
            body_stream.close()
    except ClientError as e:
        logger.warning("metadata fetch failed for %s: %s", metadata_key, e)
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        logger.warning("metadata is not valid JSON for %s: %s", metadata_key, e)
        return None
    if not isinstance(data, dict):
        logger.warning("metadata top-level is not an object for %s", metadata_key)
        return None
    return data


async def _store_chapters(
    conn: PoolConnectionProxy,
    client: Any,
    settings: Settings,
    episode_id: int,
    metadata_key: str,
) -> bool:
    meta = await asyncio.to_thread(_fetch_metadata, client, settings.s3_bucket, metadata_key)
    if meta is None:
        return False
    raw = meta.get("chapters")
    if not isinstance(raw, list):
        logger.warning("metadata chapters missing or not a list for %s", metadata_key)
        return False
    chapters = normalize_chapters(raw)
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
    skipped_non_metadata = 0
    skipped_missing_audio = 0
    skipped_unparseable = 0
    inserted = 0
    already_present = 0
    chapters_filled = 0
    soft_deleted = 0
    restored = 0
    present_keys: set[str] = set()

    try:
        async with pool.acquire() as conn:
            await bootstrap_schema(conn)

            show_cache: dict[tuple[str, str], int] = {}
            for prefix, station in STATION_PREFIXES.items():
                logger.info("scanning %s (station=%s)", prefix, station)
                keys = await asyncio.to_thread(_list_keys, client, settings.s3_bucket, prefix)
                total = len(keys)
                audio_keys_set = {k for k in keys if k.endswith(".m4a")}
                metadata_keys = [k for k in keys if k.endswith(METADATA_SUFFIX)]
                scanned += total
                skipped_non_metadata += total - len(metadata_keys)
                logger.info(
                    "found %d keys under %s (%d metadata sidecars, %d audio files)",
                    total,
                    prefix,
                    len(metadata_keys),
                    len(audio_keys_set),
                )
                meta_total = len(metadata_keys)
                for i, metadata_key in enumerate(metadata_keys, 1):
                    progress = f"[{i}/{meta_total}]"
                    audio_key = metadata_key[: -len(METADATA_SUFFIX)]
                    if audio_key not in audio_keys_set:
                        skipped_missing_audio += 1
                        logger.warning("%s sidecar without audio file: %s", progress, metadata_key)
                        continue
                    parsed = parse_episode_key(audio_key)
                    if parsed is None:
                        skipped_unparseable += 1
                        logger.warning("%s could not parse: %s", progress, audio_key)
                        continue
                    present_keys.add(audio_key)
                    new_id = await _index_one(conn, show_cache, station, audio_key, parsed)
                    if new_id is None:
                        already_present += 1
                        logger.info("%s already indexed: %s", progress, audio_key)
                        continue
                    inserted += 1
                    if await _store_chapters(conn, client, settings, new_id, metadata_key):
                        chapters_filled += 1
                        logger.info("%s inserted with chapters: %s", progress, audio_key)
                    else:
                        logger.info("%s inserted (no chapters): %s", progress, audio_key)

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
        "skipped_unparseable=%d skipped_non_metadata=%d skipped_missing_audio=%d "
        "chapters_filled=%d soft_deleted=%d restored=%d",
        scanned,
        inserted,
        already_present,
        skipped_unparseable,
        skipped_non_metadata,
        skipped_missing_audio,
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
