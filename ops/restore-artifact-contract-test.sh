#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
DUMP="$WORK/avelren-20260925-120000.sql.gz"
SIDECAR="$DUMP.sha256"

echo 'SELECT 1;' | gzip -9 >"$DUMP"
digest=$(sha256sum "$DUMP" | awk '{print $1}')
echo "$digest  $(basename "$DUMP")" >"$SIDECAR"

verify() {
    bash -c 'set -euo pipefail; source "$1"; avelren_verify_restore_artifact "$2" "$3"' bash "$ROOT/ops/restore-artifact.lib.sh" "$1" "$2"
}

verify "$DUMP" "$SIDECAR"

if bash "$ROOT/ops/restore-artifact.lib.sh" >"$WORK/direct.out" 2>&1; then
    echo "source-only artifact verifier ran directly" >&2
    exit 1
fi
grep -q 'source-only' "$WORK/direct.out"

denied() {
    local name=$1
    shift
    if "$@" >"$WORK/$name.out" 2>&1; then
        echo "expected artifact gate denial: $name" >&2
        exit 1
    fi
}

denied missing-dump verify "$WORK/missing.sql.gz" "$SIDECAR"
denied missing-sidecar verify "$DUMP" "$WORK/missing.sha256"

echo 'not a gzip' >"$WORK/bad.sql.gz"
echo "$(printf '%064d' 0)  bad.sql.gz" >"$WORK/bad.sql.gz.sha256"
denied corrupt-gzip verify "$WORK/bad.sql.gz" "$WORK/bad.sql.gz.sha256"

echo "$(printf '%064d' 0)  $(basename "$DUMP")" >"$SIDECAR"
denied wrong-digest verify "$DUMP" "$SIDECAR"

echo "$digest $(basename "$DUMP")" >"$SIDECAR"
denied noncanonical-spacing verify "$DUMP" "$SIDECAR"

echo "$digest  ../other.sql.gz" >"$SIDECAR"
denied path-in-sidecar verify "$DUMP" "$SIDECAR"

echo "$digest  other.sql.gz" >"$SIDECAR"
denied wrong-name verify "$DUMP" "$SIDECAR"

{ echo "$digest  $(basename "$DUMP")"; echo "$digest  $(basename "$DUMP")"; } >"$SIDECAR"
denied multiple-lines verify "$DUMP" "$SIDECAR"

echo "restore artifact contract: PASS (8 denials + source-only guard)"
