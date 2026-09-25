# AI Agent Instructions

No backward compatibility or migration path for simplicity because it is a private and internal project.

## Project layout

- Backend: Rust (axum + sqlx + aws-sdk-s3) at the repo root (`src/`), one binary `s3player` with `server` and `index` subcommands. Release builds embed the frontend (`build.rs` → `src/assets.rs`).
- Frontend: Vite + React + TypeScript in `frontend/`. Package manager: `bun`.
- Architectural doc is in `docs/architecture.md`.

## Validation commands

Run these before reporting a task complete. All must exit clean.

### Backend (run from repo root)

```
cargo clippy --all-targets -- -D warnings
cargo test
```

No `cargo fmt`.

### Frontend (run from `frontend/`)

```
bun run lint       # biome check (lint + format + import sort)
bun run typecheck  # tsc -b
```

To auto-fix lint/format/import issues: `bun run lint:fix`.

## Dev servers

Don't run by default, but if you do need to run, use these commands from the repo root:

```
cargo run -- server                   # backend on :8000 (dev builds don't embed the UI)
cargo run -- index                    # one-shot S3 → Postgres indexer (no server)
cd frontend && bun run dev            # frontend on :5173 (proxies /api and /login → :8000)
```

## Conventions

- Error handling: `anyhow` for application errors (main, indexer, S3 helpers), `thiserror` for the typed API error (`AppError` in `src/error.rs`), which always renders `{"detail": "..."}`; internal/upstream errors return a generic detail to clients and log the chain.
- Use the async Rust APIs by default.
- Use `tmp/` for temporary files (gitignored).
