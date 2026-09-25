# Architecture

s3player is a single Rust binary: an axum server with a JSON API, the React SPA embedded at build time, and a single password gate in front of both. Audio files live in S3; episode metadata, chapters, and per-episode playback state live in Postgres. A one-shot `index` subcommand walks the bucket and idempotently populates Postgres. This document is a map for new contributors; for runbook-style usage, see the README.

## Stack

- **Backend**: Rust 2024, axum, sqlx (Postgres, runtime-checked queries), aws-sdk-s3, clap. Chapter info comes from per-episode `.metadata.json` sidecar objects in S3 (no ffprobe / ffmpeg).
- **Frontend**: React + TypeScript, Vite, TailwindCSS, react-router, Biome.
- **Storage**: S3-compatible object store for audio (path-style requests); Postgres for everything else.
- **Tooling**: `cargo` (clippy with `-D warnings`), `bun` for JS, `biome` + `tsc -b` for frontend checks.

## Repo Layout

```
src/                  Rust backend: CLI, server, handlers, indexer
build.rs              builds and stages the frontend for release builds
frontend/             Vite React app and frontend tooling
Dockerfile            multi-stage build (binary + runtime images)
.github/workflows/    CI and release workflows
```

## Backend

### Module layout

| Module | Responsibility |
| --- | --- |
| `main.rs` | Loads `.env`, parses the CLI, connects Postgres/S3, dispatches to `server` or `index` |
| `cli.rs` | clap definitions; every setting is a flag with an env-var fallback (`SERVER_HOST`, `S3_*`, `DATABASE_URL` / `POSTGRES_*`, `SITE_PASSWORD`) |
| `db.rs` | Pool construction (`DATABASE_URL` or discrete `POSTGRES_*` pieces) and `IF NOT EXISTS` schema bootstrap |
| `s3.rs` | S3 client construction (timeouts, retries, checksums only when required, path-style), paginated listing, whole-object fetch, error-code helper |
| `server.rs` | `AppState`, the route table, extractors with JSON 422 rejections, bind + graceful shutdown |
| `error.rs` | `AppError` → status + `{"detail": "..."}`; 500/502 hide the error chain from clients and log it |
| `auth.rs` | Token derivation, the site-password gate middleware, `/login` HTML form, `POST /api/auth/login` |
| `shows.rs` | Browse hierarchy, episode detail, favorites (queries and handlers) |
| `audio.rs` | Audio stream proxy with `Range` forwarding; presigned URL |
| `summaries.rs` | Per-chapter summary prefix derivation, listing, concurrent fetch |
| `player.rs` | Single-session claim/validate, progress writes, recent/in-progress rows |
| `indexer.rs` | The S3 → Postgres indexer |
| `show_metadata.rs` | Sidecar parsing: `show.{name,date,start,end}` and chapter normalization |
| `assets.rs` | Embedded SPA (release) or a pointer to the Vite dev server (dev) |

### Entry

`s3player server` connects the pool, bootstraps the schema, builds the S3 client, and binds `$SERVER_HOST:$SERVER_PORT`. Missing required settings fail at argument parsing, before anything connects. `s3player index [--overwrite]` runs the indexer once and exits. SIGINT/SIGTERM stop the server gracefully.

### Auth gate

`auth::site_password_gate` is middleware over every route, including the SPA fallback:

- `/login` — always allowed (the internal HTML form).
- `/api/*` — require either the `s3player_auth` HMAC cookie or an `Authorization: Bearer <token>` header; unauthenticated → 401 `{"detail": "unauthenticated"}`. Exempt: `/api/auth/login`.
- Everything else (SPA routes and assets) — unauthenticated → 303 redirect to `/login?next=…`.

