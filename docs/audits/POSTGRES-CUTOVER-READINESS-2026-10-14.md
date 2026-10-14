# Готовність переходу PostgreSQL DSN — 14.10.2026

Свіжа read-only перевірка уточнила старе припущення, що перед переходом
обов'язково потрібне повторне перенесення application ownership/ACL.
**Повний чинний privilege gate пройшов: PASS, violations=[]**;
журнал міграцій точно відповідає 001–016 із перевіреними SHA.
Це не доказ сумісності старих процесів з обмеженими DSN і не дозвіл
виконати production-перемикання.

## Що перевірено

Gate виконувався незміненим кодом у наявному API-контейнері в read-only
транзакції; source migrations передано в пам'яті, без запису файлів на сервер.
SHA-256 коду gate:
`b74a4bd7ca64bd7c7b1ee5c398e1b371af5a5eb6677133032c56b47d7445f08c`.

| Область | Фактичний стан |
| --- | --- |
| PostgreSQL / TimescaleDB | 16.15 / 2.30.1 |
| Application ownership | Усі перевірені public relations і чотири functions належать `avelren_migrator` |
| Сім обмежених ролей | Існують, NOINHERIT, не superuser, без memberships; повний gate не виявив порушень |
| API / notifier / surge | Використовують власні обмежені ролі |
| Collector / watchdog | Досі використовують legacy `avelren`; їх перемикання не виконано |
| Timescale jobs | Чотири jobs scheduled із legacy owner; це не доводить можливість retirement старої ролі |

Внутрішні Timescale об'єкти не ототожнюємо з public application relations;
успішний application gate не є дозволом масово змінювати extension ownership.
Не слід повторно застосовувати ownership/ACL лише через старі формулювання
плану. Перед будь-яким записом фактичний стан треба перевірити знову.

## Стан сервісів на час звірки

Перевірка 14.10.2026 о 15:41:13 за Києвом: сім контейнерів незмінні,
RestartCount=0, capture-only вимкнений, pending=0, last_error відсутній.
API health, alert_channel та undelivered_alerts — `ok`; timestamp останнього
спостереження 15:40:53, вік 20 с. Штатний backup timer enabled/active;
наступний запуск за цим readback — 15.10 о 06:22:18 за Києвом.
Це датована звірка, не безперервна гарантія health.

Реальну off-host PostgreSQL+SQLite пару вже прийнято окремою
[ізольованою репетицією](PAIRED-LEGACY-RESTORE-2026-10-14.md).
Її legacy NOLOGIN placeholder не доводить роботу production background jobs
і не замінює репетицію конкретного DSN cutover.

## Наступна перевірка та межі

Чинні dedicated credentials collector/watchdog вже перевірені read-only
підключенням із точним `session_user`; паролі та DSN не публікувалися.
Це не перевірка всіх шляхів виконання фактичних образів.

Watchdog не має підтвердженого permission blocker для admin-token запиту:
міграція 010 надає COLUMN SELECT на `id`, `is_admin`, `fcm_token` і UPDATE
на `fcm_token`. Ці grants підтверджені; точний admin SELECT з умовою,
що не повертає рядків, пройшов під `avelren_watchdog` без читання токенів.
Відсутність table-level SELECT не означає відсутність column privileges.
Live daily/recovery → notify → admin_tokens SQL збігається з ORIGINAL;
UPDATE та реальну FCM-відправку під час аудиту не виконували.
Наступна перевірка — isolated daily/recovery/dead-token сценарії з mocked FCM
і точними column grants, без нового grant або production source fix.

Для collector потрібне isolated приймання точного чинного image з dedicated
role: повний цикл, alerts і replay, без додаткових запитів до upstream.
Успішні auth та базові права SQL ще не доводять всю runtime-сумісність.
Зміна DSN в environment вимагає recreate конкретного контейнера;
restart не оновлює його environment. Collector runtime і paired-backup
manifests прив'язані до container ID: перехід має узгоджено перевипустити
та перевірити bindings, зберігши spool volume/network. Identity guard
не обходити; timer відновлювати лише після приймання нової identity.
Watchdog використовує п'ять ordered Compose файлів, включно з його
activation override; загальний чотирифайловий stack не є еквівалентним.

Потрібні перевірений точний rollback кожної служби та окремий конкретний GO.
Операцію слід готувати по одній службі зі збереженням image/source,
60-секундного collector контракту і Device ID; не додавати ACL inverse,
міграції або retirement legacy role до DSN cutover. Формальний adoption
planner не запускався; no-op plan digest не заявляється. Timescale jobs
залишаються scheduled із legacy owner; gate їх не змінював.

Цей аудит не змінював ownership/ACL, passwords, DSN, jobs або контейнери.
Попередня межа простою до 15 хвилин не замінює конкретний дозвіл власника
на нову операцію БД. Поточний наступний етап — обмежена підготовка DSN
cutover; старий розширений maintenance-план не поновлюється автоматично.
[Runbook](../POSTGRES-ADOPTION-PRODUCTION-RUNBOOK.md) зберігає вимоги
preflight, резервної копії, перевірки результату й відкату.
