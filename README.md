# s3player

A password-gated player for S3-hosted radio recordings. Episodes are indexed
from S3, chapters extracted via `ffprobe`, and playback position is persisted
to Postgres so reloading or returning later resumes where you left off. Only
one tab/device can be in active player mode at a time — opening a new player
displaces the previous one.

## Configuration

Backend reads from environment (a `.env` at the repo root works):

| Variable                | Purpose                                |
| ----------------------- | -------------------------------------- |
| `S3_ENDPOINT`           | S3-compatible endpoint URL             |
| `S3_BUCKET`             | Bucket containing the recordings       |
| `S3_REGION`             | Region for the S3 client               |
| `S3_ACCESS_KEY_ID`      | S3 access key                          |
| `S3_SECRET_ACCESS_KEY`  | S3 secret key                          |
| `DATABASE_URL`          | Postgres URL (`postgres://…`)          |
| `SITE_PASSWORD`         | Single password protecting the app     |

For Postgres you can either set `DATABASE_URL` directly or supply the discrete
pieces (useful when injecting from a Kubernetes ConfigMap/Secret); if
`DATABASE_URL` is unset, all five of the following are required and a DSN is
built from them:

| Variable            | Purpose                       |
| ------------------- | ----------------------------- |
| `POSTGRES_HOST`     | Postgres host                 |
| `POSTGRES_PORT`     | Postgres port                 |
| `POSTGRES_USER`     | Postgres user                 |
| `POSTGRES_PASSWORD` | Postgres password             |
| `POSTGRES_DATABASE` | Postgres database name        |

The server creates its tables on startup; no separate migration step. Run the
indexer once to populate `shows` and `episodes` from S3.

## Backend

```
uv sync
uv run s3player server  # serves on http://127.0.0.1:8000
uv run s3player index   # one-shot S3 → Postgres indexer
```

API docs at `http://127.0.0.1:8000/docs` (also proxied through the dev server
at `http://localhost:5173/docs`).

## Frontend

```
cd frontend
bun install             # first time only
bun run dev             # serves on http://localhost:5173, proxies /api → :8000
```

## Auth

Visit `/login` and enter `SITE_PASSWORD`. An HMAC token is set as the
`s3player_auth` httponly browser-session cookie. All `/api/*` endpoints except
`/api/auth/login` require the cookie; UI routes redirect to `/login?next=…`
and the SPA redirects there automatically on a 401.

## Player behaviour

- **Resume**: every ~10s while playing (and on pause / ended) the player
  POSTs the current position to `/api/player/episodes/{id}/progress`. On
  reload, the saved position is fetched and applied once audio metadata is
  ready.
- **Single session (global)**: opening a player page is read-only and does
  not claim the active player session. The user must explicitly choose
  *Take over playback*, which claims a session token via
  `/api/player/session/claim`. The token is held in memory in the tab and
  sent as `X-Player-Session` on every write. A new claim displaces the
  previous one; the displaced tab pauses on its next write or validate-ping
  and disables playback controls until the user explicitly takes over again.
- **Home page** (`/stations`) shows two rows above the stations grid:
  *Continue listening* (in-progress, not completed, position more than 30s
  before the end) and *Recently played* (history). Both are hidden when
  empty.
