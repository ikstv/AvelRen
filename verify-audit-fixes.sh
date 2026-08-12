#!/usr/bin/env bash
# Повна перевірка фіксів аудиту 2026-08-12. Запускати З КОРЕНЯ репозиторію
# AvelRen на сервері (або будь-де, де є Docker + Python3):
#
#     bash verify-audit-fixes.sh          # швидкі перевірки (безпечні, ~хвилина)
#     bash verify-audit-fixes.sh --full   # + повний бекенд-набір (спінить
#                                          #   одноразову test-БД через compose)
#
# Нічого не чіпає продакшн-дані: контрактні тести фейкані, backend-набір
# піднімає ізольовану disposable-БД з env-guard. Друкує підсумок PASS/FAIL.
set -uo pipefail

cd "$(dirname "$0")"
FULL=0
[ "${1:-}" = "--full" ] && FULL=1

pass=0; fail=0; skip=0
declare -a RESULTS

run() {
    local name=$1; shift
    printf '\n\033[1m=== %s ===\033[0m\n' "$name"
    if "$@"; then
        RESULTS+=("PASS  $name"); pass=$((pass+1))
    else
        RESULTS+=("FAIL  $name"); fail=$((fail+1))
    fi
}
skipmsg() { RESULTS+=("SKIP  $1"); skip=$((skip+1)); printf '\n\033[33m=== SKIP: %s ===\033[0m\n' "$1"; }

# --- Контекст ---------------------------------------------------------------
printf '\033[1mРепозиторій:\033[0m %s\n' "$(pwd)"
if command -v git >/dev/null; then
    printf 'Гілка: %s  HEAD: %s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')" \
        "$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
    printf 'Змінені/нові файли:\n'; git status --short 2>/dev/null | sed 's/^/  /'
fi

# --- Наявність ключових файлів фіксів ---------------------------------------
check_files() {
    local ok=0 f
    for f in \
        deploy/restore-allowlist-contract-test.py \
        deploy/backup.sh deploy/restore-production.sh \
        app/src/avelren/watchdog.py app/src/avelren/forecast.py \
        app/src/avelren/api.py app/src/avelren/subscriptions_api.py \
        android/app/src/main/java/ua/avelren/app/data/DeviceStore.kt
    do
        if [ -f "$f" ]; then printf '  ok   %s\n' "$f"; else printf '  МІСЯ %s\n' "$f"; ok=1; fi
    done
    # Маркери, що фікси справді в коді:
    grep -q "AT TIME ZONE 'Europe/Kyiv'" app/src/avelren/forecast.py || { echo "forecast M-7 маркер відсутній"; ok=1; }
    grep -q 'backup_stale' app/src/avelren/watchdog.py || { echo "watchdog M-12 маркер відсутній"; ok=1; }
    grep -q 'health:{kind}' app/src/avelren/watchdog.py || { echo "watchdog M-10 маркер відсутній"; ok=1; }
    grep -q 'AND t.is_active' app/src/avelren/subscriptions_api.py || { echo "M-16 маркер відсутній"; ok=1; }
    grep -q 'pre-restore' deploy/restore-production.sh || { echo "M-13 маркер відсутній"; ok=1; }
    grep -q 'type = crypt' deploy/backup.sh 2>/dev/null; grep -q 'crypt' deploy/backup.sh || { echo "M-11 маркер відсутній"; ok=1; }
    return $ok
}
run "Файли фіксів на місці" check_files

# --- H-1: перевірка дрейфу allowlist ----------------------------------------
if command -v python3 >/dev/null; then
    run "H-1 restore allowlist drift" python3 deploy/restore-allowlist-contract-test.py
else
    skipmsg "H-1 (немає python3)"
fi

# --- Фейкані deploy-контрактні тести (безпечні, без БД) ----------------------
for t in backup-contract-test.sh restore-contract-test.sh restore-engine-contract-test.sh \
         restore-production-contract-test.sh compose-security-contract-test.sh; do
    if [ -f "deploy/$t" ]; then
        run "deploy/$t" bash "deploy/$t"
    else
        skipmsg "deploy/$t (немає)"
    fi
done

# --- ruff (якщо є) ----------------------------------------------------------
if command -v ruff >/dev/null; then
    run "ruff (app/src)" ruff check app/src/avelren
else
    skipmsg "ruff (не встановлено)"
fi

# --- Повний бекенд-набір (--full): pytest на одноразовій test-БД -------------
if [ "$FULL" = 1 ]; then
    if [ -x scripts/backend-test.sh ] || [ -f scripts/backend-test.sh ]; then
        run "backend-test.sh (pytest на disposable БД)" bash scripts/backend-test.sh
    else
        skipmsg "scripts/backend-test.sh (немає)"
    fi
else
    skipmsg "повний бекенд-набір (запусти з --full)"
fi

# --- Підсумок ---------------------------------------------------------------
printf '\n\033[1m========== ПІДСУМОК ==========\033[0m\n'
for r in "${RESULTS[@]}"; do
    case "$r" in
        PASS*) printf '\033[32m%s\033[0m\n' "$r" ;;
        FAIL*) printf '\033[31m%s\033[0m\n' "$r" ;;
        *)     printf '\033[33m%s\033[0m\n' "$r" ;;
    esac
done
printf '\nPASS=%d  FAIL=%d  SKIP=%d\n' "$pass" "$fail" "$skip"
[ "$fail" -eq 0 ] && { echo "УСЕ ЗЕЛЕНЕ ✅"; exit 0; } || { echo "Є ПРОВАЛИ ❌ — дивись FAIL вище"; exit 1; }
