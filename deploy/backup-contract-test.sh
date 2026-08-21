#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# The fake remote is addressed the way the real one is: `<remote>:<path>`, where
# the path is RELATIVE to the remote root (production uses `gdrive-crypt:avelren`).
# An absolute path here would make the stub's path() produce a nested
# $FAKE_REMOTE/$FAKE_REMOTE/... tree — self-consistent, and therefore invisible
# to every assertion that searches recursively. See assert_remote_layout.
FAKE_REMOTE_PATH=avelren
CASES=0

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
# `<remote>:<relative-path>` -> a path inside the fake remote root.
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
    printf 'DELETEFILE %s\n' "${1##*/}" >>"${FAKE_CALL_LOG:-/dev/null}"
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
    printf 'DELETE %s\n' "$pattern" >>"${FAKE_CALL_LOG:-/dev/null}"
    find "$dir" -maxdepth 1 -type f -name "$pattern" -exec rm -f {} + 2>/dev/null
    ;;
*) exit 12 ;;
esac
SH
    chmod +x "$bin/docker" "$bin/rclone"
}

# Split from run_case so a case can seed the remote (or swap the script under
# test) between preparation and execution.
prepare_case() {
    local name=$1
    mkdir -p "$WORK/$name/stack"
    make_tools "$WORK/$name/bin" "$WORK/$name/remote"
}

exec_case() {
    local name=$1; shift
    local case_dir="$WORK/$name" bin="$WORK/$name/bin" remote="$WORK/$name/remote"
    CASES=$((CASES + 1))
    env PATH="$bin:$PATH" FAKE_REMOTE="$remote" \
        AVELREN_STACK_DIR="$case_dir/stack" \
        AVELREN_BACKUP_WORK_DIR="$case_dir/work" \
        AVELREN_BACKUP_REMOTE="fake:$FAKE_REMOTE_PATH" \
        AVELREN_RCLONE_CONFIG="$case_dir/rclone.conf" \
        AVELREN_BACKUP_STAMP="$case_dir/stamp" \
        AVELREN_BACKUP_PASSWORD=backup-contract-secret \
        EXPECTED_BACKUP_PASSWORD=backup-contract-secret \
        FAKE_CALL_LOG="$case_dir/calls.log" \
        "$@" bash "${SCRIPT_UNDER_TEST:-$ROOT/deploy/backup.sh}"
}

run_case() {
    local name=$1; shift
    prepare_case "$name"
    exec_case "$name" "$@"
}

assert_no_plaintext() {
    local dir=$1
    [ -d "$dir" ] || return 0
    ! find "$dir" -maxdepth 1 -type f \( -name '*.sql.gz' -o -name '*.sha256' \) | grep -q .
}

# Exact remote layout, not "somewhere under the remote root": the artifacts must
# sit at <root>/avelren/<tier>/ and nowhere else, and there must be exactly two
# of them. A `find -type f` without this shape check passes just as happily when
# the stub writes into a nested directory — which is how a broken path() stayed
# invisible for the whole life of this test.
assert_remote_layout() {
    local root=$1 f
    mapfile -t files < <(cd "$root" && find . -type f | sed 's|^\./||' | sort)
    [ "${#files[@]}" -eq 2 ] || {
        echo "remote layout: expected 2 files, got ${#files[@]}: ${files[*]-}" >&2; return 1; }
    for f in "${files[@]}"; do
        [[ "$f" =~ ^avelren/(daily|weekly|monthly)/avelren-[0-9]{8}-[0-9]{6}\.sql\.gz(\.sha256)?$ ]] || {
            echo "remote layout: unexpected path '$f'" >&2; return 1; }
    done
    [[ "${files[0]}.sha256" == "${files[1]}" ]] || {
        echo "remote layout: dump and sidecar are not a pair: ${files[*]}" >&2; return 1; }
}

run_case success
[ "$(stat -c %a "$WORK/success/work")" = 700 ]
[ -e "$WORK/success/stamp" ]
assert_no_plaintext "$WORK/success/work"
assert_remote_layout "$WORK/success/remote"
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
prepare_case gzip
cat >"$WORK/gzip/bin/gzip" <<'SH'
#!/usr/bin/env bash
if [ "${1:-}" = -t ]; then
    printf 'GZIP_T_REACHED\n' >>"${FAKE_CALL_LOG:?}"
    exit 1
fi
exec /usr/bin/gzip "$@"
SH
chmod +x "$WORK/gzip/bin/gzip"
if exec_case gzip; then
    echo "expected gzip validation failure" >&2; exit 1
fi
[ "$(grep -c '^GZIP_T_REACHED$' "$WORK/gzip/calls.log")" -eq 1 ]
[ ! -e "$WORK/gzip/stamp" ]; assert_no_plaintext "$WORK/gzip/work"

# Cleanup is scoped: unrelated operator file survives every trap.
mkdir -p "$WORK/unrelated/work"; printf keep >"$WORK/unrelated/work/operator-note"
run_case unrelated
[ "$(cat "$WORK/unrelated/work/operator-note")" = keep ]

