# Architecture

s3player is a FastAPI app with a JSON API, a built React SPA in production, and a single password gate in front of both. Audio files live in S3; episode metadata, chapters, and per-episode playback state live in Postgres. A separate one-shot CLI walks the bucket and idempotently populates Postgres. This document is a map for new contributors; for runbook-style usage, see the README.

## Stack

- **Backend**: Python 3.12, FastAPI, asyncpg, boto3, ffprobe (subprocess) for chapter extraction.
- **Frontend**: React + TypeScript, Vite, TailwindCSS, react-router, Biome.
- **Storage**: S3-compatible object store for audio; Postgres for everything else.
- **Tooling**: `uv` for Python, `bun` for JS, `ruff` + `basedpyright` for backend checks, `biome` + `tsc -b` for frontend checks.

## Repo Layout

```
app/                  Backend Python package: FastAPI app, CLI, config, DB, S3, indexer, routers
frontend/             Vite React app and frontend tooling
tests/                pytest suite using TestClient and mocked asyncpg calls
Dockerfile            multi-stage image build for frontend assets, backend deps, and runtime
.github/workflows/    CI and container image workflows
```

## Backend

### Entry

`app.server:app` is the FastAPI instance. CLI entry `app.cli:main` (registered as the `s3player` script in `pyproject.toml`) dispatches to:

- `s3player server` → `app.server.run` (local uvicorn server)
- `s3player index` → `app.indexer.run` (one-shot, exits when done)

The FastAPI lifespan handler opens the asyncpg pool and runs `bootstrap_schema`; there is no separate migration tool. Settings are loaded during server import so missing required environment variables fail fast before the server binds.

### Auth middleware

`site_password_gate` is the single gate:

- `/login` — always allowed (handled by `app.routers.auth`).
- `/api/*` — require either the `s3player_auth` HMAC cookie or an `Authorization: Bearer <token>` header (both verified by `app.auth.is_authenticated`); unauthenticated → 401 JSON. Exempt: `/api/health`, `/api/auth/login`.
- Everything else (SPA routes) — unauthenticated → 303 redirect to `/login?next=…`.

The auth token is a deterministic HMAC-SHA256 value derived from the shared site password and a fixed authentication message. Browsers receive it as a cookie via the HTML form login at `/login`; non-browser clients (mobile apps, CLIs, scripts) obtain the same token by `POST /api/auth/login` with `{"password": "..."}` and present it as `Authorization: Bearer <token>` on subsequent requests. The cookie settings live with the auth helper code. There is no per-user identity; it is a single shared password, and the token does not expire unless `SITE_PASSWORD` rotates.

For standalone native, mobile, desktop, or CLI clients, the JSON API is sufficient without a CORS requirement: authenticate with `/api/auth/login`, send the bearer token on protected API requests, use the browse/detail/player endpoints for metadata and playback state, and use either the proxied audio stream endpoint or the presigned audio URL endpoint for media fetches.

### Routers

All under `app/routers/`. Request handlers get a connection with the shared `get_conn` dependency, which acquires from the global pool and releases on request end.

| Router | Prefix | Purpose |
| --- | --- | --- |
| `auth.py` | `/login` | Form-based login and auth cookie creation. |
| `db.py` | `/api/db` | Health check + the `get_conn` dependency. |
| `s3.py` | `/api/s3` | Raw S3 listing (debug/inspection). |
| `shows.py` | `/api/shows` | Browse hierarchy (stations → shows → months → episodes; years are derived client-side from month buckets), `GET /episodes/{id}/audio` with HTTP 206 range support, and `GET /episodes/{id}/audio_url` returning a presigned S3 URL for clients that fetch audio directly (boto3 calls go through `asyncio.to_thread`). |
| `player.py` | `/api/player` | Session claim/validate, progress save, complete, recent/in-progress lists. |

### Database

The backend uses one lazily-created asyncpg pool. A jsonb codec is registered per connection so chapters round-trip as native Python data.

Schema is created by `bootstrap_schema` using `IF NOT EXISTS` statements:

- **`shows`** — station/name records, unique by station and show name.
- **`episodes`** — S3 key, show, air date, optional chapters, time slot, and a soft-delete flag. The indexer toggles the flag when keys disappear from or reappear in S3.
- **`player_session`** — the single currently-active player session, including its token, claim time, and last heartbeat. It is global and not scoped to an episode.
- **`episode_play_state`** — per-episode playback position, duration, last-played timestamp, and completion state.

### Indexer

`app.indexer.run` is invoked by the CLI:

1. Open the pool, bootstrap schema.
2. For each configured station prefix, paginate `ListObjectsV2` and collect every `.m4a` key.
3. `parse_episode_key` (`app/parse_key.py`) extracts `aired_on`, `time_slot`, and the show name from each key.
4. Upsert `shows`, then `INSERT … ON CONFLICT (s3_key) DO NOTHING` into `episodes`. Newly-inserted rows return their id.
5. For each new episode: presign the S3 URL, shell out to `ffprobe -show_chapters` with a bounded timeout, normalize via `app.chapters.normalize_chapters`, and update `episodes.chapters`.
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

