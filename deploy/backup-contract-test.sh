#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

make_tools() {
    local bin=$1 remote=$2
    mkdir -p "$bin" "$remote"
    cat >"$bin/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_CALL_LOG:?}"
[ "${PGPASSWORD:-}" = "${EXPECTED_BACKUP_PASSWORD:?}" ] || {
    echo 'backup password was not provided through the process environment' >&2
    exit 14
}
[[ " $* " == *' exec -T -e PGPASSWORD db pg_dump --no-owner -U avelren_backup -d avelren '* ]] || {
    echo 'pg_dump did not use the canonical backup role' >&2
    exit 15
}
[[ " $* " == *' --no-owner '* ]] || {
    echo 'pg_dump did not use the canonical ownership-neutral format' >&2
    exit 17
}
[[ "$*" != *"$EXPECTED_BACKUP_PASSWORD"* ]] || {
    echo 'backup password leaked into docker argv' >&2
    exit 16
}
[ "${FAKE_DUMP_FAIL:-0}" != 1 ] || { printf 'partial'; exit 9; }
if [ "${FAKE_SMALL_DUMP:-0}" = 1 ]; then
    printf 'SELECT 1;\n'
else
    head -c 30000 /dev/urandom | base64
fi
SH
    cat >"$bin/rclone" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cmd=$1; shift
path() { printf '%s/%s' "$FAKE_REMOTE" "${1#*:}"; }
case "$cmd" in
config)
    # `rclone config show <name>` — preflight check of the remote type (M-11).
    if [ "${FAKE_REMOTE_NOT_CRYPT:-0}" = 1 ]; then
        printf 'type = drive\n'
    else
        printf 'type = crypt\n'
    fi
    ;;
copyto)
    src=$1; dst=$(path "$2")
    [ "${FAKE_UPLOAD_FAIL:-0}" != 1 ] || exit 10
    mkdir -p "$(dirname "$dst")"; cp "$src" "$dst"
    ;;
cat)
    file=$(path "$1")
    if [[ "$file" == *.sha256 ]]; then
        if [ "${FAKE_VERIFY_MISMATCH:-0}" = 1 ]; then printf 'mismatch\n'; else cat "$file"; fi
    else
        [ "${FAKE_REMOTE_CAT_FAIL:-0}" != 1 ] || exit 13
        if [ "${FAKE_SAME_SIZE_CORRUPTION:-0}" = 1 ]; then
            python3 - "$file" <<'PY'
import pathlib
import sys

data = bytearray(pathlib.Path(sys.argv[1]).read_bytes())
data[len(data) // 2] ^= 1
sys.stdout.buffer.write(data)
PY
        else
            cat "$file"
        fi
    fi
    ;;
size)
    file=$(path "$1"); size=$(stat -c %s "$file")
    [ "${FAKE_SIZE_MISMATCH:-0}" != 1 ] || size=$((size + 1))
    printf '{"count":1,"bytes":%s}\n' "$size"
    ;;
lsf)
    printf 'RETENTION\n' >>"${FAKE_CALL_LOG:-/dev/null}"
    dir=$(path "$1")
    [ "${FAKE_RETENTION_FAIL:-0}" != 1 ] || exit 11
    find "$dir" -maxdepth 1 -type f -name 'avelren-*.sql.gz' -printf '%f\n' 2>/dev/null || true
    ;;
deletefile)
    # Real rclone deletefile fails with exit 3 when the target does not exist.
    # The `-f` in `rm -f` used to hide that, so a bug where the caller passed a
    # non-existent path (like a `.sha256` sidecar the deployed script never
    # wrote) would slip through this contract test. Mirror the real semantics.
    target=$(path "$1")
    if [ ! -e "$target" ]; then
        echo "rclone-stub: file not found: $target" >&2
        exit 3
    fi
    rm -f -- "$target"
    ;;
delete)
    # `rclone delete <dir> --include <pattern>` — semantic used for the
    # sidecar cleanup: an empty match returns 0, a real access failure does
    # not. The stub mirrors that: `find -exec rm -f` is silent on missing.
    dir=$(path "$1"); shift
    pattern=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --include) pattern=$2; shift 2 ;;
            *) shift ;;
        esac
    done
    [ -n "$pattern" ] || exit 12
    find "$dir" -maxdepth 1 -type f -name "$pattern" -exec rm -f {} + 2>/dev/null
    ;;
