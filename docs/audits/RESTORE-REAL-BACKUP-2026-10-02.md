# Реальне відновлення backup — 02.10.2026

Датований доказ для [issue #41](https://github.com/ikstv/AvelRen-ORIGINAL/issues/41).
Власник окремо дозволив локальне завантаження копії та серверну ізольовану
репетицію. Цей запис не є дозволом на зміну production runtime.

## Джерело й цілісність

| Артефакт | Значення |
| --- | --- |
| Код | `857eb61e5a6c2ea35ca0c1648a55d89ecf7aa7fd` — main після PR #77 |
| Source-пакет | 54 файли, 368640 байтів: native restore CLI/engine/verify/bootstrap, db, backend source |
| SHA-256 source-пакета | `74388d353969094dfd964a190a54d6145cb643e9b867e3b47b033b0cc0de093d` |
| Backup | `gdrive-crypt:avelren/daily/avelren-20261002-070701.sql.gz` |
| Розмір backup | 6900137 байтів |
| SHA-256 backup | `a4b855a6a0cbcf8ae83a9b3633f7ecafb8afa54bb3f81115aca530a5aed4803f` |
| Перевірки артефакту | Розмір, SHA-256 і повний gzip integrity — PASS |
| Формат | pg_dump 16.6, PostgreSQL 16.6, міграції 001–014 |

Локальну репетицію завершено о **10:50:13 за Києвом**; серверну — о
**11:00:19**, фінальну перевірку очищення й collector — о **11:01:15**.
Усі часи — 02.10.2026 (UTC+03:00).

## Ізоляція та сумісність

- Окремий проєкт `avelren-restore-issue41-20261002-857eb61e`, власний
  том і внутрішня мережа, без published ports та production volumes.
- `AVELREN_COMPOSE_ENV_GUARD=isolated` усередині DB; native CLI підтримує
  лише `restore_test`, усі Compose contexts задано явно.
- TimescaleDB 2.17.2, той самий образ, що у робочого DB:
  `sha256:4e459e217f00cbb09920c34d245501e63427e6767a495de57ce76823ff280f12`.
  DB обмежено 768 МБ / 1 CPU.
- Сім одноразових тестових паролів, native fresh bootstrap в окрему
  `avelren_issue41_bootstrap_test`; legacy роль `avelren NOLOGIN` створено
  лише в disposable cluster для Timescale job owner із dump.
- Перевірки Python використовують source exact main readonly; залежності
  із вже наявного образу
  `sha256:1ab8437b7e789ec44a6971604bd56d9c43a1117c04278cb5faf550ca7d3235a1`.
  По 256 МБ / 0,5 CPU, UID 10001, cap_drop ALL, no-new-privileges.
- `compose run --rm --no-deps`: не запускає collector/notifier/watchdog,
  не опитує єЧергу й не може reconcile робочий DB.

## Результат штатної процедури

| Етап на сервері | Exit code | Час, секунд |
| --- | --- | --- |
| Disposable DB start | 0 | 9,23 |
| Native fresh roles | 0 | 0,71 |
| Legacy NOLOGIN compatibility role | 0 | 0,19 |
| Guarded restore, Timescale pre/post hooks, ownership finalization | 0 | 7,43 |
| Native schema verify й API smoke | 0 | 11,17 |
| Safe counts | 0 | 0,49 |
| Очищення власного Compose-проєкту | 0 | 0,71 |

Відновлено **3026358 observations**, **38 checkpoints**, **14 міграцій**.
`timescaledb.restoring=off`. Native schema verify перевірив історію/хеші
міграцій і фізичний контракт схеми через `avelren_migrator`. API smoke
через `avelren_api` перевірив identity guard, health із реальними observations,
401 без auth, тестову реєстрацію пристрою та 200 для protected request.
Його записи виконувалися лише в disposable `restore_test`.

## Очищення й робочий сервер

- Власних контейнерів, мереж і томів за label проєкту не залишилося.
- Backup, Compose із тестовим паролем, env, source та upload-каталог видалено.
- Зберігся лише безпечний `BENCH.json` 0600 у root-owned каталозі 0700
  `/var/lib/avelren-restore-rehearsal/issue41-20261002-857eb61e/`.
- ID/image/restarts/started усіх шести робочих служб, checkout/status,
  хеші старих Compose і restore-файлів збігаються зі зрізом перед тестом.
  Робочі служби не зупинялися й не recreate.
- Health API й alert channel — `ok`.
- Останні п'ять collector циклів **10:56:21–11:00:21 за Києвом**: усі HTTP 200,
  по 38 observations, derived complete, інтервали 60 секунд.
  SQLite: 461 acked, **pending=0**. Звірка — readonly.

## Що залишається для issue #41

Реальне відновлення перевіреним main **на ізольованому серверному стенді
підтверджено**. Старі `/opt/avelren/deploy/restore*.sh` не замінювалися;
встановлений production restore runtime ще не прийнято як узгоджений з main.
Issue #41 лишається відкритою до окремої перевіреної адаптації/встановлення
runtime після конкретного дозволу та перевірки його фактичного результату.

Ця репетиція не перевіряє перехід прав живої БД, production restore
orchestrator зі spool, оновлення TimescaleDB, RTO/RPO, APK, телефон або Play.
Безпечний JSON доказу також збережено локально в ignored dist; SQL,
тестові паролі, PIN, токени та installation IDs не додані в Git.
