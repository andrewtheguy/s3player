# s3player

## Backend

```
uv sync
uv run s3player server  # serves on http://127.0.0.1:8000
uv run s3player index   # one-shot S3 → Postgres indexer
```

API docs at `http://127.0.0.1:8000/docs` (also proxied through the dev server at `http://localhost:5173/docs`).

## Frontend

```
cd frontend
bun install             # first time only
bun run dev             # serves on http://localhost:5173, proxies /api → :8000
```
