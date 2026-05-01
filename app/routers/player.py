import secrets
from datetime import date, datetime
from typing import Annotated

import asyncpg
from asyncpg.pool import PoolConnectionProxy
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.routers.db import get_conn

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


_CLAIM_SQL = """
INSERT INTO player_session (id, session_token)
VALUES (1, $1)
ON CONFLICT (id) DO UPDATE
  SET session_token = EXCLUDED.session_token,
      claimed_at = now(),
      last_seen_at = now()
"""

_TOUCH_SQL = """
UPDATE player_session
SET last_seen_at = now()
WHERE id = 1 AND session_token = $1
RETURNING 1
"""

_GUARD_SQL = """
SELECT 1
FROM player_session
WHERE id = 1 AND session_token = $1
FOR UPDATE
"""

_PROGRESS_UPSERT_SQL = """
INSERT INTO episode_play_state (episode_id, position_ms, duration_ms, last_played_at, completed)
VALUES ($1, $2, $3, now(), $4)
ON CONFLICT (episode_id) DO UPDATE
  SET position_ms = EXCLUDED.position_ms,
      duration_ms = COALESCE(EXCLUDED.duration_ms, episode_play_state.duration_ms),
      last_played_at = EXCLUDED.last_played_at,
      completed = episode_play_state.completed OR EXCLUDED.completed
"""

_LIST_SQL_BASE = """
SELECT eps.episode_id, e.aired_on, e.time_slot,
       s.id AS show_id, s.name AS show_name, s.station,
       eps.position_ms, eps.duration_ms, eps.last_played_at, eps.completed
FROM episode_play_state eps
JOIN episodes e ON e.id = eps.episode_id
JOIN shows s ON s.id = e.show_id
WHERE e.deleted = FALSE
"""


def _row_to_recent(r: asyncpg.Record) -> RecentEpisode:
    return RecentEpisode(
        id=r["episode_id"],
        aired_on=r["aired_on"],
        time_slot=r["time_slot"],
        show_id=r["show_id"],
        show_name=r["show_name"],
        station=r["station"],
        position_ms=r["position_ms"],
        duration_ms=r["duration_ms"],
        last_played_at=r["last_played_at"],
        completed=r["completed"],
    )


async def _episode_exists(conn: PoolConnectionProxy, episode_id: int) -> bool:
    row = await conn.fetchval(
        "SELECT 1 FROM episodes WHERE id = $1 AND deleted = FALSE",
        episode_id,
    )
    return row is not None


async def _touch_session(
    conn: PoolConnectionProxy,
    session_token: str,
) -> None:
    ok = await conn.fetchval(_TOUCH_SQL, session_token)
    if ok is None:
        raise HTTPException(status_code=409, detail="session displaced")


async def _guard_session(conn: PoolConnectionProxy, session_token: str) -> None:
    ok = await conn.fetchval(_GUARD_SQL, session_token)
    if ok is None:
        raise HTTPException(status_code=409, detail="session displaced")


def _require_session_token(session_token: str | None) -> str:
    if not session_token:
        raise HTTPException(status_code=401, detail="missing session token")
    return session_token


@router.post("/session/claim")
async def claim_session(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ClaimResponse:
    token = secrets.token_urlsafe(24)
    await conn.execute(_CLAIM_SQL, token)
    return ClaimResponse(session_token=token)


@router.post("/session/validate")
async def validate_session(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    x_player_session: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    session_token = _require_session_token(x_player_session)
    await _touch_session(conn, session_token)
    return {"status": "ok"}


@router.post("/episodes/{episode_id}/progress")
async def save_progress(
    episode_id: Annotated[int, Path(ge=1)],
    body: ProgressRequest,
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    x_player_session: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    session_token = _require_session_token(x_player_session)
    async with conn.transaction():
        await _guard_session(conn, session_token)
        if not await _episode_exists(conn, episode_id):
            raise HTTPException(status_code=404, detail="episode not found")
        await _touch_session(conn, session_token)
        await conn.execute(
            _PROGRESS_UPSERT_SQL,
            episode_id,
            body.position_ms,
            body.duration_ms,
            False,
        )
    return {"status": "ok"}


@router.post("/episodes/{episode_id}/complete")
async def mark_complete(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    x_player_session: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    session_token = _require_session_token(x_player_session)
    async with conn.transaction():
        await _guard_session(conn, session_token)
        if not await _episode_exists(conn, episode_id):
            raise HTTPException(status_code=404, detail="episode not found")
        await _touch_session(conn, session_token)
        existing_duration = await conn.fetchval(
            "SELECT duration_ms FROM episode_play_state WHERE episode_id = $1",
            episode_id,
        )
        await conn.execute(
            _PROGRESS_UPSERT_SQL,
            episode_id,
            existing_duration if existing_duration is not None else 0,
            existing_duration,
            True,
        )
    return {"status": "ok"}


@router.get("/episodes/{episode_id}/progress")
async def get_progress(
    episode_id: Annotated[int, Path(ge=1)],
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> ProgressResponse:
    row = await conn.fetchrow(
        "SELECT position_ms, duration_ms, completed, last_played_at "
        "FROM episode_play_state WHERE episode_id = $1",
        episode_id,
    )
    if row is None:
        return ProgressResponse(position_ms=0, duration_ms=None, completed=False)
    return ProgressResponse(
        position_ms=row["position_ms"],
        duration_ms=row["duration_ms"],
        completed=row["completed"],
        last_played_at=row["last_played_at"],
    )


@router.get("/recent")
async def list_recent(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecentResponse:
    rows = await conn.fetch(
        _LIST_SQL_BASE + " AND eps.completed = TRUE ORDER BY eps.last_played_at DESC LIMIT $1",
        limit,
    )
    return RecentResponse(episodes=[_row_to_recent(r) for r in rows])


@router.get("/in-progress")
async def list_in_progress(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecentResponse:
    rows = await conn.fetch(
        _LIST_SQL_BASE + " AND eps.completed = FALSE "
        "AND eps.duration_ms IS NOT NULL "
        "AND eps.position_ms < eps.duration_ms - 30000 "
        "ORDER BY eps.last_played_at DESC LIMIT $1",
        limit,
    )
    return RecentResponse(episodes=[_row_to_recent(r) for r in rows])