In production the SPA is served by `SPAStaticFiles`, which catches 404s on static file lookups and replays them against `index.html`. That is how deep links survive a hard refresh.

### Data layer

- **`frontend/src/lib/api.ts`** — `apiFetch` (GET) and `apiPostJson` (POST) wrap `fetch` and on 401 redirect to `/login?next=…`. `playerApi` is a small typed object exposing `claim`, `validate`, `progress`, `complete`, `getProgress`.
- **`useFetch<T>(path)`** (`lib/use-fetch.ts`) — drop-in `{ data, error, loading }` hook used by every list page.
- **`usePlayerSession(episodeId)`** (`lib/playerSession.ts`) — owns the player session lifecycle:
  - On a fresh tab, starts inactive so opening a player page does not displace another device. The user must explicitly start playback, which calls `claim()`.
  - The claim token is stored in a ref AND mirrored to `sessionStorage` (key `s3player.session_token`) so the same tab rehydrates as `active` across React remounts, hot reloads, full reloads, and navigation between episodes — no per-episode scoping, since the backend session row is global.
  - Token is sent as `X-Player-Session` on every write.
  - State machine: `inactive → pending → active | displaced | error`. Transient call failures (network, 5xx) keep the active session and surface a non-blocking `transientError`; only HTTP 409 flips to `displaced`.
  - A periodic heartbeat calls `validate` while paused.
  - Exposes `postProgress`, `postComplete`, `reclaim`.

### Build / dev

`frontend/vite.config.ts` proxies API, login, and OpenAPI docs paths to the backend dev server so Vite and FastAPI work as one origin from the browser's perspective. In Docker / production, the backend serves the built dist directly and there is no proxy.

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
  → GET  /api/player/episodes/{id}/progress   (seeks audio to saved pos)
  → user clicks "Take over playback":
       POST /api/player/session/claim    (gets session_token)
  → audio plays, periodically and on pause:
       POST /api/player/episodes/{id}/progress  with X-Player-Session
  → on `ended`:
       POST /api/player/episodes/{id}/complete  (sets completed=TRUE)
```

### Single active session (displacement)

`player_session` has exactly one row. Claiming a session is the operation that makes a player active and displaces any previous token, so the frontend only calls it from the explicit takeover control. Every other mutating player API validates the presented token against that row before doing player-state work. If validation matches no row, the token has been displaced by another claim and the route raises HTTP 409. The frontend hook flips state to `displaced` and disables playback controls until the user explicitly takes over again. While paused, the validate ping lets a displaced tab notice without waiting for the next progress write.

### Home rows

The stations page renders two horizontal rails above the stations grid:

- **Continue listening** — `GET /api/player/in-progress` returns incomplete episodes with enough saved duration and remaining playback time to resume.
- **Recently played** — `GET /api/player/recent` returns completed episodes ordered by last playback.

The two filters are mutually exclusive, so an episode should not appear in both.

## Tests

`tests/` is pure unit-level: `pytest` + FastAPI `TestClient` + an `AsyncMock` injected as the `get_conn` dependency. `tests/conftest.py` pre-sets the env vars `app.config` requires, so importing the app under test never hits a real DB or S3. There are no integration tests against a real Postgres or bucket — DB rows are mocked at the asyncpg surface (`fetch`, `fetchrow`, `fetchval`, `execute`).

Current coverage includes:

- `test_shows_router.py` — browse hierarchy, audio range requests (206/416).
- `test_db_router.py`, `test_s3_router.py` — health and S3 listing endpoints.
- `test_auth_router.py` — HTML login cookie flow, token login, bearer auth, and API auth failures.
- `test_player_router.py` — session claim/validate, displacement handling, progress writes, completion writes, and progress defaults.
- `test_parse_key.py`, `test_chapters.py` — pure-function unit tests for the indexer's parsing helpers.

## Deployment

The Dockerfile is a three-stage build:

1. **frontend-builder**: installs frontend dependencies and builds `frontend/dist/`.
2. **backend-builder**: installs Python dependencies into the runtime environment.
3. **runtime**: copies installed Python packages, console scripts, the `app/` source, built frontend assets, and static `ffmpeg`/`ffprobe` binaries. The container entrypoint runs `uvicorn app.server:app`.

CI (`.github/workflows/`) runs the same backend and frontend checks listed in `CLAUDE.md`, plus pytest and a CLI entry-point smoke test. The container workflow builds and publishes multi-arch images for releases or manual dispatches. There is no automated indexer run; `s3player index` is invoked manually or by an out-of-band scheduler when new files land in S3.
