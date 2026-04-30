from collections.abc import AsyncIterator
from typing import Annotated

from asyncpg.pool import PoolConnectionProxy
from fastapi import APIRouter, Depends, HTTPException

from app.db import get_pool

router = APIRouter(prefix="/api/db", tags=["db"])


async def get_conn() -> AsyncIterator[PoolConnectionProxy]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@router.get("/health")
async def db_health(
    conn: Annotated[PoolConnectionProxy, Depends(get_conn)],
) -> dict[str, str | int]:
    try:
        result = await conn.fetchval("SELECT 1")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"db error: {e}") from e
    if result != 1:
        raise HTTPException(status_code=503, detail="db sanity check failed")
    return {"status": "ok", "result": result}