*) exit 12 ;;
esac
SH
    chmod +x "$bin/docker" "$bin/rclone"
}

run_case() {
    local name=$1; shift
    local case_dir="$WORK/$name" bin="$WORK/$name/bin" remote="$WORK/$name/remote"
    mkdir -p "$case_dir/stack"
    make_tools "$bin" "$remote"
    env PATH="$bin:$PATH" FAKE_REMOTE="$remote" \
        AVELREN_STACK_DIR="$case_dir/stack" \
        AVELREN_BACKUP_WORK_DIR="$case_dir/work" \
        AVELREN_BACKUP_REMOTE="fake:$remote" \
        AVELREN_RCLONE_CONFIG="$case_dir/rclone.conf" \
        AVELREN_BACKUP_STAMP="$case_dir/stamp" \
        AVELREN_BACKUP_PASSWORD=backup-contract-secret \
        EXPECTED_BACKUP_PASSWORD=backup-contract-secret \
        FAKE_CALL_LOG="$case_dir/calls.log" \
        "$@" bash "$ROOT/deploy/backup.sh"
}

assert_no_plaintext() {
    local dir=$1
    [ -d "$dir" ] || return 0
    ! find "$dir" -maxdepth 1 -type f \( -name '*.sql.gz' -o -name '*.sha256' \) | grep -q .
}

run_case success
[ "$(stat -c %a "$WORK/success/work")" = 700 ]
[ -e "$WORK/success/stamp" ]
assert_no_plaintext "$WORK/success/work"
remote_dump=$(find "$WORK/success/remote" -type f -name '*.sql.gz' | head -1)
[ -n "$remote_dump" ] && [ -f "$remote_dump.sha256" ]
grep -q 'pg_dump --no-owner -U avelren_backup -d avelren' "$WORK/success/calls.log"
grep -q -- '--no-owner' "$WORK/success/calls.log"
! grep -Eq 'pg_dump -U (avelren|avelren_admin|avelren_migrator)( |$)' "$WORK/success/calls.log"
! grep -q 'backup-contract-secret' "$WORK/success/calls.log"

# Role and credential gates run before Docker can reach PostgreSQL.
for item in \
    'missing-password:AVELREN_BACKUP_PASSWORD=' \
    'admin-role:AVELREN_BACKUP_DB_USER=avelren_admin' \
    'migrator-role:AVELREN_BACKUP_DB_USER=avelren_migrator' \
    'legacy-role:AVELREN_BACKUP_DB_USER=avelren'
