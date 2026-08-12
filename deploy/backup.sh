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
fail() { log "ПОМИЛКА: $*" >&2; exit 1; }

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

# Гарантія шифрування: remote МУСИТЬ бути типу crypt. Інакше gzip-дамп (gzip —
# не шифрування) полетів би на off-host сховище відкритим текстом. Заголовок
# скрипта обіцяє "encrypted", тож перевіряємо це, а не припускаємо: env-override
# AVELREN_BACKUP_REMOTE чи регресія конфігу легко націлили б бекап на плоский
# remote (аудит M-11). Дешевий preflight — до дорогого дампа.
REMOTE_NAME=${REMOTE%%:*}
[ "$REMOTE_NAME" != "$REMOTE" ] || fail "remote '$REMOTE' має бути у форматі <remote>:<шлях>"
remote_type=$(rclone config show "$REMOTE_NAME" --config "$RCLONE_CONFIG" 2>/dev/null \
    | sed -n 's/^[[:space:]]*type[[:space:]]*=[[:space:]]*//p' | head -1)
[ "$remote_type" = crypt ] || \
    fail "backup remote '$REMOTE_NAME' має бути типу crypt (виявлено: '${remote_type:-невідомо}') — шифрування не гарантоване"

mkdir -p -- "$WORK_DIR"
chmod 0700 -- "$WORK_DIR"
[ "$(stat -c %a "$WORK_DIR")" = 700 ] || fail "work directory не має mode 0700"
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

log "дамп бази у захищений temporary artifact"
PGPASSWORD="$BACKUP_DB_PASSWORD" \
    docker compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U "$BACKUP_DB_USER" -d avelren | gzip -9 >"$DUMP"
[ -f "$DUMP" ] || fail "dump artifact не створено"
[ "$(stat -c %a "$DUMP")" = 600 ] || fail "dump artifact не має mode 0600"
bytes=$(stat -c %s "$DUMP")
[ "$bytes" -ge "$MIN_BYTES" ] || fail "дамп менший за $MIN_BYTES байт"
gzip -t "$DUMP" || fail "gzip integrity validation не пройдена"

digest=$(sha256sum "$DUMP" | awk '{print $1}')
printf '%s  %s\n' "$digest" "$NAME" >"$MANIFEST"
expected_manifest=$(cat "$MANIFEST")

log "upload encrypted artifact і integrity sidecar у $REMOTE/$TIER"
rclone copyto "$DUMP" "$REMOTE_DUMP" --config "$RCLONE_CONFIG"
rclone copyto "$MANIFEST" "$REMOTE_MANIFEST" --config "$RCLONE_CONFIG"

remote_manifest=$(rclone cat "$REMOTE_MANIFEST" --config "$RCLONE_CONFIG")
[ "$remote_manifest" = "$expected_manifest" ] || fail "remote SHA-256 manifest mismatch"
remote_digest=$(rclone cat "$REMOTE_DUMP" --config "$RCLONE_CONFIG" | sha256sum | awk '{print $1}')
[ "$remote_digest" = "$digest" ] || fail "remote dump SHA-256 mismatch"
remote_size_json=$(rclone size "$REMOTE_DUMP" --json --config "$RCLONE_CONFIG")
remote_bytes=$(printf '%s\n' "$remote_size_json" | sed -n 's/.*"bytes"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -1)
[ -n "$remote_bytes" ] || fail "remote size не вдалося прочитати"
[ "$remote_bytes" = "$bytes" ] || fail "remote size mismatch: local=$bytes remote=$remote_bytes"

log "verified remote artifact; ротація: лишаю $KEEP у $TIER"
remote_listing=$(rclone lsf "$REMOTE/$TIER/" --files-only --include 'avelren-*.sql.gz' \
    --config "$RCLONE_CONFIG") || fail "remote retention listing failed"
mapfile -t old_names < <(
    printf '%s\n' "$remote_listing" | sort -r | tail -n +$((KEEP + 1))
)
for old in "${old_names[@]}"; do
    [ -n "$old" ] || continue
    [ "$old" != "$NAME" ] || fail "rotation спробувала видалити щойно створений backup"
    log "видаляю застарілий $old"
    rclone deletefile "$REMOTE/$TIER/$old" --config "$RCLONE_CONFIG"
    rclone deletefile "$REMOTE/$TIER/$old.sha256" --config "$RCLONE_CONFIG"
done

mkdir -p -- "$(dirname "$STAMP_FILE")"
touch -- "$STAMP_FILE"
log "готово: remote artifact перевірено, stamp оновлено"
