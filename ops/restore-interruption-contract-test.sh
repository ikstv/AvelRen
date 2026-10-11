#!/usr/bin/env bash
# Every Docker call is intercepted. Signals target only the fixture shell.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/stack"
printf 'fixture\n' >"$WORK/dump.gz"
cat >"$WORK/bin/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$TRACE"
if [[ " $* " == *' psql '* && " $* " != *' -c '* ]]; then cat >/dev/null; fi
if [[ "$*" == *'timescaledb_post_restore()'* && "$SIGNAL_PHASE" = post ]]; then
    kill -s "$SIGNAL" "$PPID"
fi
if [[ "$*" == *'timescaledb_post_restore()'* && "$POST_FAIL" = 1 ]]; then exit 29; fi
exit 0
SH
chmod +x "$WORK/bin/docker"
run_case() {
    local name=$1 signal=$2 post_fail=$3 phase=${4:-ingest}
    : >"$WORK/$name.trace"
    set +e
    env PATH="$WORK/bin:$PATH" TRACE="$WORK/$name.trace" \
        SIGNAL="$signal" SIGNAL_PHASE="$phase" POST_FAIL="$post_fail" AVELREN_ADMIN_PASSWORD=fixture-only \
        bash -c '
            set -euo pipefail
            source "$1/ops/restore-engine.lib.sh"
            trap '\''printf "caller-exit=%s\n" "$?" >>"$TRACE"'\'' EXIT
            trap "exit 129" HUP
            trap "exit 130" INT
            trap "exit 143" TERM
            original_traps=$(trap -p EXIT HUP INT TERM)
            gunzip() {
                if [ "$SIGNAL" != none ] && [ "$SIGNAL_PHASE" = ingest ]; then
                    kill -s "$SIGNAL" "$$"
                fi
                printf "SELECT 1;\n"
            }
            avelren_restore_engine "$2/dump.gz" restore_test "$2/stack" "" fixture db
            [ "$(trap -p EXIT HUP INT TERM)" = "$original_traps" ]
            printf "returned\n" >>"$TRACE"
        ' bash "$ROOT" "$WORK" >"$WORK/$name.out" 2>&1
    CASE_STATUS=$?
    set -e
}
for signal in HUP INT TERM; do
    case "$signal" in HUP) expected=129 ;; INT) expected=130 ;; TERM) expected=143 ;; esac
    for post_fail in 0 1; do
        name="$signal-$post_fail"
        run_case "$name" "$signal" "$post_fail"
        [ "$CASE_STATUS" -eq "$expected" ] || { cat "$WORK/$name.out"; exit 1; }
        post_count=$(grep -c 'timescaledb_post_restore()' "$WORK/$name.trace" || true)
        [ "$post_count" -eq 1 ] || {
            echo "FAIL: $name expected one post_restore cleanup, got $post_count" >&2
            exit 1
        }
        grep -qx "caller-exit=$expected" "$WORK/$name.trace"
        ! grep -q 'application ownership\|SELECT (SELECT count\|returned' "$WORK/$name.trace"
    done
done
# Once post_restore starts, an interruption must not issue it a second time.
run_case interrupted-post TERM 0 post
[ "$CASE_STATUS" -eq 143 ]
[ "$(grep -c 'timescaledb_post_restore()' "$WORK/interrupted-post.trace")" -eq 1 ]
grep -qx caller-exit=143 "$WORK/interrupted-post.trace"
run_case success none 0
[ "$CASE_STATUS" -eq 0 ] || { cat "$WORK/success.out"; exit 1; }
[ "$(grep -c 'timescaledb_post_restore()' "$WORK/success.trace")" -eq 1 ]
grep -qx returned "$WORK/success.trace"
grep -qx caller-exit=0 "$WORK/success.trace"
echo 'restore interruption contracts: 8 passed'
