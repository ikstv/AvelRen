#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
PROJECT="avelren-caddy-test-${RANDOM}-${RANDOM}"
ROOT_DOCKER=$ROOT
WORK_DOCKER=$WORK
if command -v cygpath >/dev/null 2>&1; then
    ROOT_DOCKER=$(cygpath -w "$ROOT")
    WORK_DOCKER=$(cygpath -w "$WORK")
fi
docker_cmd() { MSYS_NO_PATHCONV=1 docker "$@"; }
cleanup() {
    local status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then docker_cmd logs "$PROJECT-caddy" 2>&1 || true; fi
    docker_cmd rm -f -v "$PROJECT-caddy" "$PROJECT-api" >/dev/null 2>&1 || true
    docker_cmd network rm "$PROJECT" >/dev/null 2>&1 || true
    # Only files created in this invocation; no recursive directory deletion.
    rm -f -- "$WORK/Caddyfile"
    rmdir -- "$WORK"
    exit "$status"
}
trap cleanup EXIT
CADDY_IMAGE=$(awk '/^  caddy:/ {found=1; next} found && /image:/ {print $2; exit}' "$ROOT/docker-compose.yml")
PYTHON_IMAGE=$(awk '/^FROM / {print $2; exit}' "$ROOT/ops/Dockerfile.database-test")
[[ "$CADDY_IMAGE" == caddy:*@sha256:* ]] || { echo 'Pinned Caddy image missing' >&2; exit 1; }
[[ "$PYTHON_IMAGE" == python:*@sha256:* ]] || { echo 'Pinned Python image missing' >&2; exit 1; }
# Pull public images before creating a network with no external connectivity.
docker_cmd pull "$CADDY_IMAGE"
docker_cmd pull "$PYTHON_IMAGE"
docker_cmd run --rm --network none \
    -v "$ROOT_DOCKER/ops/Caddyfile:/etc/caddy/Caddyfile:ro" \
    "$CADDY_IMAGE" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
# Keep the canonical routes intact; only replace certificate issuance in tests.
sed '/^https:\/\/api.bordersignal.pp.ua {/a\
    tls internal' "$ROOT/ops/Caddyfile" >"$WORK/Caddyfile"
docker_cmd network create --internal "$PROJECT" >/dev/null
docker_cmd run -d --name "$PROJECT-api" --network "$PROJECT" --network-alias api \
    --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true \
    -v "$ROOT_DOCKER:/workspace:ro" "$PYTHON_IMAGE" \
    python /workspace/ops/caddy-routing-test.py server >/dev/null
docker_cmd run -d --name "$PROJECT-caddy" --network "$PROJECT" \
    --network-alias api.bordersignal.pp.ua \
    -v "$WORK_DOCKER/Caddyfile:/etc/caddy/Caddyfile:ro" \
    -v "$ROOT_DOCKER/ops/static:/srv/static:ro" "$CADDY_IMAGE" >/dev/null
docker_cmd run --rm --network "$PROJECT" --user 10001:10001 \
    --cap-drop ALL --security-opt no-new-privileges:true \
    -v "$ROOT_DOCKER:/workspace:ro" "$PYTHON_IMAGE" \
    python /workspace/ops/caddy-routing-test.py
# The stub container is a second client with a different address.
docker_cmd exec "$PROJECT-api" python /workspace/ops/caddy-routing-test.py
