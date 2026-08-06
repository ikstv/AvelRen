#!/usr/bin/env bash
#
# Резервна копія AvelRen на Google Drive.
#
# Копія шифрується до відправки: у дампі лежать FCM-токени пристроїв, а сам
# архів їде в чужу хмару. Ключ шифрування залишається на сервері.
#
# Схема зберігання: 7 денних, 4 тижневі, 3 місячні.
#
set -euo pipefail

STACK_DIR=/opt/avelren
WORK_DIR=/var/lib/avelren-backup
REMOTE=gdrive-crypt:avelren
KEEP_DAILY=7
KEEP_WEEKLY=4
KEEP_MONTHLY=3

log() { echo "$(date -u +%FT%TZ) $*"; }

mkdir -p "$WORK_DIR"
cd "$STACK_DIR"

STAMP=$(date -u +%Y%m%d-%H%M%S)
DOW=$(date -u +%u)   # 7 = неділя
DOM=$(date -u +%d)

if [ "$DOM" = "01" ]; then
    TIER=monthly
elif [ "$DOW" = "7" ]; then
    TIER=weekly
else
    TIER=daily
fi

DUMP="$WORK_DIR/avelren-$STAMP.sql.gz"

log "дамп бази..."
# Через контейнер, щоб не залежати від версії psql на хості.
docker compose exec -T db pg_dump -U avelren -d avelren --no-owner \
    | gzip -9 > "$DUMP"

SIZE=$(du -h "$DUMP" | cut -f1)
log "дамп готовий: $SIZE"

# Порожній або підозріло малий дамп — привід зупинитись, а не залити сміття
# поверх робочих копій.
MIN_BYTES=10240
if [ "$(stat -c%s "$DUMP")" -lt "$MIN_BYTES" ]; then
    log "ПОМИЛКА: дамп менший за $MIN_BYTES байт, копію не відправляю"
    rm -f "$DUMP"
    exit 1
fi

log "відправка в $REMOTE/$TIER ..."
rclone copy "$DUMP" "$REMOTE/$TIER/" --config /root/.config/rclone/rclone.conf

case "$TIER" in
    daily)   KEEP=$KEEP_DAILY ;;
    weekly)  KEEP=$KEEP_WEEKLY ;;
    monthly) KEEP=$KEEP_MONTHLY ;;
esac

log "ротація: лишаю $KEEP у $TIER"
rclone lsf "$REMOTE/$TIER/" --config /root/.config/rclone/rclone.conf \
    | sort -r | tail -n +$((KEEP + 1)) | while read -r old; do
        log "видаляю застарілий $old"
        rclone deletefile "$REMOTE/$TIER/$old" --config /root/.config/rclone/rclone.conf
    done

rm -f "$DUMP"
log "готово"
