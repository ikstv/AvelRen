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

## Крок 2 — кандидат, перевірка БД ще триває

Новий INSERT зберігає missing як технічний 0 з окремим статусом,
не гублячи кількість автомобілів. Міграція 015 додає статус із default
legacy_unknown та CHECK; старі міграції й історія не редагуються.
Schema contract піднімає вимогу нового runtime до 015.
CORE-PROVENANCE зберігає джерело та фіксує revisions db/schema_verify.

RED: isolated database CI на bf495415 — 2 нові тести failed, 22 passed
(колонка відсутня); локальні тести запису — 3 failed.
Після правки 237 unit passed, Ruff успішний. Compressed DDL, повний
pipeline, API/Android і restore/rollback ще не підтверджені.
Цей кандидат не готовий до merge або production deployment.
