from datetime import date, datetime
from typing import Annotated

from asyncpg.pool import PoolConnectionProxy
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app import player_state
from app.db import get_conn

router = APIRouter(prefix="/api/player", tags=["player"])


class ClaimResponse(BaseModel):
    session_token: str


class ProgressRequest(BaseModel):
    position_ms: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0)


class ProgressResponse(BaseModel):
    position_ms: int
    duration_ms: int | None
    completed: bool
    last_played_at: datetime | None = None


class RecentEpisode(BaseModel):
    id: int
    aired_on: date
    time_slot: str | None
    show_id: int
    show_name: str
    station: str
    position_ms: int
    duration_ms: int | None
    last_played_at: datetime
    completed: bool


class RecentResponse(BaseModel):
    episodes: list[RecentEpisode]


def _require_session_token(session_token: str | None) -> str:
    if not session_token:
        raise HTTPException(status_code=401, detail="missing session token")
    return session_token


def _progress_response(progress: player_state.Progress) -> ProgressResponse:
    return ProgressResponse(
        position_ms=progress.position_ms,
        duration_ms=progress.duration_ms,
        completed=progress.completed,
        last_played_at=progress.last_played_at,
    )


def _recent_episode(episode: player_state.RecentEpisode) -> RecentEpisode:
    return RecentEpisode(
        id=episode.id,
        aired_on=episode.aired_on,
        time_slot=episode.time_slot,
        show_id=episode.show_id,
        show_name=episode.show_name,
        station=episode.station,
        position_ms=episode.position_ms,
        duration_ms=episode.duration_ms,
        last_played_at=episode.last_played_at,
        completed=episode.completed,
    )


@router.post("/session/claim")
async def claim_session(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ClaimResponse:
    return ClaimResponse(session_token=await player_state.claim_session(conn))


@router.post("/session/validate")
async def validate_session(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    x_player_session: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    session_token = _require_session_token(x_player_session)
    try:
        await player_state.validate_session(conn, session_token)
    except player_state.SessionDisplaced as e:
        raise HTTPException(status_code=409, detail=e.detail) from e
    return {"status": "ok"}


@router.post("/episodes/{episode_id}/progress")
async def save_progress(
    episode_id: Annotated[int, Path(ge=1)],
    body: ProgressRequest,
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    x_player_session: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    session_token = _require_session_token(x_player_session)
    try:
        await player_state.save_progress(
            conn,
            session_token,
            episode_id,
            body.position_ms,
            body.duration_ms,
        )
    except player_state.SessionDisplaced as e:
        raise HTTPException(status_code=409, detail=e.detail) from e
    except player_state.EpisodeNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    return {"status": "ok"}


@router.post("/episodes/{episode_id}/complete")
async def mark_complete(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    x_player_session: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    session_token = _require_session_token(x_player_session)
    try:
        await player_state.mark_complete(conn, session_token, episode_id)
    except player_state.SessionDisplaced as e:
        raise HTTPException(status_code=409, detail=e.detail) from e
    except player_state.EpisodeNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    return {"status": "ok"}


@router.get("/episodes/{episode_id}/progress")
async def get_progress(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ProgressResponse:
    return _progress_response(await player_state.get_progress(conn, episode_id))


@router.get("/recent")
async def list_recent(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecentResponse:
    episodes = await player_state.list_recent(conn, limit)
    return RecentResponse(episodes=[_recent_episode(e) for e in episodes])


@router.get("/in-progress")
async def list_in_progress(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecentResponse:
    episodes = await player_state.list_in_progress(conn, limit)
    return RecentResponse(episodes=[_recent_episode(e) for e in episodes])
