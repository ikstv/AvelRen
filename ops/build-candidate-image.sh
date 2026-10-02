#!/usr/bin/env bash
# Build and attest one local, non-deployed backend candidate image.
#
# This script never invokes compose, pushes an image or contacts production.
# Its JSON stdout is suitable for the candidate_images section of the separate
# sanitised deployment evidence record.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REPOSITORY=${AVELREN_CANDIDATE_REPOSITORY:-avelren-candidate}

usage() {
    echo "usage: $0" >&2
    exit 64
}

[ "$#" -eq 0 ] || usage

branch=$(git -C "$ROOT" branch --show-current)
if [ "$branch" != "main" ]; then
    echo "candidate build refused: build only from a clean main branch" >&2
    exit 65
fi
commit=$(git -C "$ROOT" rev-parse HEAD)
if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "candidate build refused: HEAD is not a 40-character lowercase Git SHA" >&2
    exit 65
fi
if ! git -C "$ROOT" diff --quiet; then
    echo "candidate build refused: tracked source changes are present" >&2
    exit 66
fi
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    echo "candidate build refused: source tree is not clean" >&2
    exit 66
fi

image="$REPOSITORY:$commit"
docker build \
    --build-arg "SOURCE_COMMIT=$commit" \
    --tag "$image" \
    "$ROOT/services/backend"

image_id=$(docker image inspect --format '{{.Id}}' "$image")
if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "candidate build refused: Docker did not return an immutable image ID" >&2
    exit 67
fi

embedded_commit=$(docker run --rm --network none --entrypoint python "$image" -c \
    'import os; print(os.environ.get("AVELREN_GIT_SHA", ""))')
if [ "$embedded_commit" != "$commit" ]; then
    echo "candidate build refused: image AVELREN_GIT_SHA does not match HEAD" >&2
    exit 68
fi

# Source-mounted tests cannot prove that package data reached the wheel.
# Verify the installed model in the actual candidate, without source or network.
docker run --rm -i --network none --entrypoint python "$image" - \
    < "$ROOT/ops/verify-installed-model.py" >/dev/null

printf '{"source_commit":"%s","image_ref":"%s","image_digest":"%s"}\n' \
    "$commit" "$image" "$image_id"
