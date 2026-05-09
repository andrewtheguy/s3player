# AI Agent Instructions

No backward compatibility or migration path for simplicity because it is a private and internal project.

use `uv` to run all python commands

## Project layout

- Backend: FastAPI app at repo root (`app/`, entrypoint `app.server:app`, CLI dispatcher `app.cli:main` exposed as `s3player` with `server` and `index` subcommands).
- Frontend: Vite + React + TypeScript in `frontend/`. Package manager: `bun`.

## Validation commands

Run these before reporting a task complete. All four must exit clean.

### Backend (run from repo root)

```
uv run ruff check          # lint
uv run ruff format --check # format check (use `uv run ruff format` to apply)
uv run basedpyright        # type check
```

To auto-fix lint issues: `uv run ruff check --fix`.

### Frontend (run from `frontend/`)

```
bun run lint       # biome check (lint + format + import sort)
bun run typecheck  # tsc -b
```

To auto-fix lint/format/import issues: `bun run lint:fix`.

## Dev servers

Don't run by default, but if you do need to run, use these commands from the repo root:

```
uv run s3player server                # backend on :8000
uv run s3player index                 # one-shot S3 → Postgres indexer (no server)
cd frontend && bun run dev            # frontend on :5173 (proxies /api → :8000)
```

## Conventions

- Python target: 3.12.
- Configs live in `pyproject.toml` (`[tool.ruff]`, `[tool.basedpyright]`) and `frontend/biome.json`.
