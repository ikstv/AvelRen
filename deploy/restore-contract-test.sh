#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

valid="$WORK/valid.sql.gz"
printf 'SELECT 1;\n' | gzip -c > "$valid"

denied() {
    if bash "$ROOT/deploy/restore.sh" "$@" >/dev/null 2>&1; then
        echo "expected restore denial: $*" >&2
        exit 1
    fi
}

# A: production target without explicit confirmation.
denied "$valid" --target avelren
# B: bad confirmation token.
denied "$valid" --target avelren --confirm-production-restore WRONG
# C: unsupported target.
denied "$valid" --target not-a-real-database --confirm-production-restore AVELREN-PRODUCTION-RESTORE
# D: corrupt artifact is rejected before any database command.
printf 'corrupt\n' > "$WORK/corrupt.sql.gz"
denied "$WORK/corrupt.sql.gz" --target restore_test
# E: missing artifact is rejected.
denied "$WORK/missing.sql.gz" --target restore_test
# F: disposable restore path still passes its pre-destructive contract.
bash "$ROOT/deploy/restore.sh" "$valid" --target restore_test --dry-run >/dev/null
# G: even the historical public phrase cannot authorize direct production.
denied "$valid" --target avelren \
    --confirm-production-restore AVELREN-PRODUCTION-RESTORE --dry-run

# H: the source-only engine has no executable production CLI.
if bash "$ROOT/deploy/restore-engine.lib.sh" >/dev/null 2>&1; then
    echo "source-only restore engine unexpectedly executed" >&2
    exit 1
fi

echo "restore contract tests: 8 passed"