# --- #93: rotation over legacy dumps that have no `.sha256` sidecar ----------
# This is the actual production state: every artifact written by the drifted
# host-only script lacks a sidecar. Seeding all three tiers keeps the case
# independent of which tier today's UTC date selects — the script lists only its
# own tier, and the two idle tiers double as a cross-tier containment check.
SEED_OLD=avelren-20200101-000000.sql.gz
SEED_NEW=avelren-20200102-000000.sql.gz

seed_legacy_tiers() {
    local remote=$1 tier
    for tier in daily weekly monthly; do
        mkdir -p "$remote/$FAKE_REMOTE_PATH/$tier"
        printf 'legacy-dump-without-sidecar\n' >"$remote/$FAKE_REMOTE_PATH/$tier/$SEED_OLD"
        printf 'legacy-dump-without-sidecar\n' >"$remote/$FAKE_REMOTE_PATH/$tier/$SEED_NEW"
    done
}

prepare_case sidecar
seed_legacy_tiers "$WORK/sidecar/remote"
exec_case sidecar AVELREN_KEEP_DAILY=2 AVELREN_KEEP_WEEKLY=2 AVELREN_KEEP_MONTHLY=2

# The stamp is the point: a failure in sidecar cleanup would leave it untouched
# and starve the watchdog after 36 h without failing anything visible sooner.
[ -e "$WORK/sidecar/stamp" ]
assert_no_plaintext "$WORK/sidecar/work"
mapfile -t fresh < <(
    find "$WORK/sidecar/remote" -type f -name 'avelren-*.sql.gz' \
        ! -name "$SEED_OLD" ! -name "$SEED_NEW" | sort
)
[ "${#fresh[@]}" -eq 1 ] || { echo "sidecar: expected one fresh dump, got ${#fresh[@]}" >&2; exit 1; }
sidecar_tier=$(basename "$(dirname "${fresh[0]}")")
[ -f "${fresh[0]}.sha256" ] || { echo "sidecar: fresh dump has no manifest" >&2; exit 1; }
[ ! -e "$WORK/sidecar/remote/$FAKE_REMOTE_PATH/$sidecar_tier/$SEED_OLD" ] || {
    echo "sidecar: overflow dump was not rotated out" >&2; exit 1; }
[ -f "$WORK/sidecar/remote/$FAKE_REMOTE_PATH/$sidecar_tier/$SEED_NEW" ] || {
    echo "sidecar: rotation deleted more than the overflow" >&2; exit 1; }
for other in daily weekly monthly; do
    if [ "$other" != "$sidecar_tier" ]; then
        [ -f "$WORK/sidecar/remote/$FAKE_REMOTE_PATH/$other/$SEED_OLD" ] &&
        [ -f "$WORK/sidecar/remote/$FAKE_REMOTE_PATH/$other/$SEED_NEW" ] || {
            echo "sidecar: rotation crossed the tier boundary into $other" >&2; exit 1; }
    fi
done
grep -qx "DELETEFILE $SEED_OLD" "$WORK/sidecar/calls.log" || {
    echo "sidecar: overflow dump deletion was never attempted" >&2; exit 1; }
grep -qx "DELETE $SEED_OLD.sha256" "$WORK/sidecar/calls.log" || {
    echo "sidecar: sidecar cleanup did not use the empty-match-safe call" >&2; exit 1; }

# Counterfactual: the case above is only worth its lines if the pre-fix script
# fails it. Mutate the fix back out and require a red. If the mutation stops
# matching, that is an error, not a pass — an unapplied mutation would make this
# check silently vacuous, which is the exact failure mode we are guarding.
MUTANT="$WORK/pre-fix-backup.sh"
awk '
    /rclone delete .*--include .*sha256/ {
        print "    rclone deletefile \"$REMOTE/$TIER/$old.sha256\" --config \"$RCLONE_CONFIG\""
        mutated = 1
        next
    }
    { print }
    END { if (!mutated) exit 1 }
' "$ROOT/deploy/backup.sh" >"$MUTANT" || {
    echo "counterfactual: the pre-fix line no longer matches — update the mutation" >&2; exit 1; }

prepare_case pre-fix
seed_legacy_tiers "$WORK/pre-fix/remote"
SCRIPT_UNDER_TEST="$MUTANT"
if exec_case pre-fix AVELREN_KEEP_DAILY=2 AVELREN_KEEP_WEEKLY=2 AVELREN_KEEP_MONTHLY=2; then
    echo "counterfactual: the pre-fix script survived the missing-sidecar case — the case above proves nothing" >&2
    exit 1
fi
unset SCRIPT_UNDER_TEST
[ ! -e "$WORK/pre-fix/stamp" ] || {
    echo "counterfactual: the pre-fix script still stamped — wrong failure was reproduced" >&2; exit 1; }

echo "backup contract tests: $CASES passed"