The auth token is a deterministic HMAC-SHA256 value keyed by the shared site password over a fixed message. Browsers receive it as a browser-session cookie from the HTML form at `/login`; non-browser clients (mobile apps, CLIs, scripts) obtain the same token by `POST /api/auth/login` with `{"password": "..."}` and present it as a bearer token. There is no per-user identity, and the token does not expire unless `SITE_PASSWORD` rotates. Comparisons are constant-time.

For standalone native, mobile, desktop, or CLI clients the JSON API is sufficient without CORS: authenticate with `/api/auth/login`, send the bearer token, use the browse/detail/player endpoints for metadata and playback state, and either the proxied audio stream or the presigned audio URL for media.

### Public API

`/api/*` is the public API; everything else (`GET`/`POST /login`) is internal. Errors are always `{"detail": "..."}`. Malformed path/query/body values are 422; unknown `/api/*` paths are a JSON 404.

| Method & path | Auth | Purpose |
| --- | --- | --- |
| `POST /api/auth/login` | none | `{"password"}` → `{"token"}`; 401 `wrong_password` |
| `GET /api/shows/stations` | site | Stations with show counts |
| `GET /api/shows/stations/{station}/shows` | site | Shows of a station with episode counts and favorite flag |
| `GET /api/shows/favorites` | site | Favorite shows, latest-aired first |
| `GET /api/shows/{show_id}` | site | Show detail; 404 if missing |
| `POST`/`DELETE /api/shows/{show_id}/favorite` | site | Idempotent favorite toggle; POST 404s for a missing show |
| `GET /api/shows/{show_id}/recent-episodes?limit=` | site | Latest episodes (default 20, 1–50) with play state |
| `GET /api/shows/{show_id}/months` | site | (year, month) buckets with counts |
| `GET /api/shows/{show_id}/months/{year}/{month}/episodes` | site | Episodes of a month, with chapters |
| `GET /api/shows/episodes/{episode_id}` | site | Episode detail with chapters and parent show |
| `GET /api/shows/episodes/{episode_id}/audio` | site | Audio stream proxy (see below) |
| `GET /api/shows/episodes/{episode_id}/audio_url` | site | Presigned S3 URL (1h) for direct fetch; 502 if presigning fails |
| `GET /api/shows/episodes/{episode_id}/chapter_summaries` | site | Per-chapter markdown summaries, 1-based `index`; 502 if listing fails |
| `POST /api/player/session/claim` | site | Issue a new session token, displacing the previous one |
| `POST /api/player/session/validate` | site + session | 200 while the token owns the session |
| `GET /api/player/episodes/{episode_id}/progress` | site | Saved position (zeros/false when none) |
| `POST /api/player/episodes/{episode_id}/progress` | site + session | `{position_ms, duration_ms?, completed?}`; 404 for a missing episode |
| `DELETE /api/player/episodes/{episode_id}/progress` | site + session | Drop play state (idempotent) |
| `GET /api/player/recent-completed?limit=` | site | Completed episodes (default 10, 1–50) |
| `GET /api/player/in-progress?limit=` | site | Resumable episodes (default 10, 1–50) |

"Session" routes require `X-Player-Session`: missing → 401 `{"detail": "missing session token"}`, displaced → 409 `{"detail": "session displaced"}`.

### Audio stream proxy

`GET /api/shows/episodes/{episode_id}/audio` resolves the episode id to an S3 key, forwards the client's `Range` header to S3 when present, and streams the S3 body back in 64 KiB chunks. `Content-Type` comes from the key extension (`.m4a` → `audio/mp4`, `.ogg` → `audio/ogg`); `Accept-Ranges`, `Content-Length`, and `Content-Range` are passed through. It returns `206` only when S3 returns `Content-Range`, otherwise `200`; 404 for a missing episode or object, 416 for an unsatisfiable range, 502 for other upstream failures. If the upstream body breaks mid-stream the response is aborted and the failure logged.

### Database

One sqlx pool (max 5 connections). Queries are plain runtime-checked SQL mapped with `FromRow`; chapters round-trip as `JSONB` via `sqlx::types::Json`.

