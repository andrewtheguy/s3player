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
- `/api/*` — require either the `s3player_auth` HMAC cookie or an `Authorization: Bearer <token>` header (both verified by `app.auth.is_authenticated`); unauthenticated → 401 JSON. Exempt: `/api/auth/login`.
- Everything else (SPA routes) — unauthenticated → 303 redirect to `/login?next=…`.

The auth token is a deterministic HMAC-SHA256 value derived from the shared site password and a fixed authentication message. Browsers receive it as a cookie via the HTML form login at `/login`; non-browser clients (mobile apps, CLIs, scripts) obtain the same token by `POST /api/auth/login` with `{"password": "..."}` and present it as `Authorization: Bearer <token>` on subsequent requests. The cookie settings live with the auth helper code. There is no per-user identity; it is a single shared password, and the token does not expire unless `SITE_PASSWORD` rotates.

For standalone native, mobile, desktop, or CLI clients, the JSON API is sufficient without a CORS requirement: authenticate with `/api/auth/login`, send the bearer token on protected API requests, use the browse/detail/player endpoints for metadata and playback state, and use either the proxied audio stream endpoint or the presigned audio URL endpoint for media fetches.

### Public vs internal API surface

The split is by URL prefix:

- **`/api/*` is the public API.** Every route is documented in OpenAPI (`/docs`, `/redoc`, `/openapi.json`) and is supported for third-party clients (mobile, desktop, CLI). New `/api/*` routes go in a topic-specific router (`auth.py`, `shows.py`, `player.py`, or a new public file) and must carry a docstring + `summary`.
- **Everything else is internal.** Today that is just `GET /login` and `POST /login` — the HTML form and auth cookie creation for browsers. Internal routes live in `app/routers/internal.py`, whose router declares `include_in_schema=False` so they stay out of the OpenAPI document. New internal routes go in `internal.py` and must not use the `/api/` prefix.

### Production route protection

The production Python server enforces authentication in `site_password_gate` before requests reach API routers or the mounted SPA/static files.

| Path | Site auth? | Player session token? | Notes |
| --- | --- | --- | --- |
| `GET /login`, `POST /login` | No | No | **Internal use only** — HTML login form and auth cookie creation for the SPA in browsers; not part of the public API and not documented in OpenAPI. Third-party clients should use `POST /api/auth/login` instead. |
| `POST /api/auth/login` | No | No | Password-to-bearer-token login for non-browser clients. |
| `GET /api/shows/stations` | Yes | No | Lists stations. |
| `GET /api/shows/stations/{station}/shows` | Yes | No | Lists shows for a station. |
| `GET /api/shows/{show_id}` | Yes | No | Reads show detail. |
| `GET /api/shows/{show_id}/months` | Yes | No | Lists month buckets for a show. |
| `GET /api/shows/{show_id}/months/{year}/{month}/episodes` | Yes | No | Lists episodes in a month. |
| `GET /api/shows/episodes/{episode_id}` | Yes | No | Reads episode detail. |
| `GET /api/shows/episodes/{episode_id}/audio` | Yes | No | Backend audio stream proxy; supports S3 range forwarding. |
| `GET /api/shows/episodes/{episode_id}/audio_url` | Yes | No | Returns a presigned S3 URL for direct media fetches. |
| `POST /api/player/session/claim` | Yes | No | Creates a new active player session and displaces any previous session token. |
| `POST /api/player/session/validate` | Yes | Yes | Requires `X-Player-Session`; stale/displaced tokens return 409. |
| `POST /api/player/episodes/{id}/progress` | Yes | Yes | Requires `X-Player-Session`; stale/displaced tokens return 409. |
| `POST /api/player/episodes/{id}/complete` | Yes | Yes | Requires `X-Player-Session`; stale/displaced tokens return 409. |
| `GET /api/player/episodes/{id}/progress` | Yes | No | Reads saved progress. |
| `GET /api/player/recent`, `GET /api/player/in-progress` | Yes | No | Reads playback history rows. |
| All other `/api/*` paths | Yes | N/A | Site auth is checked before routing; authenticated unknown paths return 404. |
| SPA/static routes, `/docs`, `/redoc`, `/openapi.json` | Yes | No | Unauthenticated requests redirect to `/login?next=...`; authenticated requests continue. |

