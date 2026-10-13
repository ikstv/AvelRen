#!/usr/bin/env bash
# Real local daemon/coordinator/jobs/crypt/restore; no external HTTP transport.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test -f "$ROOT/ops/paired-backup-daemon-test.py" || { echo paired_daemon_acceptance_missing >&2; exit 1; }
SOURCE=$(git -C "$ROOT" rev-parse HEAD)
PREFIX="avelren-runtime-test-pair-${RANDOM}-${RANDOM}"
ROOT_DOCKER=$ROOT
if command -v cygpath >/dev/null 2>&1; then ROOT_DOCKER=$(cygpath -w "$ROOT"); fi
export MSYS_NO_PATHCONV=1
CONTROLLER=${AVELREN_PAIRED_TEST_CONTROLLER:-}
BUILT=0
LOCAL_BASE=()
if [ -z "$CONTROLLER" ]; then
  CONTROLLER="$PREFIX-controller"
  docker build -t "$CONTROLLER" -f "$ROOT_DOCKER/ops/Dockerfile.collector-runtime-test-controller" "$ROOT_DOCKER/ops"
  BUILT=1
else
  [[ "$CONTROLLER" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
  LOCAL_BASE=(--local-base)
fi
VOLUME="$PREFIX-controller-data"
if docker container inspect "$PREFIX-controller" >/dev/null 2>&1 || docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo fixture_resource_already_exists >&2
  exit 2
fi
docker volume create "$VOLUME" >/dev/null
MOUNT=$(docker volume inspect "$VOLUME" --format '{{.Mountpoint}}')
cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  docker rm -f "$PREFIX-controller" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null || status=1
  if [ "$BUILT" = 1 ]; then docker image rm "$CONTROLLER" >/dev/null || status=1; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$ROOT/dist"
docker run --rm --name "$PREFIX-controller" --network none \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$ROOT_DOCKER:/work:ro" -v "$ROOT_DOCKER/dist:/evidence" \
  -v "$VOLUME:$MOUNT" "$CONTROLLER" \
  python3 /work/ops/paired-backup-daemon-test.py --source-commit "$SOURCE" --fixture "$MOUNT" --prefix "$PREFIX" "${LOCAL_BASE[@]}"
