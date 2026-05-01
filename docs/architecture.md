# Architecture

s3player is a single-process FastAPI app that serves both a JSON API and a built React SPA, fronted by a single password gate. Audio files live in S3; episode metadata, chapters, and per-episode playback state live in Postgres. A separate one-shot CLI walks the bucket and (idempotently) populates Postgres. This document is a map for new contributors — for runbook-style usage, see the README.

## Stack

- **Backend**: Python 3.12, FastAPI, asyncpg, boto3, ffprobe (subprocess) for chapter extraction.
- **Frontend**: React + TypeScript, Vite, TailwindCSS, react-router, Biome.
- **Storage**: S3-compatible object store for audio; Postgres for everything else.
- **Tooling**: `uv` for Python, `bun` for JS, `ruff` + `basedpyright` for backend checks, `biome` + `tsc -b` for frontend checks.

## Repo layout

```
app/                  Backend Python package
  server.py           FastAPI app + lifespan + auth middleware + SPA mount
  cli.py              `s3player` CLI: dispatches to server.run() or indexer.run()
  config.py           Settings dataclass (env-driven, lru_cached)
  db.py               Global asyncpg pool (min 1, max 5; jsonb codec)
  auth.py             HMAC cookie token check
  indexer.py          S3 → Postgres indexer, schema bootstrap, ffprobe driver
  parse_key.py        Parses YYYYMMDD_HHMM_HHMM_SHOW.m4a S3 keys
  chapters.py         Normalizes ffprobe chapter output
  s3_client.py        boto3 client factory
  routers/            FastAPI routers — see § Backend
frontend/src/
  routes/             Page components + AppRouter
  lib/                api client, hooks, helpers
  components/         shared UI (TableRow, EpisodeCard, BreadcrumbTrail, etc.)
tests/                pytest suite (TestClient + mocked asyncpg connection)
Dockerfile            multi-stage: bun build → uv sync → slim runtime + ffmpeg
.github/workflows/    CI: ruff/basedpyright/pytest + biome/tsc
```

## Backend

### Entry

`app.server:app` is the FastAPI instance. CLI entry `app.cli:main` (registered as the `s3player` script in `pyproject.toml`) dispatches to:

- `s3player server` → `app.server.run` (uvicorn on `127.0.0.1:8000`)
- `s3player index` → `app.indexer.run` (one-shot, exits when done)

The lifespan handler in `app/server.py:28-34` opens the asyncpg pool and runs `bootstrap_schema` — there is no separate migration tool. `get_settings()` is called at module import (`app/server.py:38`) so missing env vars fail fast before the server binds.

### Auth middleware

`site_password_gate` in `app/server.py:50-76` is the single gate:

- `/login` — always allowed (handled by `app.routers.auth`).
- `/api/*` — require the `s3player_auth` HMAC cookie (verified by `app.auth.is_authenticated`); unauthenticated → 401 JSON. Exempt: `/api/health`.
- Everything else (SPA routes) — unauthenticated → 303 redirect to `/login?next=…`.

The cookie token is `HMAC-SHA256(site_password, "s3player_auth")`, scoped 7 days, httponly. There is no per-user identity — it's a single shared password.

### Routers

All under `app/routers/`. Each gets a connection by `Depends(get_conn)` from `app/routers/db.py:12`, which acquires from the global pool and releases on request end.

| Router | Prefix | Purpose |
| --- | --- | --- |
| `auth.py` | `/login` | Form-based login, sets/clears the auth cookie. |
| `db.py` | `/api/db` | Health check + the `get_conn` dependency. |
| `s3.py` | `/api/s3` | Raw S3 listing (debug/inspection). |
| `shows.py` | `/api/shows` | Browse hierarchy (stations → shows → years → months → episodes) and `GET /episodes/{id}/audio` with HTTP 206 range support (boto3 calls go through `asyncio.to_thread`). |
| `player.py` | `/api/player` | Session claim/validate, progress save, complete, recent/in-progress lists. |

### Database

Single asyncpg pool created lazily in `app/db.py:19-29`. A jsonb codec is registered per connection so chapters round-trip as native dicts.

Schema (created by `bootstrap_schema` in `app/indexer.py:26-69`, all `IF NOT EXISTS`):

- **`shows`** — `(id, station, name)`, unique on `(station, name)`.
- **`episodes`** — `(id, s3_key UNIQUE, show_id FK, aired_on, chapters JSONB, time_slot, deleted)`. `deleted` is the soft-delete flag the indexer toggles when keys disappear/reappear in S3.
- **`player_session`** — single row pinned to `id = 1` via `CHECK (id = 1)`. Holds the currently-active session token, the episode it claimed, and `last_seen_at`. This is the basis for the single-active-session rule.
- **`episode_play_state`** — `(episode_id PK, position_ms, duration_ms, last_played_at, completed)`. One row per started episode.

### Indexer

`app/indexer.py:run` is invoked by the CLI:

1. Open the pool, bootstrap schema.
2. For each station prefix in `STATION_PREFIXES` (`app/indexer.py:18-21`), paginate `ListObjectsV2` and collect every `.m4a` key.
3. `parse_episode_key` (`app/parse_key.py`) extracts `aired_on`, `time_slot`, and the show name from each key.
4. Upsert `shows`, then `INSERT … ON CONFLICT (s3_key) DO NOTHING` into `episodes`. Newly-inserted rows return their id.
5. For each new episode: presign the S3 URL (5-min expiry), shell out to `ffprobe -show_chapters` (60s timeout), normalize via `app.chapters.normalize_chapters`, and update `episodes.chapters`.
6. Soft-delete any `episodes.s3_key` not seen in this run; restore any previously-deleted key that reappeared.

