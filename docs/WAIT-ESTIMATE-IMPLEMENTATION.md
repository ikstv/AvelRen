# Виконання контракту відсутньої оцінки

30.09.2026. Issue #70; legacy #111. Робоча гілка codex/wait-estimate-contract.
Специфікація й план — у docs/superpowers. Це незавершений кандидат,
не готовий до merge/deployment до підключення нового збереження й API.

## Крок 1

WorkloadItem приймає omitted/null як None, справжній 0 зберігає як 0;
статус виводиться з оцінки та не підміняється стороннім полем.
Тільки невід'ємний JSON integer; інші типи дають parse-помилку.
Новий wait_estimate.py централізує правило читання й виміряний ETA.
Позитивний paused wait збережено; paused/0 не дає ETA.

TDD: базові 201 unit пройшли; нові тести до правки — 31 failed/29 passed;
після правки весь unit набір — 234 passed. Два попередні deprecation
warnings Starlette/httpx/anyio зберігаються. Ruff успішний.
HTTP тільки MockTransport; production та upstream не використовувалися.

CORE-PROVENANCE зберігає вихідні SHA-256 і додає revision для моделі
та HTTP-тестів. Нові helper і unit-test файли — власний код проєкту.

Схема, DB persistence, API/Android, restore/rollback ще потребують
виконання наступних кроків. Nullable-модель не розгортати окремо:
старий insert_observations не зберігає статус і не приймає None.
