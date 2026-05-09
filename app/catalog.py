from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from asyncpg.pool import PoolConnectionProxy


class CatalogDatabaseError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CatalogNotFound(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Station:
    id: str
    show_count: int


@dataclass(frozen=True)
class Show:
    id: int
    name: str
    episode_count: int
    is_favorite: bool


@dataclass(frozen=True)
class ShowDetail:
    id: int
    station: str
    name: str
    episode_count: int


@dataclass(frozen=True)
class FavoriteShow:
    id: int
    station: str
    name: str
    episode_count: int
    favorited_at: datetime
    latest_aired_on: date | None


@dataclass(frozen=True)
class ShowEpisode:
    id: int
    aired_on: date
    time_slot: str | None
    show_id: int
    show_name: str
    station: str
    position_ms: int
    duration_ms: int | None
    completed: bool
    last_played_at: datetime | None


@dataclass(frozen=True)
class MonthBucket:
    year: int
    month: int
    episode_count: int


@dataclass(frozen=True)
class Episode:
    id: int
    aired_on: date
    time_slot: str | None
    s3_key: str
    chapters: list[dict[str, Any]] | None


@dataclass(frozen=True)
class EpisodeDetail:
    id: int
    aired_on: date
    time_slot: str | None
    s3_key: str
    chapters: list[dict[str, Any]] | None
    show: ShowDetail


def _db_error(e: Exception) -> CatalogDatabaseError:
    return CatalogDatabaseError(f"db error: {e}")


async def list_stations(conn: PoolConnectionProxy) -> list[Station]:
    try:
        rows = await conn.fetch(
            "SELECT station, COUNT(*)::int AS show_count "
            "FROM shows GROUP BY station ORDER BY station"
        )
    except Exception as e:
        raise _db_error(e) from e
    return [Station(id=r["station"], show_count=r["show_count"]) for r in rows]


async def list_shows(conn: PoolConnectionProxy, station: str) -> list[Show]:
    try:
        rows = await conn.fetch(
            "SELECT s.id, s.name, COUNT(e.id)::int AS episode_count, "
            "(f.show_id IS NOT NULL) AS is_favorite "
            "FROM shows s LEFT JOIN episodes e "
            "ON e.show_id = s.id AND e.deleted = FALSE "
            "LEFT JOIN favorite_shows f ON f.show_id = s.id "
            "WHERE s.station = $1 "
            "GROUP BY s.id, s.name, f.show_id ORDER BY s.name",
            station,
        )
    except Exception as e:
        raise _db_error(e) from e
    return [
        Show(
            id=r["id"],
            name=r["name"],
            episode_count=r["episode_count"],
            is_favorite=r["is_favorite"],
        )
        for r in rows
    ]


async def get_show_detail(conn: PoolConnectionProxy, show_id: int) -> ShowDetail:
    try:
        row = await conn.fetchrow(
            "SELECT s.id, s.station, s.name, "
            "COUNT(e.id) FILTER (WHERE e.deleted = FALSE)::int AS episode_count "
            "FROM shows s LEFT JOIN episodes e ON e.show_id = s.id "
            "WHERE s.id = $1 GROUP BY s.id, s.station, s.name",
            show_id,
        )
    except Exception as e:
        raise _db_error(e) from e
    if row is None:
        raise CatalogNotFound("show not found")
    return ShowDetail(
        id=row["id"],
        station=row["station"],
        name=row["name"],
        episode_count=row["episode_count"],
    )


async def list_months(
    conn: PoolConnectionProxy, show_id: int
) -> tuple[ShowDetail, list[MonthBucket]]:
    show = await get_show_detail(conn, show_id)
    try:
        rows = await conn.fetch(
            "SELECT EXTRACT(YEAR FROM aired_on)::int AS year, "
            "EXTRACT(MONTH FROM aired_on)::int AS month, "
            "COUNT(*)::int AS episode_count "
            "FROM episodes WHERE show_id = $1 AND deleted = FALSE "
            "GROUP BY year, month ORDER BY year DESC, month DESC",
            show_id,
        )
    except Exception as e:
        raise _db_error(e) from e
    return (
        show,
        [
            MonthBucket(year=r["year"], month=r["month"], episode_count=r["episode_count"])
            for r in rows
        ],
    )


async def list_episodes(
    conn: PoolConnectionProxy,
    show_id: int,
    year: int,
    month: int,
) -> tuple[ShowDetail, list[Episode]]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    show = await get_show_detail(conn, show_id)
    try:
        rows = await conn.fetch(
            "SELECT id, aired_on, time_slot, s3_key, chapters "
            "FROM episodes "
            "WHERE show_id = $1 AND aired_on >= $2 AND aired_on < $3 "
            "AND deleted = FALSE "
            "ORDER BY aired_on, time_slot NULLS LAST",
            show_id,
            start,
            end,
        )
    except Exception as e:
        raise _db_error(e) from e
    return (
        show,
        [
            Episode(
                id=r["id"],
                aired_on=r["aired_on"],
                time_slot=r["time_slot"],
                s3_key=r["s3_key"],
                chapters=r["chapters"],
            )
            for r in rows
        ],
    )


async def get_episode_detail(conn: PoolConnectionProxy, episode_id: int) -> EpisodeDetail:
    try:
        row = await conn.fetchrow(
            "SELECT id, aired_on, time_slot, s3_key, chapters, show_id "
            "FROM episodes WHERE id = $1 AND deleted = FALSE",
            episode_id,
        )
    except Exception as e:
        raise _db_error(e) from e
    if row is None:
        raise CatalogNotFound("episode not found")
    show = await get_show_detail(conn, row["show_id"])
    return EpisodeDetail(
        id=row["id"],
        aired_on=row["aired_on"],
        time_slot=row["time_slot"],
        s3_key=row["s3_key"],
        chapters=row["chapters"],
        show=show,
    )


async def get_episode_s3_key(conn: PoolConnectionProxy, episode_id: int) -> str:
    try:
        s3_key = await conn.fetchval(
            "SELECT s3_key FROM episodes WHERE id = $1 AND deleted = FALSE", episode_id
        )
    except Exception as e:
        raise _db_error(e) from e
    if s3_key is None:
        raise CatalogNotFound("episode not found")
    return s3_key


async def add_favorite(conn: PoolConnectionProxy, show_id: int) -> None:
    try:
        async with conn.transaction():
            exists = await conn.fetchval("SELECT 1 FROM shows WHERE id = $1", show_id)
            if exists is None:
                raise CatalogNotFound("show not found")
            await conn.execute(
                "INSERT INTO favorite_shows (show_id) VALUES ($1) ON CONFLICT (show_id) DO NOTHING",
                show_id,
            )
    except CatalogNotFound:
        raise
    except Exception as e:
        raise _db_error(e) from e


async def remove_favorite(conn: PoolConnectionProxy, show_id: int) -> None:
    try:
        await conn.execute("DELETE FROM favorite_shows WHERE show_id = $1", show_id)
    except Exception as e:
        raise _db_error(e) from e


async def list_favorites(conn: PoolConnectionProxy) -> list[FavoriteShow]:
    try:
        rows = await conn.fetch(
            "SELECT s.id, s.station, s.name, "
            "COUNT(e.id) FILTER (WHERE e.deleted = FALSE)::int AS episode_count, "
            "MAX(e.aired_on) FILTER (WHERE e.deleted = FALSE) AS latest_aired_on, "
            "f.favorited_at "
            "FROM favorite_shows f "
            "JOIN shows s ON s.id = f.show_id "
            "LEFT JOIN episodes e ON e.show_id = s.id "
            "GROUP BY s.id, s.station, s.name, f.favorited_at "
            "ORDER BY f.favorited_at DESC"
        )
    except Exception as e:
        raise _db_error(e) from e
    return [
        FavoriteShow(
            id=r["id"],
            station=r["station"],
            name=r["name"],
            episode_count=r["episode_count"],
            favorited_at=r["favorited_at"],
            latest_aired_on=r["latest_aired_on"],
        )
        for r in rows
    ]


async def list_recent_show_episodes(
    conn: PoolConnectionProxy,
    show_id: int,
    limit: int,
) -> tuple[ShowDetail, list[ShowEpisode]]:
    show = await get_show_detail(conn, show_id)
    try:
        rows = await conn.fetch(
            "SELECT e.id, e.aired_on, e.time_slot, "
            "s.id AS show_id, s.name AS show_name, s.station, "
            "COALESCE(ps.position_ms, 0) AS position_ms, "
            "ps.duration_ms, "
            "COALESCE(ps.completed, FALSE) AS completed, "
            "ps.last_played_at "
            "FROM episodes e "
            "JOIN shows s ON s.id = e.show_id "
            "LEFT JOIN episode_play_state ps ON ps.episode_id = e.id "
            "WHERE e.show_id = $1 AND e.deleted = FALSE "
            "ORDER BY e.aired_on DESC, e.time_slot DESC NULLS LAST "
            "LIMIT $2",
            show_id,
            limit,
        )
    except Exception as e:
        raise _db_error(e) from e
    return (
        show,
        [
            ShowEpisode(
                id=r["id"],
                aired_on=r["aired_on"],
                time_slot=r["time_slot"],
                show_id=r["show_id"],
                show_name=r["show_name"],
                station=r["station"],
                position_ms=r["position_ms"],
                duration_ms=r["duration_ms"],
                completed=r["completed"],
                last_played_at=r["last_played_at"],
            )
            for r in rows
        ],
    )
