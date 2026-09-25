# s3player

A password-gated player for S3-hosted radio recordings. Episodes are indexed
from S3 — the indexer treats `{audio_key}.metadata.json` sidecar files as the
anchor (skipping any whose audio file is missing) and reads chapter info from
those sidecars. Playback position is persisted to Postgres so reloading or
returning later resumes where you left off. Only one tab/device can be in
active player mode at a time — opening a new player displaces the previous
one.

It ships as a single Rust binary with the React frontend embedded.

## Configuration

Every setting is read from the environment (a `.env` in the working directory
works) or the matching command-line flag (`s3player server --help`):

| Variable                | Purpose                                |
| ----------------------- | -------------------------------------- |
| `S3_ENDPOINT`           | S3-compatible endpoint URL             |
| `S3_BUCKET`             | Bucket containing the recordings       |
| `S3_REGION`             | Region for the S3 client               |
| `S3_ACCESS_KEY_ID`      | S3 access key                          |
| `S3_SECRET_ACCESS_KEY`  | S3 secret key                          |
| `DATABASE_URL`          | Postgres URL (`postgres://…`)          |
| `SITE_PASSWORD`         | Single password protecting the app (`server` only) |
| `SERVER_HOST`           | Bind address (default `127.0.0.1`)     |
| `SERVER_PORT`           | Bind port (default `8000`)             |
| `RUST_LOG`              | Log filter (default `info`)            |

S3 requests use path-style addressing.

For Postgres you can either set `DATABASE_URL` directly or supply the discrete
pieces (useful when injecting from a Kubernetes ConfigMap/Secret); if
`DATABASE_URL` is unset or empty, all five of the following are required:

| Variable            | Purpose                       |
| ------------------- | ----------------------------- |
| `POSTGRES_HOST`     | Postgres host                 |
| `POSTGRES_PORT`     | Postgres port                 |
| `POSTGRES_USER`     | Postgres user                 |
| `POSTGRES_PASSWORD` | Postgres password             |
| `POSTGRES_DATABASE` | Postgres database name        |

Both subcommands create the tables on startup; there is no separate migration
step. Run the indexer to populate `shows` and `episodes` from S3.

## Usage

```
s3player server                 # serves on http://127.0.0.1:8000
s3player index                  # one-shot S3 → Postgres indexer
s3player index --overwrite      # also rewrite already-indexed episodes from their sidecars
```

The Docker image defaults `SERVER_HOST=0.0.0.0` so the container is reachable;
its command is `s3player server`, overridable at run time (e.g. `s3player index`).

## Development

Requires Rust, [Bun](https://bun.sh), and `clang` + `mold` (see
`.cargo/config.toml`).

```
cd frontend && bun install      # first time only
cargo run -- server             # backend on :8000
cd frontend && bun run dev      # UI on http://localhost:5173, proxies /api and /login → :8000
```

Dev builds do not embed the UI; open the Vite dev server instead. `cargo build
--release` runs `bun run build` from `build.rs` and embeds the result
(`S3PLAYER_EMBED_FRONTEND=1` forces that in a dev build;
`S3PLAYER_PREBUILT_FRONTEND=<dir>` embeds an already-built bundle).

Checks: `cargo clippy --all-targets -- -D warnings`, `cargo test`, and in
`frontend/` `bun run lint` and `bun run typecheck`.

End-to-end tests (`tests/e2e.rs`) run the real binary against a
[Silo](https://github.com/pgsty/silo) S3 server and Postgres:

```
./scripts/e2e.sh                # needs podman or docker for Postgres
./scripts/e2e.sh player         # only tests matching "player"
./scripts/e2e.sh --coverage     # unit + e2e coverage report (cargo-llvm-cov)
```

The script downloads Silo into `tmp/tools`, starts it and a throwaway
Postgres container, and tears both down afterwards. Set
`S3PLAYER_E2E_DATABASE_URL` to use an existing Postgres instead (its user
must be able to create databases).

## Releases

Releases are cut manually: bump `version` in `Cargo.toml`, merge to `main`,
then run the **Release** workflow (`.github/workflows/release.yml`) from the
Actions tab. It derives the tag from `Cargo.toml` (`0.0.1` → `v0.0.1`), builds
the frontend once, builds Linux (x86_64, arm64) and macOS (arm64) binaries,
publishes them as a GitHub release, and pushes multi-arch images to
`ghcr.io/andrewtheguy/s3player`. Dispatching from a branch other than `main`
marks the release as a prerelease and skips the `latest` image tag.

`./build-docker.sh` builds both Linux binaries locally via Docker into `tmp/`.

## Auth

Visit `/login` and enter `SITE_PASSWORD`. An HMAC token is set as the
`s3player_auth` httponly browser-session cookie. All `/api/*` endpoints except
`/api/auth/login` require the cookie (or `Authorization: Bearer <token>`, with
the token from `POST /api/auth/login`); UI routes redirect to `/login?next=…`
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
  before the end) and *Recently Completed* (history). Both are hidden when
  empty.
