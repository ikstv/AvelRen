#!/usr/bin/env bash
#
# Перевірка відновленої БД (A-07 / DR restore contract).
#
# Restore вважається доведеним не тоді, коли «counts зійшлися», а коли:
#   * історія міграцій точно відповідає файлам (версії + SHA);
#   * фізична схема ціла (критичні таблиці/колонки/індекси, hypertable,
#     continuous aggregate) — schema_verify;
#   * справжній застосунок піднімається проти цієї БД і проходить auth-smoke —
#     restore_smoke.
#
# Запускати ЛИШЕ проти disposable-бази (типово restore_test). Проти бойової
# `avelren` скрипт свідомо відмовляється: smoke створює тестовий рядок devices,
# і робити це на проді не можна. Production restore тут теж не виконується.
#
# Використання:
#   avelren-restore-verify [ім'я_бази]     # типово restore_test
#
set -euo pipefail

STACK_DIR=/opt/avelren
TARGET=${1:-restore_test}

if [ "$TARGET" = "avelren" ]; then
    echo "ВІДМОВА: verify проти бойової бази avelren заборонено (A-07)." >&2
    exit 2
fi

cd "$STACK_DIR"

# Базовий DSN береться з .env (він для avelren); підмінюємо лише назву бази на
# TARGET, зберігаючи логін/пароль/хост.
base_dsn=$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)
if [ -z "$base_dsn" ]; then
    echo "ВІДМОВА: DATABASE_URL не знайдено в .env" >&2
    exit 2
fi
target_dsn="${base_dsn%/*}/$TARGET"

run_in_app() {
    sudo docker compose run --rm -T -e "DATABASE_URL=$target_dsn" migrate "$@"
}

echo ">>> schema_verify (історія + фізичний контракт) проти $TARGET"
run_in_app python -m avelren.schema_verify /migrations

echo ">>> restore_smoke (health + auth + devices/secret) проти $TARGET"
run_in_app python -m avelren.restore_smoke

echo "restore-verify OK: $TARGET"
