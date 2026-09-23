#!/usr/bin/env bash
# Encrypted off-host backup with a guaranteed local plaintext cleanup contract.
set -euo pipefail

umask 077

STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
WORK_DIR=${AVELREN_BACKUP_WORK_DIR:-/var/lib/avelren-backup}
REMOTE=${AVELREN_BACKUP_REMOTE:-gdrive-crypt:avelren}
RCLONE_CONFIG=${AVELREN_RCLONE_CONFIG:-/root/.config/rclone/rclone.conf}
STAMP_FILE=${AVELREN_BACKUP_STAMP:-/run/avelren-backup.stamp}
MIN_BYTES=${AVELREN_BACKUP_MIN_BYTES:-10240}
KEEP_DAILY=${AVELREN_KEEP_DAILY:-7}
KEEP_WEEKLY=${AVELREN_KEEP_WEEKLY:-4}
KEEP_MONTHLY=${AVELREN_KEEP_MONTHLY:-3}
BACKUP_DB_USER=${AVELREN_BACKUP_DB_USER:-avelren_backup}
BACKUP_DB_PASSWORD=${AVELREN_BACKUP_PASSWORD:-}

log() { echo "$(date -u +%FT%TZ) $*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

DUMP=
MANIFEST=
cleanup() {
    local status=$?
    trap - EXIT HUP INT TERM
    [ -z "$DUMP" ] || rm -f -- "$DUMP"
    [ -z "$MANIFEST" ] || rm -f -- "$MANIFEST"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

[ "$BACKUP_DB_USER" = avelren_backup ] || fail "backup database role must be avelren_backup"
[ -n "$BACKUP_DB_PASSWORD" ] || fail "backup database password is required"

# Encryption guarantee: the remote MUST be of type crypt. Otherwise the gzip dump
# (gzip is not encryption) would fly to off-host storage in plaintext. The script's
# header promises "encrypted", so we verify that rather than assume it: an env override
# of AVELREN_BACKUP_REMOTE or a config regression could easily point the backup at a flat
# remote (audit M-11). A cheap preflight — before the expensive dump.
REMOTE_NAME=${REMOTE%%:*}
[ "$REMOTE_NAME" != "$REMOTE" ] || fail "remote '$REMOTE' must be in the format <remote>:<path>"
remote_type=$(rclone config show "$REMOTE_NAME" --config "$RCLONE_CONFIG" 2>/dev/null \
    | sed -n 's/^[[:space:]]*type[[:space:]]*=[[:space:]]*//p' | head -1)
[ "$remote_type" = crypt ] || \
    fail "backup remote '$REMOTE_NAME' must be of type crypt (detected: '${remote_type:-unknown}') — encryption is not guaranteed"

mkdir -p -- "$WORK_DIR"
chmod 0700 -- "$WORK_DIR"
[ "$(stat -c %a "$WORK_DIR")" = 700 ] || fail "work directory does not have mode 0700"
cd "$STACK_DIR"

STAMP=$(date -u +%Y%m%d-%H%M%S)
DOW=$(date -u +%u)
DOM=$(date -u +%d)
if [ "$DOM" = 01 ]; then
    TIER=monthly
elif [ "$DOW" = 7 ]; then
    TIER=weekly
else
    TIER=daily
fi
case "$TIER" in
    daily) KEEP=$KEEP_DAILY ;;
    weekly) KEEP=$KEEP_WEEKLY ;;
    monthly) KEEP=$KEEP_MONTHLY ;;
esac

DUMP=$(mktemp "$WORK_DIR/.avelren-$STAMP.XXXXXX.sql.gz")
MANIFEST=$(mktemp "$WORK_DIR/.avelren-$STAMP.XXXXXX.sha256")
chmod 0600 -- "$DUMP" "$MANIFEST"
NAME="avelren-$STAMP.sql.gz"
MANIFEST_NAME="$NAME.sha256"
REMOTE_DUMP="$REMOTE/$TIER/$NAME"
REMOTE_MANIFEST="$REMOTE/$TIER/$MANIFEST_NAME"

log "dumping the database into a protected temporary artifact"
PGPASSWORD="$BACKUP_DB_PASSWORD" \
    docker compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U "$BACKUP_DB_USER" -d avelren | gzip -9 >"$DUMP"
[ -f "$DUMP" ] || fail "dump artifact was not created"
[ "$(stat -c %a "$DUMP")" = 600 ] || fail "dump artifact does not have mode 0600"
bytes=$(stat -c %s "$DUMP")
[ "$bytes" -ge "$MIN_BYTES" ] || fail "dump is smaller than $MIN_BYTES bytes"
gzip -t "$DUMP" || fail "gzip integrity validation failed"

digest=$(sha256sum "$DUMP" | awk '{print $1}')
printf '%s  %s\n' "$digest" "$NAME" >"$MANIFEST"
expected_manifest=$(cat "$MANIFEST")

log "uploading encrypted artifact and integrity sidecar to $REMOTE/$TIER"
rclone copyto "$DUMP" "$REMOTE_DUMP" --config "$RCLONE_CONFIG"
rclone copyto "$MANIFEST" "$REMOTE_MANIFEST" --config "$RCLONE_CONFIG"

remote_manifest=$(rclone cat "$REMOTE_MANIFEST" --config "$RCLONE_CONFIG")
[ "$remote_manifest" = "$expected_manifest" ] || fail "remote SHA-256 manifest mismatch"
remote_digest=$(rclone cat "$REMOTE_DUMP" --config "$RCLONE_CONFIG" | sha256sum | awk '{print $1}')
[ "$remote_digest" = "$digest" ] || fail "remote dump SHA-256 mismatch"
remote_size_json=$(rclone size "$REMOTE_DUMP" --json --config "$RCLONE_CONFIG")
remote_bytes=$(printf '%s\n' "$remote_size_json" | sed -n 's/.*"bytes"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -1)
[ -n "$remote_bytes" ] || fail "could not read remote size"
[ "$remote_bytes" = "$bytes" ] || fail "remote size mismatch: local=$bytes remote=$remote_bytes"

log "verified remote artifact; rotation: keeping $KEEP in $TIER"
remote_listing=$(rclone lsf "$REMOTE/$TIER/" --files-only --include 'avelren-*.sql.gz' \
    --config "$RCLONE_CONFIG") || fail "remote retention listing failed"
mapfile -t old_names < <(
    printf '%s\n' "$remote_listing" | sort -r | tail -n +$((KEEP + 1))
)
for old in "${old_names[@]}"; do
    [ -n "$old" ] || continue
    [ "$old" != "$NAME" ] || fail "rotation tried to delete the just-created backup"
    log "deleting stale $old"
    rclone deletefile "$REMOTE/$TIER/$old" --config "$RCLONE_CONFIG"
    # The sidecar may or may not exist: the deployed script never wrote them,
    # so on the first repository-script run every rotated dump has a missing
    # `.sha256`. `rclone deletefile` returns non-zero on missing → `set -e`
    # would kill an otherwise successful backup, AND `touch "$STAMP_FILE"`
    # below would not run, silently starving watchdog after 36 h.
    # `rclone delete <dir> --include <name>` returns 0 on an empty match and
    # non-zero on real access errors — the semantic we want. `|| true` here
    # would also mask genuine remote failures, so do not simplify to that.
    rclone delete "$REMOTE/$TIER/" --include "$old.sha256" --config "$RCLONE_CONFIG"
done

mkdir -p -- "$(dirname "$STAMP_FILE")"
touch -- "$STAMP_FILE"
log "done: remote artifact verified, stamp updated"
