# --- Frontend builder: bun + vite -> /build/frontend/dist ---
FROM oven/bun:1.3-alpine AS frontend-builder
WORKDIR /build/frontend

COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

COPY frontend/ ./
RUN bun run build

# --- Backend builder: install Python deps into /usr/local/ ---
FROM python:3.12-slim-bookworm AS backend-builder

RUN apt-get -yqq update && \
    apt-get install -yq --no-install-recommends ca-certificates && \
    apt-get clean -y && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY pyproject.toml uv.lock README.md ./
COPY app ./app

ENV UV_PROJECT_ENVIRONMENT=/usr/local/
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.8,source=/uv,target=/uv \
    /uv sync --locked --no-dev

# --- Runtime: minimal image with backend + built frontend ---
FROM python:3.12-slim-bookworm

RUN apt-get -yqq update && \
    apt-get install -yq --no-install-recommends ca-certificates tini && \
    apt-get clean -y && rm -rf /var/lib/apt/lists/*

COPY --from=backend-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=backend-builder /usr/local/bin/s3player /usr/local/bin/s3player

WORKDIR /usr/src/app
COPY app ./app
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
