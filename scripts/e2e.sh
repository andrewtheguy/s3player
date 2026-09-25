#!/usr/bin/env bash

# End-to-end tests: runs the real `s3player` binary (`index` and `server`)
# against a Silo S3 server and a throwaway Postgres, then tears both down.
#
#   ./scripts/e2e.sh                 # whole suite (tests/e2e.rs)
#   ./scripts/e2e.sh player          # only tests whose name contains "player"
#   ./scripts/e2e.sh --coverage      # unit + e2e under cargo-llvm-cov, one report
#
# Silo (https://github.com/pgsty/silo) is a MinIO fork: one binary, a data
# directory, and root credentials in the environment. Its configuration and
# health surfaces are still MinIO's, hence the `MINIO_*` variables and the
# `/minio/health/live` probe. It is downloaded once into tmp/tools and
# checksum-verified.
#
# Postgres comes from a `postgres:17-alpine` container (podman, else docker),
# unless S3PLAYER_E2E_DATABASE_URL already points at a server whose user may
# CREATE DATABASE: every test creates and drops its own database, and uses
# its own bucket, so tests run in parallel and leave nothing behind.
#
# Environment: SILO_S3_PORT (default 9400), E2E_PG_PORT (default 55432),
# SILO_BIN (an existing Silo binary), S3PLAYER_E2E_DATABASE_URL.

set -euo pipefail

coverage=false
if [[ "${1:-}" == "--coverage" ]]; then
    coverage=true
    shift
    command -v cargo-llvm-cov >/dev/null 2>&1 ||
        { printf '[e2e] ERROR: cargo-llvm-cov is required for --coverage\n' >&2; exit 1; }
fi

SILO_RELEASE="RELEASE.2026-09-16T00-00-00Z"
SILO_VERSION="20260916000000.0.0"
# SHA-256 of the official linux archives for the release above.
SILO_SHA256_AMD64="381e745510a8fb64323d7bb3207f95984b7f4ed826f4fcad318f97683c420c73"
SILO_SHA256_ARM64="6e697d3e1d70f2343fe829cd6820a0b840d4619f1dde546424de80e529636ed2"
SILO_ACCESS_KEY="s3player-e2e"
SILO_SECRET_KEY="s3player-e2e-secret"
SILO_REGION="us-east-1"
SILO_S3_PORT="${SILO_S3_PORT:-9400}"
E2E_PG_PORT="${E2E_PG_PORT:-55432}"
PG_IMAGE="docker.io/library/postgres:17-alpine"

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime="${project_root}/tmp/e2e"
silo_binary="${SILO_BIN:-${project_root}/tmp/tools/silo-${SILO_VERSION}}"
pg_container="s3player-e2e-$$"

info() {
    printf '[e2e] %s\n' "$*"
}

fail() {
    printf '[e2e] ERROR: %s\n' "$*" >&2
    exit 1
}

for port in "$SILO_S3_PORT" "$E2E_PG_PORT"; do
    [[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )) ||
        fail "ports must be integers from 1 through 65535"
done

download_silo() {
    local arch expected_sha256 actual_sha256 archive
    [[ "$(uname -s)" == "Linux" ]] || fail "set SILO_BIN to a Silo ${SILO_RELEASE} binary"
    case "$(uname -m)" in
        x86_64) arch="amd64"; expected_sha256="$SILO_SHA256_AMD64" ;;
        aarch64 | arm64) arch="arm64"; expected_sha256="$SILO_SHA256_ARM64" ;;
        *) fail "set SILO_BIN to a Silo ${SILO_RELEASE} binary" ;;
    esac
    mkdir -p "$(dirname "$silo_binary")"
    archive="${silo_binary}.tar.gz"
    info "downloading Silo ${SILO_RELEASE} (linux/${arch})"
    curl --fail --location --silent --show-error --output "$archive" \
        "https://github.com/pgsty/silo/releases/download/${SILO_RELEASE}/silo_${SILO_VERSION}_linux_${arch}.tar.gz"
    actual_sha256="$(sha256sum "$archive" | awk '{ print $1 }')"
    if [[ "$actual_sha256" != "$expected_sha256" ]]; then
        rm -f "$archive"
        fail "Silo checksum mismatch: expected ${expected_sha256}, got ${actual_sha256}"
    fi
    # The archive carries the server as a bare `silo` at its root.
    tar -xzf "$archive" -O silo >"${silo_binary}.download"
    rm -f "$archive"
    chmod +x "${silo_binary}.download"
    mv "${silo_binary}.download" "$silo_binary"
}

