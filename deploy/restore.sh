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
#
# Без другого аргументу відновлює в restore_test, а не в бойову базу:
# помилитись і затерти прод має бути важче, ніж перевірити копію.
#
set -euo pipefail

STACK_DIR=/opt/avelren
DUMP=${1:?вкажіть файл дампа}
TARGET=${2:-restore_test}

log() { echo "$(date -u +%FT%TZ) $*"; }

if [ "$TARGET" = "avelren" ]; then
    log "УВАГА: відновлення в БОЙОВУ базу. Ctrl+C протягом 10 секунд, щоб скасувати."
    sleep 10
fi

cd "$STACK_DIR"
psql() { docker compose exec -T db psql -U avelren "$@"; }

log "готую базу $TARGET"
psql -d postgres -q -c "DROP DATABASE IF EXISTS $TARGET;" -c "CREATE DATABASE $TARGET;"
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
