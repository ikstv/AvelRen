#!/usr/bin/env bash
# Only disposable Docker resources; Windows uses the same Linux controller as CI.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test -f "$ROOT/ops/collector-runtime-daemon-test.py" || { echo 'runtime acceptance driver missing' >&2; exit 1; }
SOURCE=$(git -C "$ROOT" rev-parse HEAD)
TAG="avelren-runtime-test-controller-${RANDOM}-${RANDOM}"
mkdir -p "$ROOT/dist"
ROOT_DOCKER=$ROOT
if command -v cygpath >/dev/null 2>&1; then ROOT_DOCKER=$(cygpath -w "$ROOT"); fi
export MSYS_NO_PATHCONV=1
docker build -t "$TAG" -f "$ROOT_DOCKER/ops/Dockerfile.collector-runtime-test-controller" "$ROOT_DOCKER/ops"
docker run --rm --name "$TAG" --network none \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$ROOT_DOCKER:/work:ro" -v "$ROOT_DOCKER/dist:/evidence" \
  "$TAG" python3 /work/ops/collector-runtime-daemon-test.py --source-commit "$SOURCE"
