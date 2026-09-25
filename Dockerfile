# Build stage
FROM rust:1.91-slim-trixie AS builder
ARG TARGETARCH

# Install build dependencies and bun
RUN apt-get update && apt-get install -y \
    build-essential \
    clang \
    mold \
    pkg-config \
    curl \
    unzip \
    && curl -fsSL https://bun.sh/install | bash \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.bun/bin:${PATH}"

WORKDIR /build

COPY . .

RUN cd frontend && bun install --frozen-lockfile

# Build the release binary (build.rs builds and embeds the frontend) with architecture-specific cache mounts
RUN --mount=type=cache,target=/usr/local/cargo/registry,id=cargo-registry-v2-${TARGETARCH} \
    --mount=type=cache,target=/build/target,id=cargo-target-v2-${TARGETARCH} \
    cargo build --release --locked && \
    cp target/release/s3player /s3player

# Export stage - for extracting standalone binaries (used by docker-bake.hcl)
FROM scratch AS export
COPY --from=builder /s3player /s3player

# Runtime stage - minimal image for container deployment (builds from source)
FROM debian:trixie-slim AS runtime

LABEL org.opencontainers.image.source=https://github.com/andrewtheguy/s3player

RUN apt-get update && apt-get install -y \
    ca-certificates \
    tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /s3player /usr/local/bin/s3player

# Containers need to listen on all interfaces by default; both are overridable
# at run time (env or `--host`/`--port`).
ENV SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["s3player", "server"]

# Runtime stage for pre-built binary (used by CI to avoid double build)
FROM debian:trixie-slim AS runtime-prebuilt

LABEL org.opencontainers.image.source=https://github.com/andrewtheguy/s3player

RUN apt-get update && apt-get install -y \
    ca-certificates \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Binary must be passed via build context
COPY s3player /usr/local/bin/s3player

ENV SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["s3player", "server"]
