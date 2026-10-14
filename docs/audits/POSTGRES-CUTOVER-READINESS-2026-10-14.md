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
Live daily → notify → admin_tokens SQL збігається з ORIGINAL;
UPDATE та реальну FCM-відправку під час аудиту не виконували.
Наступна перевірка — isolated daily/incident-resolution/dead-token сценарії з mocked FCM
і точними column grants, без нового grant або production source fix.

Для collector потрібне isolated приймання точного чинного image з dedicated
role: повний цикл, alerts і replay, без додаткових запитів до upstream.
Успішні auth та базові права SQL ще не доводять всю runtime-сумісність.
Зміна DSN в environment вимагає recreate конкретного контейнера;
restart не оновлює його environment. Runtime manifest містить дев'ять полів і не містить container ID;
[preflight](../../ops/collector-runtime-preflight.py) перевіряє фактичний
контейнер за чинним контрактом. [Paired coordinator](../../ops/paired-backup.py)
прив'язує поточну identity до окремого покоління backup: попередній terminal
state допускається, перед новим поколінням перевіряється поточний контейнер.
Тому обов'язковий rebind manifest лише через новий ID не обґрунтований.
Потрібні точний recreate-контракт, збереження spool volume/network та перевірка
preflight/identity перед відновленням timer; identity guard не обходити.
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

## Доповнення: часткове приймання точних runtime images — 14.10.2026

Уточнення раніше опублікованого висновку цього аудиту: припущення про
обов'язковий manifest rebind через container ID та окремий recovery-push
шлях як передумову переходу відкликані після звірки встановленого контракту
і live `run_cycle`. Вище наведено виправлені вимоги; початковий висновок
збережений у Git-історії PR #134 і не є чинною передумовою.

Після окремого дозволу отримано два immutable Docker images; production
дані для цих тестів не використовувалися. Перевірені image IDs:

- Collector: `sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3`.
- Watchdog: `sha256:77e55b1dc74dac65a665ab1e0fd00269a62b821bd337fcf957b600b006e257af`.

Перший успішний прогін дав **14 PASS**: 9 watchdog reporting; 4 collector
FIFO/idempotency/conflict; 1 synthetic producer із п'ятьма циклами під час
недоступності БД та наступним replay під обмеженою роллю. Це exact-image
перевірка: кожен pytest-процес підтвердив шлях установленого package й SHA
завантажених модулів. Поточний source не підміняв runtime; додано лише
offline test tooling. Використано synthetic DB, dedicated roles і точні
column grants, internal network, mocked FCM та заборону зовнішнього HTTP.

Перша спроба зупинилася до збору тестів через відсутній компонент pytest
tooling; це не runtime failure. Після виправлення лише tooling повторна
спроба пройшла. Harness/driver не змінювалися під час прийнятого прогону.
Власні сім контейнерів, tools volume і network видалені; два імпортовані
images прибрані без force/prune, архів після load видалений. Збережено
лише metadata та докази; production runtime не змінювався.

Додаткова звірка [watchdog run_cycle](../../services/backend/src/avelren/watchdog.py)
підтвердила: чинний цикл виконує incident resolution і daily reporting,
але не викликає dormant `_deliver_recoveries`. Incident resolution уже
охоплений дев'ятьма прийнятими watchdog тестами. Новий recovery push не
є передумовою DSN cutover і не додається як побічна функція.

Наступний точковий прогін того самого exact collector image завершився
**1 PASS за 1,99 с**: три synthetic цикли, створення fresh alert,
обмежені collector/notifier roles і mocked delivery. Installed-package
provenance підтверджений. Notifier module походив із collector image:
це не приймання іншого production notifier image. Архів, чотири власні
контейнери, tools volume, network та імпортований image цього прогону
також видалені. Попередні 14 тестів не повторювалися; разом **15 PASS**.

Fresh-derived SQL шлях закритий цим focused case. Далі потрібна конкретна
перевірена процедура DSN cutover з private rollback/env/Compose, recreate
лише цільової служби та runtime/identity acceptance після зміни.
**Production DSN cutover не виконано**; ці тести не доводять фактичний
production recreate/restart. Автоматичне переписування runtime manifest
лише через новий container ID не потрібне за перевіреним контрактом вище,
але незавершене покоління backup блокує recreate. Успішні 15 тестів не
замінюють окремий production GO й не закривають долю legacy Timescale jobs.
