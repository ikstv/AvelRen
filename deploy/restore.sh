#!/usr/bin/env bash
#
# Відновлення AvelRen з резервної копії.
#
# Звичайний psql на дампі TimescaleDB дає помилки на гіпертаблицях і
# стисненні: розширення намагається застосувати політики до того, як таблиці
# готові. Правильний шлях — timescaledb_pre_restore() до і
# timescaledb_post_restore() після.
#
# Використання:
#   avelren-restore <файл.sql.gz> [ім'я_бази]
#   avelren-restore <файл.sql.gz> --target avelren \
#       --confirm-production-restore AVELREN-PRODUCTION-RESTORE
#
# Без другого аргументу відновлює в restore_test, а не в бойову базу:
# помилитись і затерти прод має бути важче, ніж перевірити копію.
#
set -euo pipefail

STACK_DIR=/opt/avelren
PRODUCTION_TARGET=avelren
PRODUCTION_CONFIRMATION=AVELREN-PRODUCTION-RESTORE
DUMP=${1:?вкажіть файл дампа}
shift
TARGET=restore_test
CONFIRMATION=
DRY_RUN=false

if [ "$DUMP" = "--help" ]; then
    sed -n '1,24p' "$0"
    exit 0
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        --target)
            [ "$#" -ge 2 ] || { echo "помилка: --target потребує значення" >&2; exit 2; }
            TARGET=$2
            shift 2
            ;;
        --confirm-production-restore)
            [ "$#" -ge 2 ] || { echo "помилка: confirmation token відсутній" >&2; exit 2; }
            CONFIRMATION=$2
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "помилка: невідомий аргумент: $1" >&2
            exit 2
            ;;
    esac
done

log() { echo "$(date -u +%FT%TZ) $*"; }

if [ ! -f "$DUMP" ]; then
    log "ВІДМОВА: backup artifact не знайдено: $DUMP"
    exit 1
fi
if [ "$TARGET" != "restore_test" ] && [ "$TARGET" != "$PRODUCTION_TARGET" ]; then
    log "ВІДМОВА: дозволені target лише restore_test або $PRODUCTION_TARGET"
    exit 2
fi
if [ "$TARGET" = "$PRODUCTION_TARGET" ] && [ "$CONFIRMATION" != "$PRODUCTION_CONFIRMATION" ]; then
    log "ВІДМОВА: production restore потребує exact explicit confirmation token"
    exit 2
fi
if [ "$TARGET" != "$PRODUCTION_TARGET" ] && [ -n "$CONFIRMATION" ]; then
    log "ВІДМОВА: production confirmation не дозволена для test target"
    exit 2
fi
if ! gzip -t "$DUMP"; then
    log "ВІДМОВА: backup artifact не пройшов gzip integrity validation"
    exit 1
fi

log "preflight OK: target=$TARGET, backup=$DUMP"
if [ "$DRY_RUN" = true ]; then
    log "dry-run: destructive restore не виконувався"
    exit 0
fi

cd "$STACK_DIR"
psql() { docker compose exec -T db psql -U avelren "$@"; }

log "готую базу $TARGET"
psql -d postgres -v target="$TARGET" -q \
    -c 'DROP DATABASE IF EXISTS :"target";' \
    -c 'CREATE DATABASE :"target";'
psql -d "$TARGET" -q -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"

log "timescaledb_pre_restore"
psql -d "$TARGET" -q -c "SELECT timescaledb_pre_restore();"

log "відновлення даних"
gunzip -c "$DUMP" | psql -d "$TARGET" -q

log "timescaledb_post_restore"
psql -d "$TARGET" -q -c "SELECT timescaledb_post_restore();"

log "перевірка"
psql -d "$TARGET" -c "
SELECT (SELECT count(*) FROM observations)  AS спостережень,
       (SELECT count(*) FROM checkpoints)   AS кпп,
       (SELECT count(*) FROM timescaledb_information.hypertables) AS гіпертаблиць,
       (SELECT count(*) FROM timescaledb_information.continuous_aggregates) AS агрегатів;"

log "готово: база $TARGET"