Schema is created at startup by `db::connect` using `IF NOT EXISTS` statements:

- **`shows`** — station/name records, unique by station and show name.
- **`episodes`** — S3 key, show, air date, optional chapters, time slot, and a soft-delete flag. The indexer toggles the flag when keys disappear from or reappear in S3.
- **`player_session`** — the single currently-active player session, including its token, claim time, and last heartbeat. It is global and not scoped to an episode.
- **`episode_play_state`** — per-episode playback position, duration, last-played timestamp, and completion state.
- **`favorite_shows`** — favorited show ids with the time they were favorited.

### Indexer

`indexer::run`:

1. List `shows/` with delimiter `/` to discover station prefixes.
2. For each station prefix, list every key and split the listing into the set of audio keys (`.m4a` and `.ogg`) and the list of `.metadata.json` sidecar keys.
3. For each sidecar, derive `audio_key` by stripping `.metadata.json`. Skip if the audio key is not in the listed set (sidecar without audio file).
4. Fetch the sidecar and parse it as a JSON object. `show_metadata::extract_show_metadata` reads `show.{name, date, start, end}` into a `ShowMetadata` (name, `aired_on`, `time_slot`) or a `ShowMetadataError`. Sidecars whose `show.date` is missing are skipped at INFO; structurally invalid sidecars (missing `show` object, missing/empty name, malformed date) are skipped at WARN. `time_slot` is `HHMM_HHMM` when both `show.start` and `show.end` are `HH:MM`, otherwise NULL.
5. Upsert `shows` (keyed on station + name, cached per run), then `INSERT … ON CONFLICT (s3_key) DO NOTHING` into `episodes` (`--overwrite`: `DO UPDATE` of show, date, and time slot).
6. For each written episode, `normalize_chapters` runs over the same sidecar's `chapters` array (`start_ms_in_show` / `end_ms_in_show` / `title`) and sets `episodes.chapters` — no second S3 fetch. An overwritten episode whose sidecar has no chapter list gets its chapters cleared.
7. Soft-delete any `episodes.s3_key` not seen in this run; restore any previously-deleted key that reappeared.

The sidecar contract (canonical writer: upstream `extract_shows_rthk`; documented in `radio_show_tools/docs/show_sidecar.md`) is the only metadata source — the S3 key is treated purely as the audio path, not parsed for show name or air time.

The indexer is safe to re-run: every write is an upsert or a conditional update.

## Frontend

### Routing

`frontend/src/routes/router.tsx` defines the route tree under a single `RootLayout`:

```
/                              → redirect to /stations
/stations                      → StationsPage   (Continue listening + Recently Completed + station list)
/stations/:station             → ShowsPage
/shows/:show_id                → YearsPage
/shows/:show_id/:year          → MonthsPage
/shows/:show_id/:year/:month   → EpisodesPage
/player/:episode_id            → PlayerPage
```

In release builds the SPA is embedded in the binary and served by `assets::static_handler`, which answers any path that is not a bundled file with `index.html`. That is how deep links survive a hard refresh.

### Data layer

- **`frontend/src/lib/api.ts`** — `apiFetch` (GET), `apiPostJson` (POST), and `apiDelete` (DELETE) wrap `fetch` and on 401 redirect to `/login?next=…`. `playerApi` is a small typed object exposing `claim`, `validate`, `progress` (carries `completed`), `getProgress`, `deleteProgress`.
- **`useFetch<T>(path)`** (`lib/use-fetch.ts`) — drop-in `{ data, error, loading }` hook used by every list page.
- **`usePlayerSession(episodeId)`** (`lib/playerSession.ts`) — owns the player session lifecycle:
  - On a fresh tab, starts inactive so opening a player page does not displace another device. The user must explicitly start playback, which calls `claim()`.
  - The claim token is stored in a ref AND mirrored to `sessionStorage` (key `s3player.session_token`) so the same tab rehydrates as `active` across React remounts, hot reloads, full reloads, and navigation between episodes — no per-episode scoping, since the backend session row is global.
  - Token is sent as `X-Player-Session` on every write.
  - State machine: `inactive → pending → active | displaced | error`. Transient call failures (network, 5xx) keep the active session and surface a non-blocking `transientError`; only HTTP 409 flips to `displaced`.
  - A periodic heartbeat calls `validate` while paused.
  - Exposes `postProgress` (which carries the `completed` flag) and `claim`.