The indexer is safe to re-run: every write is an upsert or a conditional update.

## Frontend

### Routing

`frontend/src/routes/router.tsx` defines the route tree under a single `RootLayout`:

```
/                              → redirect to /stations
/stations                      → StationsPage   (Continue listening + Recently played + station list)
/stations/:station             → ShowsPage
/shows/:show_id                → YearsPage
/shows/:show_id/:year          → MonthsPage
/shows/:show_id/:year/:month   → EpisodesPage
/player/:episode_id            → PlayerPage
```

In production the SPA is served by `SPAStaticFiles` (`app/server.py:91-99`), which catches 404s on file lookups and replays them against `index.html` — that's how deep links survive a hard refresh.

### Data layer

- **`frontend/src/lib/api.ts`** — `apiFetch` (GET) and `apiPostJson` (POST) wrap `fetch` and on 401 redirect to `/login?next=…`. `playerApi` is a small typed object exposing `claim`, `validate`, `progress`, `complete`, `getProgress`.
- **`useFetch<T>(path)`** (`lib/use-fetch.ts`) — drop-in `{ data, error, loading }` hook used by every list page.
- **`usePlayerSession(episodeId)`** (`lib/playerSession.ts`) — owns the player session lifecycle:
  - On mount, calls `claim()` and stores the token in a ref. Token is sent as `X-Player-Session` on every write.
  - State machine: `pending → active | displaced | error`.
  - 30s heartbeat (`PAUSED_PING_MS`) calls `validate` while paused; HTTP 409 from the server flips state to `displaced`.
  - Exposes `postProgress`, `postComplete`, `reclaim`.

### Build / dev

`frontend/vite.config.ts` proxies `/api`, `/login`, and `/docs` to `http://127.0.0.1:8000` so the dev frontend on `:5173` and the dev backend on `:8000` work as one origin from the browser's perspective. In Docker / production, the backend serves the built dist directly and there is no proxy.

## Key flows

### Indexing

```
s3player index
  → asyncpg pool + bootstrap_schema
  → S3 ListObjectsV2 (paginated) per station prefix
  → parse_episode_key  ──→ shows upsert  ──→ episodes insert
  → for each new episode: presign URL → ffprobe → chapters JSONB
  → soft-delete missing keys; restore reappeared keys
```

### Playback (one tab)

```
PlayerPage mounts
  → POST /api/player/session/claim       (gets session_token)
  → GET  /api/player/episodes/{id}/progress   (seeks audio to saved pos)
  → audio plays, every ~10s and on pause:
       POST /api/player/episodes/{id}/progress  with X-Player-Session
  → on `ended`:
       POST /api/player/episodes/{id}/complete  (sets completed=TRUE)
```

### Single active session (displacement)

`player_session` has exactly one row. Every write goes through `_TOUCH_SQL` (`app/routers/player.py:63-69`):

```sql
UPDATE player_session
   SET last_seen_at = now(),
       current_episode_id = COALESCE($2, current_episode_id)
 WHERE id = 1 AND session_token = $1
RETURNING 1
```

If `RETURNING 1` is empty, the token has been displaced by another claim and the route raises HTTP 409 (`app/routers/player.py:121-122`). The frontend hook flips state to `displaced` and renders a "Resume here" banner that re-claims. While paused, the validate ping ensures a displaced tab notices within ~30s instead of only on the next progress write.

### Home rows

`stations.tsx` renders two horizontal rails above the stations grid:

- **Continue listening** — `GET /api/player/in-progress` → `completed = FALSE AND duration_ms IS NOT NULL AND position_ms < duration_ms - 30000`.
- **Recently played** — `GET /api/player/recent` → `completed = TRUE`.

The two filters are mutually exclusive, so an episode never appears in both.

## Tests

`tests/` is pure unit-level: `pytest` + FastAPI `TestClient` + an `AsyncMock` injected as the `get_conn` dependency. `tests/conftest.py` pre-sets the env vars `app.config` requires, so importing the app under test never hits a real DB or S3. There are no integration tests against a real Postgres or bucket — DB rows are mocked at the asyncpg surface (`fetch`, `fetchrow`, `fetchval`, `execute`).

Files:

- `test_shows_router.py` — browse hierarchy, audio range requests (206/416).
- `test_db_router.py`, `test_s3_router.py` — health and S3 listing endpoints.
- `test_parse_key.py`, `test_chapters.py` — pure-function unit tests for the indexer's parsing helpers.

There is no test for `player.py` yet.

## Deployment

The Dockerfile is a three-stage build:

1. **frontend-builder** (`oven/bun:1.3-alpine`): `bun install --frozen-lockfile` → `bun run build` → `frontend/dist/`.
2. **backend-builder** (`python:3.12-slim-trixie` + `uv`): `uv sync --locked --no-dev` into `/usr/local/`.
3. **runtime** (`python:3.12-slim-trixie`): copies installed Python packages, the `s3player`/`uvicorn` console scripts, the `app/` source, and `frontend/dist/`. Static `ffmpeg` and `ffprobe` binaries are pulled from `mwader/static-ffmpeg:8.0.1`. Entry: `tini → uvicorn app.server:app --host 0.0.0.0 --port 8000`.

CI (`.github/workflows/`) runs the same checks listed in `CLAUDE.md`: `ruff check`, `ruff format --check`, `basedpyright`, `pytest`, plus `bun run lint` and `bun run typecheck` in `frontend/`. There is no automated indexer run — `s3player index` is invoked manually (or by an out-of-band scheduler) when new files land in S3.