wait_for() {
    local what="$1"
    shift
    for _ in $(seq 1 60); do
        if "$@" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    fail "${what} did not become ready"
}

silo_pid=""
container_runtime=""

cleanup() {
    if [[ -n "$silo_pid" ]]; then
        kill "$silo_pid" 2>/dev/null || true
        wait "$silo_pid" 2>/dev/null || true
    fi
    if [[ -n "$container_runtime" ]]; then
        "$container_runtime" rm --force "$pg_container" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

[[ -x "$silo_binary" ]] || download_silo

# A fresh data directory per run; this path is disposable, under tmp/.
rm -rf "$runtime"
mkdir -p "${runtime}/silo-data"

info "starting Silo on 127.0.0.1:${SILO_S3_PORT} (log: tmp/e2e/silo.log)"
MINIO_ROOT_USER="$SILO_ACCESS_KEY" \
    MINIO_ROOT_PASSWORD="$SILO_SECRET_KEY" \
    MINIO_REGION="$SILO_REGION" \
    "$silo_binary" server "${runtime}/silo-data" \
    --address "127.0.0.1:${SILO_S3_PORT}" --quiet >"${runtime}/silo.log" 2>&1 &
silo_pid=$!
wait_for "Silo" curl --fail --silent --output /dev/null \
    "http://127.0.0.1:${SILO_S3_PORT}/minio/health/live"

database_url="${S3PLAYER_E2E_DATABASE_URL:-}"
if [[ -z "$database_url" ]]; then
    if command -v podman >/dev/null 2>&1; then
        container_runtime="podman"
    elif command -v docker >/dev/null 2>&1; then
        container_runtime="docker"
    else
        fail "podman or docker is required, or set S3PLAYER_E2E_DATABASE_URL"
    fi
    info "starting Postgres (${PG_IMAGE}) on 127.0.0.1:${E2E_PG_PORT} via ${container_runtime}"
    "$container_runtime" run --detach --rm --name "$pg_container" \
        --env POSTGRES_PASSWORD=e2e \
        --publish "127.0.0.1:${E2E_PG_PORT}:5432" \
        "$PG_IMAGE" >/dev/null
    # pg_isready over TCP: the image's init phase serves only the unix socket.
    wait_for "Postgres" "$container_runtime" exec "$pg_container" \
        pg_isready --host 127.0.0.1 --username postgres
    database_url="postgres://postgres:e2e@127.0.0.1:${E2E_PG_PORT}/postgres"
fi

export S3PLAYER_E2E_S3_ENDPOINT="http://127.0.0.1:${SILO_S3_PORT}"
export S3PLAYER_E2E_S3_ACCESS_KEY_ID="$SILO_ACCESS_KEY"
export S3PLAYER_E2E_S3_SECRET_ACCESS_KEY="$SILO_SECRET_KEY"
export S3PLAYER_E2E_S3_REGION="$SILO_REGION"
export S3PLAYER_E2E_DATABASE_URL="$database_url"
cd "$project_root"

if [[ "$coverage" == true ]]; then
    # The e2e tests spawn the instrumented binary, so its runs count too.
    info "running unit and e2e tests under cargo-llvm-cov"
    cargo llvm-cov clean --workspace
    cargo llvm-cov --no-report
    cargo llvm-cov --no-report --test e2e -- --ignored "$@"
    cargo llvm-cov report --summary-only
    cargo llvm-cov report --html --output-dir tmp/coverage
    info "HTML report: tmp/coverage/html/index.html"
else
    info "running tests/e2e.rs"
    cargo test --test e2e -- --ignored "$@"
fi
info "end-to-end tests passed"
