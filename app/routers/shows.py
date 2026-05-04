from datetime import date
from typing import Annotated, Any

from asyncpg.pool import PoolConnectionProxy
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import audio, catalog, summaries
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


class ChapterSummary(BaseModel):
    index: int
    content: str


class ChapterSummariesResponse(BaseModel):
    summaries: list[ChapterSummary]


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


@router.get("/stations", summary="List stations")
async def list_stations(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> StationsResponse:
    """List every known station and its total show count."""
    try:
        stations = await catalog.list_stations(conn)
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e
    return StationsResponse(stations=[Station(id=s.id, show_count=s.show_count) for s in stations])


@router.get("/stations/{station}/shows", summary="List shows for a station")
async def list_shows(
    station: Annotated[str, Path(min_length=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ShowsResponse:
    """List shows that belong to the given station, with their episode counts."""
    try:
        shows = await catalog.list_shows(conn, station)
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e
    return ShowsResponse(
        shows=[Show(id=s.id, name=s.name, episode_count=s.episode_count) for s in shows]
    )


@router.get("/{show_id}", summary="Get show detail")
async def get_show(
    show_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ShowDetail:
    """Return station, name, and total episode count for a single show.

    Returns 404 if the show does not exist.
    """
    try:
        return _show_detail(await catalog.get_show_detail(conn, show_id))
    except catalog.CatalogNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e


@router.get("/{show_id}/months", summary="List month buckets for a show")
async def list_months(
    show_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> MonthsResponse:
    """List every (year, month) bucket that has episodes for the show.

    Each bucket includes its episode count. Returns 404 if the show does not exist.
    """
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


@router.get("/{show_id}/months/{year}/{month}/episodes", summary="List episodes in a month")
async def list_episodes(
    show_id: Annotated[int, Path(ge=1)],
    year: Annotated[int, Path(ge=1900, le=2999)],
    month: Annotated[int, Path(ge=1, le=12)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> EpisodesResponse:
    """List the show's episodes that aired in the given year and month.

    Each episode includes its chapters when available. Returns 404 if the show
    does not exist.
    """
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


@router.get("/episodes/{episode_id}", summary="Get episode detail")
async def get_episode(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> EpisodeDetail:
    """Return air date, time slot, S3 key, chapters, and parent show for a single episode.

    Returns 404 if the episode does not exist.
    """
    try:
        return _episode_detail(await catalog.get_episode_detail(conn, episode_id))
    except catalog.CatalogNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    except catalog.CatalogDatabaseError as e:
        raise _db_error(e) from e


@router.get("/episodes/{episode_id}/audio_url", summary="Get a presigned S3 audio URL")
async def get_episode_audio_url(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> AudioUrlResponse:
    """Return a presigned S3 URL for the episode's audio file plus its expiry in seconds.

    Use this when the client should fetch media bytes directly from S3 instead of
    proxying through the backend. Returns 404 if the episode does not exist and 502
    if the upstream presign fails.
    """
    s3_key = await _get_episode_s3_key(conn, episode_id)
    try:
        url = await audio.presign_audio_url(s3_key)
    except audio.AudioUpstreamError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e
    return AudioUrlResponse(url=url.url, expires_in=url.expires_in)


@router.get("/episodes/{episode_id}/audio", summary="Stream episode audio through the backend")
async def stream_episode_audio(
    episode_id: Annotated[int, Path(ge=1)],
    request: Request,
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> StreamingResponse:
    """Proxy the episode's audio bytes from S3 as `audio/mp4`.

    Forwards the client's `Range` header to S3 when present and returns 206 with
    `Content-Range` for partial responses; otherwise returns 200. Returns 404 if
    the episode does not exist, 416 if the requested range is not satisfiable,
    and 502 if the upstream fetch fails.
    """
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


@router.get(
    "/episodes/{episode_id}/chapter_summaries",
    summary="List per-chapter markdown summaries for an episode",
)
async def list_episode_chapter_summaries(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ChapterSummariesResponse:
    """Return every per-chapter markdown summary stored for the episode.

    Summaries live in S3 under a prefix derived from the episode's audio key:
    `shows/<...>/<basename>.m4a` is mapped to
    `summaries/<...>/<basename>_summary/chapter_NN.md`. Each entry's `index`
    is the integer parsed from the file name (the `NN` in `chapter_NN.md`),
    so indices are **1-based** under the canonical naming where the first
    chapter is `chapter_01.md`. The list is sorted ascending by index.
    Returns an empty list when no summaries exist for the episode. Returns
    404 if the episode does not exist and 502 if listing the summaries
    upstream fails.
    """
    s3_key = await _get_episode_s3_key(conn, episode_id)
    try:
        items = await summaries.list_chapter_summaries(s3_key)
    except summaries.SummaryUpstreamError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e
    return ChapterSummariesResponse(
        summaries=[ChapterSummary(index=item.index, content=item.content) for item in items]
    )
