# CLAUDE.md

Instructions for Claude Code when working in this repo.

## Project layout

- Backend: FastAPI app at repo root (`app/`, entrypoint `app.main:app`, runner `s3player`).
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
uv run s3player                       # backend on :8000
cd frontend && bun run dev            # frontend on :5173 (proxies /api → :8000)
```

## Conventions

- Python target: 3.12. Ruff `line-length = 100`.
- Frontend formatter (biome): 2-space indent, single quotes, no semicolons. Match this when editing `.ts`/`.tsx`.
- `noNonNullAssertion` is intentionally disabled in biome — leaving the React 18+ `getElementById('root')!` entrypoint pattern alone.
- Configs live in `pyproject.toml` (`[tool.ruff]`, `[tool.basedpyright]`) and `frontend/biome.json`.
