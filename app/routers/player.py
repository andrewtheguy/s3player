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
    completed: bool = False


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
    )


@router.post("/session/claim", summary="Claim the active player session")
async def claim_session(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ClaimResponse:
    """Claim the single active player session and displace any previous one.

    There is exactly one active player session globally; calling this issues a
    new `session_token` and invalidates the previously-issued token. Send the
    returned token as `X-Player-Session` on every player write (progress,
    complete) and on `validate`.
    """
    return ClaimResponse(session_token=await player_state.claim_session(conn))


@router.post("/session/validate", summary="Check that the player session is still active")
async def validate_session(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    x_player_session: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Confirm that the `X-Player-Session` token still owns the active session.

    Returns 401 if the header is missing and 409 if the token has been
    displaced by a later claim.
    """
    session_token = _require_session_token(x_player_session)
    try:
        await player_state.validate_session(conn, session_token)
    except player_state.SessionDisplaced as e:
        raise HTTPException(status_code=409, detail=e.detail) from e
    return {"status": "ok"}


@router.post("/episodes/{episode_id}/progress", summary="Save playback progress for an episode")
async def save_progress(
    episode_id: Annotated[int, Path(ge=1)],
    body: ProgressRequest,
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    x_player_session: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Persist playback progress for an episode and, when `completed=true`, mark it fully played.

    Requires `X-Player-Session`. Returns 401 if the header is missing, 409 if
    the token has been displaced, and 404 if the episode does not exist.
    """
    session_token = _require_session_token(x_player_session)
    try:
        await player_state.save_progress(
            conn,
            session_token,
            episode_id,
            body.position_ms,
            body.duration_ms,
            body.completed,
        )
    except player_state.SessionDisplaced as e:
        raise HTTPException(status_code=409, detail=e.detail) from e
    except player_state.EpisodeNotFound as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    return {"status": "ok"}


@router.get(
    "/episodes/{episode_id}/progress",
    summary="Read saved playback progress for an episode",
)
async def get_progress(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ProgressResponse:
    """Return saved position, duration, completion flag, and last-played time for an episode.

    If no progress has been recorded yet, position and completion default to
    zero/false. Does not require a player session token.
    """
    return _progress_response(await player_state.get_progress(conn, episode_id))


@router.delete(
    "/episodes/{episode_id}/progress",
    summary="Remove saved playback progress for an episode",
)
async def delete_progress(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> dict[str, str]:
    """Drop the play-state row for an episode so it disappears from the
    in-progress and recently-completed lists.

    Idempotent: returns 200 whether or not a row existed. Does not require a
    player session token.
    """
    await player_state.delete_progress(conn, episode_id)
    return {"status": "ok"}


@router.get("/recent-completed", summary="List recently completed episodes")
async def list_recent(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecentResponse:
    """List completed episodes ordered by most recent playback.

    Mutually exclusive with `/in-progress`: an episode appears in one or the
    other, never both.
    """
    episodes = await player_state.list_recent(conn, limit)
    return RecentResponse(episodes=[_recent_episode(e) for e in episodes])


@router.get("/in-progress", summary="List episodes with resumable progress")
async def list_in_progress(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecentResponse:
    """List incomplete episodes that have enough saved duration and remaining time to resume.

    Mutually exclusive with `/recent-completed`.
    """
    episodes = await player_state.list_in_progress(conn, limit)
    return RecentResponse(episodes=[_recent_episode(e) for e in episodes])
