from datetime import date
from typing import Annotated

from asyncpg.pool import PoolConnectionProxy
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from app.config import get_settings
from app.routers.db import get_conn
from app.s3_client import get_s3_client

router = APIRouter(prefix="/api/shows", tags=["shows"])

PRESIGN_EXPIRES_IN = 86400


class Station(BaseModel):
    id: str
    show_count: int


class StationsResponse(BaseModel):
    stations: list[Station]


class Show(BaseModel):
    id: int
    name: str
    episode_count: int


class ShowsResponse(BaseModel):
    shows: list[Show]


class MonthBucket(BaseModel):
    year: int
    month: int
    episode_count: int


class MonthsResponse(BaseModel):
    months: list[MonthBucket]


class Episode(BaseModel):
    id: int
    aired_on: date
    time_slot: str | None
    s3_key: str


class EpisodesResponse(BaseModel):
    episodes: list[Episode]


class PresignedUrlResponse(BaseModel):
    url: str
    expires_in: int


def _db_error(e: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=f"db error: {e}")


@router.get("/stations")
async def list_stations(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> StationsResponse:
    try:
        rows = await conn.fetch(
            "SELECT station, COUNT(*)::int AS show_count "
            "FROM shows GROUP BY station ORDER BY station"
        )
    except Exception as e:
        raise _db_error(e) from e
    return StationsResponse(
        stations=[Station(id=r["station"], show_count=r["show_count"]) for r in rows]
    )


@router.get("/stations/{station}/shows")
async def list_shows(
    station: Annotated[str, Path(min_length=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ShowsResponse:
    try:
        rows = await conn.fetch(
            "SELECT s.id, s.name, COUNT(e.id)::int AS episode_count "
            "FROM shows s LEFT JOIN episodes e ON e.show_id = s.id "
            "WHERE s.station = $1 "
            "GROUP BY s.id, s.name ORDER BY s.name",
            station,
        )
    except Exception as e:
        raise _db_error(e) from e
    return ShowsResponse(
        shows=[Show(id=r["id"], name=r["name"], episode_count=r["episode_count"]) for r in rows]
    )


@router.get("/stations/{station}/shows/{show}/months")
async def list_months(
    station: Annotated[str, Path(min_length=1)],
    show: Annotated[str, Path(min_length=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> MonthsResponse:
    try:
        show_id = await conn.fetchval(
            "SELECT id FROM shows WHERE station = $1 AND name = $2", station, show
        )
        if show_id is None:
            raise HTTPException(status_code=404, detail="show not found")
        rows = await conn.fetch(
            "SELECT EXTRACT(YEAR FROM aired_on)::int AS year, "
            "EXTRACT(MONTH FROM aired_on)::int AS month, "
            "COUNT(*)::int AS episode_count "
            "FROM episodes WHERE show_id = $1 "
            "GROUP BY year, month ORDER BY year DESC, month DESC",
            show_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise _db_error(e) from e
    return MonthsResponse(
        months=[
            MonthBucket(year=r["year"], month=r["month"], episode_count=r["episode_count"])
            for r in rows
        ]
    )


@router.get("/stations/{station}/shows/{show}/months/{year}/{month}/episodes")
async def list_episodes(
    station: Annotated[str, Path(min_length=1)],
    show: Annotated[str, Path(min_length=1)],
    year: Annotated[int, Path(ge=1900, le=2999)],
    month: Annotated[int, Path(ge=1, le=12)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> EpisodesResponse:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    try:
        rows = await conn.fetch(
            "SELECT e.id, e.aired_on, e.time_slot, e.s3_key "
            "FROM episodes e JOIN shows s ON s.id = e.show_id "
            "WHERE s.station = $1 AND s.name = $2 "
            "AND e.aired_on >= $3 AND e.aired_on < $4 "
            "ORDER BY e.aired_on, e.time_slot NULLS LAST",
            station,
            show,
            start,
            end,
        )
    except Exception as e:
        raise _db_error(e) from e
    return EpisodesResponse(
        episodes=[
            Episode(
                id=r["id"],
                aired_on=r["aired_on"],
                time_slot=r["time_slot"],
                s3_key=r["s3_key"],
            )
            for r in rows
        ]
    )


@router.get("/episodes/{episode_id}/url")
async def get_episode_url(
    episode_id: int,
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> PresignedUrlResponse:
    try:
        s3_key = await conn.fetchval("SELECT s3_key FROM episodes WHERE id = $1", episode_id)
    except Exception as e:
        raise _db_error(e) from e
    if s3_key is None:
        raise HTTPException(status_code=404, detail="episode not found")

    settings = get_settings()
    client = get_s3_client()
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": s3_key},
            ExpiresIn=PRESIGN_EXPIRES_IN,
        )
    except ClientError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return PresignedUrlResponse(url=url, expires_in=PRESIGN_EXPIRES_IN)
