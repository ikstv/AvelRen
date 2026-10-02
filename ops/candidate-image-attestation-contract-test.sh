#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
COMMIT=1234567890abcdef1234567890abcdef12345678
IMAGE_ID=sha256:abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd
PYTHON_BIN=${PYTHON_BIN:-python3}

cat >"$WORK/bin/git" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${*: -2}" in
  'branch --show-current') echo main ;;
  'rev-parse HEAD') echo "$FAKE_COMMIT" ;;
  'diff --quiet') exit 0 ;;
  'status --porcelain') [ "${FAKE_GIT_DIRTY:-0}" = 1 ] && echo ' M changed.py' ;;
  *) echo "unexpected fake git arguments: $*" >&2; exit 97 ;;
esac
SH

cat >"$WORK/bin/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"
case "$1 $2" in
  'build --build-arg') exit 0 ;;
  'image inspect') echo "$FAKE_IMAGE_ID" ;;
  'run --rm')
    if [ "${*: -1}" = '-' ]; then
      cat >/dev/null
      [ "${FAKE_MODEL_MISSING:-0}" != 1 ] || exit 69
    else
      echo "${FAKE_EMBEDDED_COMMIT:-$FAKE_COMMIT}"
    fi
    ;;
  *) echo "unexpected fake docker arguments: $*" >&2; exit 98 ;;
esac
SH
chmod +x "$WORK/bin/git" "$WORK/bin/docker"

run() {
  PATH="$WORK/bin:$PATH" FAKE_COMMIT="$COMMIT" FAKE_IMAGE_ID="$IMAGE_ID" \
    FAKE_DOCKER_LOG="$WORK/docker.log" bash "$ROOT/ops/build-candidate-image.sh"
}

output=$(run)
"$PYTHON_BIN" - "$output" "$COMMIT" "$IMAGE_ID" <<'PY'
import json
import sys

record = json.loads(sys.argv[1])
assert record == {
    "source_commit": sys.argv[2],
    "image_ref": f"avelren-candidate:{sys.argv[2]}",
    "image_digest": sys.argv[3],
}
PY
grep -Fx -- "build --build-arg SOURCE_COMMIT=$COMMIT --tag avelren-candidate:$COMMIT $ROOT/services/backend" "$WORK/docker.log"
grep -Fx -- "run --rm --network none --entrypoint python avelren-candidate:$COMMIT -c import os; print(os.environ.get(\"AVELREN_GIT_SHA\", \"\"))" "$WORK/docker.log"

if PATH="$WORK/bin:$PATH" FAKE_COMMIT="$COMMIT" FAKE_IMAGE_ID="$IMAGE_ID" \
  FAKE_DOCKER_LOG="$WORK/dirty.log" FAKE_GIT_DIRTY=1 bash "$ROOT/ops/build-candidate-image.sh"; then
  echo 'dirty source tree was accepted' >&2
  exit 1
fi

if PATH="$WORK/bin:$PATH" FAKE_COMMIT="$COMMIT" FAKE_IMAGE_ID="$IMAGE_ID" \
  FAKE_DOCKER_LOG="$WORK/mismatch.log" FAKE_EMBEDDED_COMMIT=deadbeef bash "$ROOT/ops/build-candidate-image.sh"; then
  echo 'mismatched embedded commit was accepted' >&2
  exit 1
fi

echo "candidate image attestation contract: PASS"

if PATH="$WORK/bin:$PATH" FAKE_COMMIT="$COMMIT" FAKE_IMAGE_ID="$IMAGE_ID" \
  FAKE_DOCKER_LOG="$WORK/missing-model.log" FAKE_MODEL_MISSING=1 bash "$ROOT/ops/build-candidate-image.sh"; then
  echo 'image without an installed model was accepted' >&2
  exit 1
fi
grep -Fx -- "run --rm -i --network none --entrypoint python avelren-candidate:$COMMIT -" "$WORK/docker.log"
echo "installed model attestation contract: PASS"