do
    name=${item%%:*}; setting=${item#*:}
    if run_case "$name" "$setting"; then
        echo "expected backup role gate failure: $name" >&2; exit 1
    fi
    [ ! -s "$WORK/$name/calls.log" ]
    [ ! -e "$WORK/$name/stamp" ]
    assert_no_plaintext "$WORK/$name/work"
done

for item in \
    'dump:FAKE_DUMP_FAIL=1' \
    'small:FAKE_SMALL_DUMP=1' \
    'upload:FAKE_UPLOAD_FAIL=1' \
    'verify:FAKE_VERIFY_MISMATCH=1' \
    'same-size:FAKE_SAME_SIZE_CORRUPTION=1' \
    'remote-cat:FAKE_REMOTE_CAT_FAIL=1' \
    'size:FAKE_SIZE_MISMATCH=1' \
    'retention:FAKE_RETENTION_FAIL=1'
do
    name=${item%%:*}; flag=${item#*:}
    if run_case "$name" "$flag"; then
        echo "expected backup failure: $name" >&2; exit 1
    fi
    [ ! -e "$WORK/$name/stamp" ]
    assert_no_plaintext "$WORK/$name/work"
    if [ "$name" = same-size ] || [ "$name" = remote-cat ]; then
        ! grep -q RETENTION "$WORK/$name/calls.log" 2>/dev/null
    fi
done

# M-11: remote not of type crypt → backup fails at preflight, BEFORE the dump and stamp.
if run_case not-crypt FAKE_REMOTE_NOT_CRYPT=1; then
    echo "expected non-crypt remote gate failure" >&2; exit 1
fi
[ ! -e "$WORK/not-crypt/stamp" ]
[ ! -s "$WORK/not-crypt/calls.log" ]
assert_no_plaintext "$WORK/not-crypt/work"

# Corrupt gzip validator: test the actual script while replacing only gzip.
case_dir="$WORK/gzip"; mkdir -p "$case_dir/stack"; make_tools "$case_dir/bin" "$case_dir/remote"
cat >"$case_dir/bin/gzip" <<'SH'
#!/usr/bin/env bash
if [ "${1:-}" = -t ]; then
    printf 'GZIP_T_REACHED\n' >>"${FAKE_CALL_LOG:?}"
    exit 1
fi
exec /usr/bin/gzip "$@"
SH
chmod +x "$case_dir/bin/gzip"
if env PATH="$case_dir/bin:$PATH" FAKE_REMOTE="$case_dir/remote" \
    AVELREN_STACK_DIR="$case_dir/stack" AVELREN_BACKUP_WORK_DIR="$case_dir/work" \
    AVELREN_BACKUP_REMOTE="fake:$case_dir/remote" AVELREN_RCLONE_CONFIG=x \
    AVELREN_BACKUP_STAMP="$case_dir/stamp" \
    AVELREN_BACKUP_PASSWORD=backup-contract-secret \
    EXPECTED_BACKUP_PASSWORD=backup-contract-secret \
    FAKE_CALL_LOG="$case_dir/calls.log" bash "$ROOT/deploy/backup.sh"; then
    echo "expected gzip validation failure" >&2; exit 1
fi
[ "$(grep -c '^GZIP_T_REACHED$' "$case_dir/calls.log")" -eq 1 ]
[ ! -e "$case_dir/stamp" ]; assert_no_plaintext "$case_dir/work"

# Cleanup is scoped: unrelated operator file survives every trap.
mkdir -p "$WORK/unrelated/work"; printf keep >"$WORK/unrelated/work/operator-note"
run_case unrelated
[ "$(cat "$WORK/unrelated/work/operator-note")" = keep ]

# Retention with missing sidecars: the actual production state before this fix.
# The deployed script never wrote `.sha256` sidecars, so on the first
# repository-script run every rotated dump has a missing companion. The
# rotation must NOT fail on that (fixed by using `rclone delete --include`
# instead of `rclone deletefile` for the sidecar). If it does, the successful
# backup is reported as failed AND the stamp is never touched.
mismatched_dir="$WORK/mismatched"
mkdir -p "$mismatched_dir/stack" "$mismatched_dir/remote/daily"
make_tools "$mismatched_dir/bin" "$mismatched_dir/remote"
for i in 1 2 3 4 5 6 7 8; do
    printf 'legacy' >"$mismatched_dir/remote/daily/avelren-2025010${i}-000000.sql.gz"
done
env PATH="$mismatched_dir/bin:$PATH" FAKE_REMOTE="$mismatched_dir/remote" \
    AVELREN_STACK_DIR="$mismatched_dir/stack" \
    AVELREN_BACKUP_WORK_DIR="$mismatched_dir/work" \
    AVELREN_BACKUP_REMOTE="fake:$mismatched_dir/remote" \
    AVELREN_RCLONE_CONFIG="$mismatched_dir/rclone.conf" \
    AVELREN_BACKUP_STAMP="$mismatched_dir/stamp" \
    AVELREN_BACKUP_PASSWORD=backup-contract-secret \
    EXPECTED_BACKUP_PASSWORD=backup-contract-secret \
    FAKE_CALL_LOG="$mismatched_dir/calls.log" bash "$ROOT/deploy/backup.sh"
[ -e "$mismatched_dir/stamp" ]
# 8 legacy + 1 new = 9 listed; KEEP_DAILY=7 → the two oldest are rotated out.
# Numeric comparison: `wc -l` output can carry leading whitespace.
kept=$(find "$mismatched_dir/remote/daily" -maxdepth 1 -type f -name '*.sql.gz' | wc -l)
[ "$kept" -eq 7 ] || { echo "expected 7 dumps kept, got $kept" >&2; exit 1; }

echo "backup contract tests: 19 passed"
