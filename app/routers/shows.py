from datetime import date
from typing import Annotated, Any

from asyncpg.pool import PoolConnectionProxy
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import audio, catalog
from app.db import get_conn

router = APIRouter(prefix="/api/shows", tags=["shows"])


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


class ShowDetail(BaseModel):
    id: int
    station: str
    name: str
    episode_count: int


class MonthBucket(BaseModel):
    year: int
    month: int
    episode_count: int


class MonthsResponse(BaseModel):
    show: ShowDetail
    months: list[MonthBucket]


class Chapter(BaseModel):
    title: str
    start: int
    end: int


class Episode(BaseModel):
    id: int
    aired_on: date
    time_slot: str | None
    s3_key: str
    chapters: list[Chapter] | None


class EpisodesResponse(BaseModel):
    show: ShowDetail
    episodes: list[Episode]


class EpisodeDetail(BaseModel):
    id: int
    aired_on: date
    time_slot: str | None
    s3_key: str
    chapters: list[Chapter] | None
    show: ShowDetail


class AudioUrlResponse(BaseModel):
    url: str
    expires_in: int


def _db_error(e: catalog.CatalogDatabaseError) -> HTTPException:
    return HTTPException(status_code=500, detail=e.detail)


def _show_detail(show: catalog.ShowDetail) -> ShowDetail:
    return ShowDetail(
        id=show.id,
        station=show.station,
        name=show.name,
        episode_count=show.episode_count,
    )


def _chapters(chapters: list[dict[str, Any]] | None) -> list[Chapter] | None:
    if chapters is None:
        return None
    return [
        Chapter(title=chapter["title"], start=chapter["start"], end=chapter["end"])
        for chapter in chapters
    ]


def _episode(episode: catalog.Episode) -> Episode:
    return Episode(
        id=episode.id,
        aired_on=episode.aired_on,
        time_slot=episode.time_slot,
        s3_key=episode.s3_key,
        chapters=_chapters(episode.chapters),
    )


def _episode_detail(episode: catalog.EpisodeDetail) -> EpisodeDetail:
    return EpisodeDetail(
        id=episode.id,
        aired_on=episode.aired_on,
        time_slot=episode.time_slot,
        s3_key=episode.s3_key,
        chapters=_chapters(episode.chapters),
        show=_show_detail(episode.show),
    )


async def _get_episode_s3_key(conn: PoolConnectionProxy, episode_id: int) -> str:
    try:
        return await catalog.get_episode_s3_key(conn, episode_id)
    except catalog.CatalogNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e


@router.get("/stations")
async def list_stations(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> StationsResponse:
    try:
        stations = await catalog.list_stations(conn)
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e
    return StationsResponse(stations=[Station(id=s.id, show_count=s.show_count) for s in stations])


@router.get("/stations/{station}/shows")
async def list_shows(
    station: Annotated[str, Path(min_length=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ShowsResponse:
    try:
        shows = await catalog.list_shows(conn, station)
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e
    return ShowsResponse(
        shows=[Show(id=s.id, name=s.name, episode_count=s.episode_count) for s in shows]
    )


@router.get("/{show_id}")
async def get_show(
    show_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ShowDetail:
    try:
        return _show_detail(await catalog.get_show_detail(conn, show_id))
    except catalog.CatalogNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e


@router.get("/{show_id}/months")
async def list_months(
    show_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> MonthsResponse:
    try:
        show, months = await catalog.list_months(conn, show_id)
    except catalog.CatalogNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e
    return MonthsResponse(
        show=_show_detail(show),
        months=[
            MonthBucket(year=m.year, month=m.month, episode_count=m.episode_count) for m in months
        ],
    )


@router.get("/{show_id}/months/{year}/{month}/episodes")
async def list_episodes(
    show_id: Annotated[int, Path(ge=1)],
    year: Annotated[int, Path(ge=1900, le=2999)],
    month: Annotated[int, Path(ge=1, le=12)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> EpisodesResponse:
    try:
        show, episodes = await catalog.list_episodes(conn, show_id, year, month)
    except catalog.CatalogNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e
    return EpisodesResponse(
        show=_show_detail(show),
        episodes=[_episode(e) for e in episodes],
    )


@router.get("/episodes/{episode_id}")
async def get_episode(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> EpisodeDetail:
    try:
        return _episode_detail(await catalog.get_episode_detail(conn, episode_id))
    except catalog.CatalogNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e


@router.get("/episodes/{episode_id}/audio_url")
async def get_episode_audio_url(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> AudioUrlResponse:
    s3_key = await _get_episode_s3_key(conn, episode_id)
    try:
        url = await audio.presign_audio_url(s3_key)
    except audio.AudioUpstreamError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e
    return AudioUrlResponse(url=url.url, expires_in=url.expires_in)


@router.get("/episodes/{episode_id}/audio")
async def stream_episode_audio(
    episode_id: Annotated[int, Path(ge=1)],
    request: Request,
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> StreamingResponse:
    s3_key = await _get_episode_s3_key(conn, episode_id)
    try:
        stream = await audio.open_audio_stream(s3_key, request.headers.get("range"))
    except audio.AudioRangeNotSatisfiable as e:
        raise HTTPException(status_code=416, detail=e.detail) from e
    except audio.AudioNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except audio.AudioUpstreamError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e

    return StreamingResponse(
        stream.body,
        status_code=stream.status_code,
        headers=stream.headers,
        media_type=stream.media_type,
    )
