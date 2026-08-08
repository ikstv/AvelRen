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

BIN="$WORK/bin"
mkdir -p "$BIN"
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_LOG:?}"
if [[ " $* " == *' run --rm -T '* ]]; then
    [ "${DATABASE_URL:-}" = "${EXPECTED_ADMIN_DSN:?}" ] || {
        echo 'admin verification DSN was not provided through the process environment' >&2
        exit 40
    }
    [[ " $* " == *' -e DATABASE_URL '* ]] || {
        echo 'verification did not request protected DATABASE_URL forwarding' >&2
        exit 41
    }
    [[ "$*" != *"$EXPECTED_ADMIN_DSN"* ]] || {
        echo 'admin verification DSN leaked into docker argv' >&2
        exit 42
    }
fi
exit 0
SH
chmod +x "$BIN/docker"

# I/J: restore role configuration fails before the first database command.
for item in \
    'missing-password:AVELREN_ADMIN_PASSWORD=' \
    'non-admin-role:AVELREN_ADMIN_DB_USER=avelren_backup'
do
    name=${item%%:*}; setting=${item#*:}
    : >"$WORK/$name.log"
    if env PATH="$BIN:$PATH" FAKE_LOG="$WORK/$name.log" "$setting" \
        AVELREN_STACK_DIR="$ROOT" \
        bash "$ROOT/deploy/restore.sh" "$valid" --target restore_test >/dev/null 2>&1; then
        echo "expected restore role configuration denial: $name" >&2
        exit 1
    fi
    [ ! -s "$WORK/$name.log" ]
done

# K: verification refuses a missing admin DSN without starting an app process.
: >"$WORK/verify-missing.log"
if env PATH="$BIN:$PATH" FAKE_LOG="$WORK/verify-missing.log" \
    AVELREN_STACK_DIR="$ROOT" AVELREN_VERIFY_DATABASE_URL= \
    bash "$ROOT/deploy/restore-verify.sh" restore_test >/dev/null 2>&1; then
    echo 'expected missing admin verification DSN denial' >&2
    exit 1
fi
[ ! -s "$WORK/verify-missing.log" ]

# L: the admin DSN reaches the app only through its environment, never argv/logs.
ADMIN_DSN=postgresql://avelren_admin:verify-contract-secret@db:5432/restore_test
: >"$WORK/verify.log"
env PATH="$BIN:$PATH" FAKE_LOG="$WORK/verify.log" \
    AVELREN_STACK_DIR="$ROOT" AVELREN_VERIFY_DATABASE_URL="$ADMIN_DSN" \
    EXPECTED_ADMIN_DSN="$ADMIN_DSN" \
    bash "$ROOT/deploy/restore-verify.sh" restore_test >/dev/null
[ "$(wc -l <"$WORK/verify.log")" -eq 2 ]
if grep -q 'verify-contract-secret' "$WORK/verify.log"; then
    echo 'admin verification DSN leaked into logged argv' >&2
    exit 1
fi

echo "restore contract tests: 12 passed"