### Build / dev

`frontend/vite.config.ts` proxies `/api` and `/login` to the backend dev server so Vite and the Rust server work as one origin from the browser's perspective. Dev builds of the binary embed no UI. Release builds run `bun run build` from `build.rs` into Cargo's `OUT_DIR` (`S3PLAYER_FRONTEND_OUT_DIR`), compile it in with `rust-embed`, and need no proxy.

## Key flows

### Indexing

```
s3player index
  → sqlx pool + bootstrap_schema
  → S3 ListObjectsV2 (paginated) per station prefix
  → split listing into audio set (.m4a, .ogg) and .metadata.json sidecars
  → for each sidecar with a matching audio file:
       GetObject sidecar (once)
       → extract_show_metadata (show.name/date/start/end)
       → shows upsert  ──→ episodes insert
       → normalize_chapters over the same dict → chapters JSONB
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
       POST /api/player/episodes/{id}/progress  with completed=true (sets completed=TRUE)
```

### Single active session (displacement)

`player_session` has exactly one row. Claiming a session is the operation that makes a player active and displaces any previous token, so the frontend only calls it from the explicit takeover control. Every other mutating player API validates the presented token against that row before doing player-state work. If validation matches no row, the token has been displaced by another claim and the route raises HTTP 409. The frontend hook flips state to `displaced` and disables playback controls until the user explicitly takes over again. While paused, the validate ping lets a displaced tab notice without waiting for the next progress write.

### Home rows

The stations page renders two horizontal rails above the stations grid:

- **Continue listening** — `GET /api/player/in-progress` returns incomplete episodes with enough saved duration and remaining playback time to resume.
- **Recently Completed** — `GET /api/player/recent-completed` returns completed episodes ordered by last playback.

The two filters are mutually exclusive, so an episode should not appear in both.

## Tests

`cargo test` runs unit tests beside the code:

- Pure functions: sidecar parsing and chapter normalization (`show_metadata.rs`), summary prefix and chapter-file parsing (`summaries.rs`), month ranges (`shows.rs`), token/`next` helpers (`auth.rs`), error rendering (`error.rs`), the CLI definition (`cli.rs`).
- S3 logic against `aws-smithy-mocks` clients (`summaries.rs`).
- Router tests through `tower::ServiceExt::oneshot` with a lazy, never-connecting pool (`test_support.rs`): login cookie flow, bearer/cookie auth, 401/redirect behaviour, validation 422s, missing session tokens.

There are no automated tests against a real Postgres or bucket.

## Deployment

The Dockerfile builds the release binary (frontend embedded) in a Rust image with Bun, then copies it into a `debian:trixie-slim` runtime with `tini`. `ENTRYPOINT` is `tini --` and `CMD` is `s3player server`, with `SERVER_HOST=0.0.0.0`. The `runtime-prebuilt` target wraps a binary built outside Docker (used by the release workflow); the `export` target extracts binaries (`docker-bake.hcl`, `build-docker.sh`).

CI (`.github/workflows/ci.yml`) runs clippy, tests, a CLI smoke test, and the frontend lint/typecheck/build. The release workflow (`release.yml`) builds the frontend once, embeds it into Linux and macOS binaries via `S3PLAYER_PREBUILT_FRONTEND`, publishes a GitHub release, and pushes multi-arch images. There is no automated indexer run; `s3player index` is invoked manually or by an out-of-band scheduler when new files land in S3.