Site-auth-protected API routes accept either the `s3player_auth` cookie or `Authorization: Bearer <token>`. Player-session-token routes additionally require `X-Player-Session`; missing tokens return `401 {"detail": "missing session token"}`, and stale/displaced tokens return `409 {"detail": "session displaced"}`.

### Routers

Routers live under `app/routers/` and are split by visibility: one internal router holds every non-public route, and the rest are public, topic-specific routers. Postgres-backed request handlers get a connection with the shared `app.db.get_conn` dependency, which acquires from the global pool and releases on request end.

| Router | Prefix | Visibility | Purpose |
| --- | --- | --- | --- |
| `internal.py` | (none) | Internal | HTML `/login` form and auth cookie creation. Router-level `include_in_schema=False`. |
| `auth.py` | `/api/auth` | Public | `POST /api/auth/login` — site-password-to-bearer-token exchange for non-browser clients. |
| `shows.py` | `/api/shows` | Public | HTTP adapter for browse hierarchy, episode detail, audio stream proxy, and presigned audio URL endpoints. Catalog queries live in `app.catalog`; audio presign/stream logic lives in `app.audio`. |
| `player.py` | `/api/player` | Public | HTTP adapter for session claim/validate, progress save, complete, recent, and in-progress endpoints. Player session/state rules live in `app.player_state`. |

### Audio stream proxy

`GET /api/shows/episodes/{episode_id}/audio` is the backend audio proxy. It resolves the episode id to an S3 key, forwards the client's `Range` header to S3 when present, streams the S3 body back as `audio/mp4`, and includes `Accept-Ranges`, `Content-Length`, and `Content-Range` headers when S3 returns them. The route returns `206` only when S3 returns `ContentRange`; otherwise it returns `200`.

`GET /api/shows/episodes/{episode_id}/audio_url` is the direct-fetch alternative. It returns a presigned S3 URL plus its expiry for clients that do not need the backend to proxy media bytes.

Supporting modules outside `app/routers/` hold reusable application logic:

- `app.catalog` — station/show/month/episode read queries and row mapping.
- `app.audio` — presigned audio URLs, S3 range forwarding, stream-body cleanup, and S3 audio error normalization.
- `app.player_state` — single-session claim/displacement, progress writes, completion, and recent/in-progress queries.

### Database

The backend uses one lazily-created asyncpg pool. A jsonb codec is registered per connection so chapters round-trip as native Python data. `app.db.get_conn` is the FastAPI dependency used by Postgres-backed routers.

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
- `test_auth_router.py` — HTML login cookie flow, token login, bearer auth, and API auth failures.
- `test_player_router.py` — session claim/validate, displacement handling, progress writes, completion writes, and progress defaults.
- `test_parse_key.py`, `test_chapters.py` — pure-function unit tests for the indexer's parsing helpers.

## Deployment

The Dockerfile is a three-stage build:

1. **frontend-builder**: installs frontend dependencies and builds `frontend/dist/`.
2. **backend-builder**: installs Python dependencies into the runtime environment.
3. **runtime**: copies installed Python packages, console scripts, the `app/` source, built frontend assets, and static `ffmpeg`/`ffprobe` binaries. The container entrypoint runs `uvicorn app.server:app`.

CI (`.github/workflows/`) runs the same backend and frontend checks listed in `CLAUDE.md`, plus pytest and a CLI entry-point smoke test. The container workflow builds and publishes multi-arch images for releases or manual dispatches. There is no automated indexer run; `s3player index` is invoked manually or by an out-of-band scheduler when new files land in S3.
