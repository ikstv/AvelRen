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
STARTED=0
VOLUME_CREATED=0
VOLUME="$PREFIX-controller-data"
LOCAL_BASE=()
cleanup() {
  local status=$?
  trap - EXIT
  trap '' HUP INT TERM
  if [ "$STARTED" = 1 ]; then
    if docker container inspect "$PREFIX-controller" >/dev/null 2>&1; then
      if [ "$(docker container inspect "$PREFIX-controller" --format '{{index .Config.Labels "org.avelren.test.fixture"}}')" != "$PREFIX" ]; then
        echo fixture_controller_ownership_unproven >&2
        [ "$status" != 0 ] || status=1
        exit "$status"
      fi
      # TERM enters Python finally; never force-remove its sibling owner first.
      timeout 190 docker stop --time 180 "$PREFIX-controller" >/dev/null 2>&1 || true
    fi
    if ! timeout 20 docker run --rm --network none -v "$VOLUME:/fixture:ro" "$CONTROLLER" \
      python3 -c 'import json,sys;v=json.load(open("/fixture/cleanup.json"));assert v["fixture"]==sys.argv[1] and v["status"]=="PASS"' "$PREFIX"; then
      [ "$status" != 0 ] || status=1
      # An unresponsive owner is terminated only before an independent reader
      # uses its private durable ledger and exact resource ownership labels.
      timeout 15 docker kill "$PREFIX-controller" >/dev/null 2>&1 || true
      timeout 15 docker rm "$PREFIX-controller" >/dev/null 2>&1 || true
      if ! timeout 170 docker run --rm --network none \
        -v /var/run/docker.sock:/var/run/docker.sock -v "$ROOT_DOCKER:/work:ro" \
        -v "$ROOT_DOCKER/dist:/evidence" -v "$VOLUME:$MOUNT" "$CONTROLLER" \
        python3 /work/ops/paired-backup-daemon-test.py --cleanup-only \
        --source-commit "$SOURCE" --fixture "$MOUNT" --prefix "$PREFIX"; then
        echo "fixture_cleanup_unproven: preserve $VOLUME and dist/paired-backup-cleanup-$PREFIX.json" >&2
        exit "$status"
      fi
    fi
    timeout 15 docker rm "$PREFIX-controller" >/dev/null 2>&1 || true
  fi
  if [ "$VOLUME_CREATED" = 1 ]; then timeout 15 docker volume rm "$VOLUME" >/dev/null || status=1; fi
  if [ "$BUILT" = 1 ]; then timeout 15 docker image rm "$CONTROLLER" >/dev/null || status=1; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
if [ -z "$CONTROLLER" ]; then
  CONTROLLER="$PREFIX-controller"
  BUILT=1
  docker build -t "$CONTROLLER" -f "$ROOT_DOCKER/ops/Dockerfile.collector-runtime-test-controller" "$ROOT_DOCKER/ops"
else
  [[ "$CONTROLLER" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
  LOCAL_BASE=(--local-base)
fi
if docker container inspect "$PREFIX-controller" >/dev/null 2>&1 || docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo fixture_resource_already_exists >&2
  exit 2
fi
VOLUME_CREATED=1
docker volume create --label "org.avelren.test.fixture=$PREFIX" "$VOLUME" >/dev/null
MOUNT=$(docker volume inspect "$VOLUME" --format '{{.Mountpoint}}')
mkdir -p "$ROOT/dist"
STARTED=1
docker run --rm --name "$PREFIX-controller" --network none \
  --label "org.avelren.test.fixture=$PREFIX" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$ROOT_DOCKER:/work:ro" -v "$ROOT_DOCKER/dist:/evidence" \
  -v "$VOLUME:$MOUNT" "$CONTROLLER" \
  python3 /work/ops/paired-backup-daemon-test.py --source-commit "$SOURCE" --fixture "$MOUNT" --prefix "$PREFIX" "${LOCAL_BASE[@]}" &
RUN_PID=$!
wait "$RUN_PID"
