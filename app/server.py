from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import override
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from app.auth import is_authenticated
from app.config import get_settings
from app.db import bootstrap_schema, close_pool, get_pool
from app.routers import auth as auth_router
from app.routers import db as db_router
from app.routers import player as player_router
from app.routers import s3 as s3_router
from app.routers import shows as shows_router

API_AUTH_EXEMPT: frozenset[str] = frozenset({"/api/health", "/api/auth/login"})


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await bootstrap_schema(conn)
    yield
    await close_pool()


# Fail fast at import if any required env var is missing.
get_settings()

app = FastAPI(title="s3player", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def site_password_gate(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    path = request.url.path
    if path == "/login":
        return await call_next(request)
    settings = get_settings()
    if path.startswith("/api/"):
        if path in API_AUTH_EXEMPT:
            return await call_next(request)
        if is_authenticated(request, settings.site_password):
            return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={"detail": "unauthenticated"},
        )
    if is_authenticated(request, settings.site_password):
        return await call_next(request)
    target = path
    if request.url.query:
        target = f"{path}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(target, safe='')}",
        status_code=303,
    )


app.include_router(auth_router.router)
app.include_router(s3_router.router)
app.include_router(db_router.router)
app.include_router(shows_router.router)
app.include_router(player_router.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class SPAStaticFiles(StaticFiles):
    @override
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", SPAStaticFiles(directory=frontend_dist, html=True), name="frontend")


def run() -> None:
    uvicorn.run("app.server:app", host="127.0.0.1", port=8000, reload=True)
