# Production adoption PostgreSQL 001–016 — процедура переходу

> Уточнення 14.10.2026: [свіжий read-only аудит](audits/POSTGRES-CUTOVER-READINESS-2026-10-14.md)
> підтвердив повний privilege gate PASS і чинне application ownership.
> Не застосовувати ownership/ACL повторно на підставі старого припущення.
> Credentials обох dedicated ролей перевірені; watchdog column grants
> дозволяють точний admin SELECT. Часткове exact-image приймання пройшло;
> recreate/rollback ще потребують перевірки. Runtime manifest не містить
> container ID, автоматичний rebind не є передумовою. Legacy Timescale jobs лишаються окремою
> темою. Перевірка не дозволяє production-запис. Нижчий статус 11.10
> збережено як історію підготовки, а не поточний доказ стану каталогу.

Дата: 11.10.2026. Статус: DB executor реалізований і перевірений як source
кандидат етапу 1; публічний production CLI закритий. Реальний maintenance
adapter і operational acceptance попереду. Документ не є дозволом на операцію.

## Походження та чинний контракт

Джерело — [AvelRen-ops 5be9da8, deploy/postgres-adoption-runbook.md](https://github.com/ikstv/AvelRen-ops/blob/5be9da8b433813a664b4d4e21a0a92bae91c56a0/deploy/postgres-adoption-runbook.md),
SHA-256 `2f72ab932f64830fea9ed29f10b06aeb49af3ab85de746cb2a4ffe50b0edb57a`.
Механіка старого AvelRen: [postgres-adopt.sh та ownership library](https://github.com/ikstv/AvelRen/tree/4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27/deploy).

Поточна основа — [privilege gate](../ops/POSTGRES-PRIVILEGE-GATE.md)
і [disposable adoption](../ops/POSTGRES-ADOPTION.md), прийняті PR #106/#107.
Forward/inverse застосовуються лише до application ownership/ACL;
журнал, applied_at, application data, визначення функцій і системні об'єкти
не змінюються. Цільові сім обмежених ролей: `avelren_backup`,
`avelren_collector`, `avelren_notifier`, `avelren_watchdog`, `avelren_api`,
`avelren_surge`, `avelren_migrator`. Адміністративна `avelren_admin` за
чинним контрактом лишається superuser; її retirement не належить цьому переходу.

| Припущення старої процедури | Адаптація для ORIGINAL |
| --- | --- |
| Schema 009, grants зі старої 010, пізніше stamp 010 | Точний журнал 001–016 та SHA чинних source migrations; жодного повторного stamp або редагування міграцій |
| Старий shell production executor | Python DB executor має окремий production API із target/manifest/receipts; production CLI закритий до maintenance adapter |
| П'ять служб, включно з Caddy | Окремо ingress Caddy та всі DB clients, включно з `surge_worker` і фактичним collector spool runtime |
| Повернення всіх клієнтів на legacy DSN | Зберегти фактичні DSN кожної служби: API/notifier/worker уже можуть бути обмеженими |
| Старі exit codes 0/3 | Не переносити значення 3 як «committed, restart failed»: у disposable CLI 3 означає rollback_failed |
| Clean checkout старого deploy source | Окремий clean, перевірений кандидат; dirty working checkout сервера зберігати до звірки, не чистити примусово |

## Передумови до першого запису

1. Свіжий read-only аудит host/container identities, активних image digests,
   Compose project/service names, override файлів, міграцій та ролей.
   [Аудит 11.10](audits/MIGRATION-SERVER-2026-10-11.md) — орієнтир,
   а не автоматично чинний preflight майбутньої операції.
2. Актуальний backup доступний поза сервером, checksum перевірений,
   recovery перевірено в ізольованій БД. Успіх timer або синтетична
   restore-репетиція не замінюють приймання цього артефакту.
3. Підтверджено PostgreSQL 16, TimescaleDB 2.30.1, journal 001–016,
   compressed chunks та continuous aggregate у підтримуваній топології.
   Інша версія, relation layout, function/role drift — відмова до запису.
4. Потрібні ролі вже існують; відсутні/надмірні права не виправляються
   побічно. Provisioning або ротація — окрема зміна й окремий GO.
   Обліковий запис executor має підключатися також до фіксованої maintenance
   DB `postgres` на тому самому сервері та читати control/database identity.
   Production lifecycle guard не має альтернативної або fallback DB;
   відсутність цього доступу блокує операцію до target mutation.
   Активний autovacuum також не проходить production quiescence; майбутня
   maintenance процедура має врахувати його окремо. Вимкнення autovacuum у
   isolated database/adoption/upgrade fixtures не є production інструкцією чи
   дозволом; ці fixtures не перевіряють natural autovacuum scheduling.
5. Evidence приватне: каталог 0700, файли 0600, власник оператор,
   абсолютний шлях поза checkout, без symlink/hardlink і перезапису.
   Credentials тільки через захищене середовище, не argv, Git або logs.
6. Production executor, maintenance orchestration та відкат мають
   ізольовані докази, незалежний review, exact-head CI і злиття.
   DB executor source перевірений ізольовано; actual maintenance adapter,
   whole-branch review, exact-head CI та integration ще не прийняті цим записом.

## Окремі операції та точки зупинки

### A. Підготовка і read-only inventory

Зафіксувати конкретний source commit, цільову DB/server identity,
підтримувану topology та before fingerprint. План генерується з приватного
catalog snapshot; SQL повторно генерується з перевіреного inventory.
Записи application data й паролі не включати в evidence.
Невідповідність checksum, цілі або журналу припиняє процедуру.

Поточні `inventory`, `plan`, `inspect` описані в
[adoption CLI](../ops/POSTGRES-ADOPTION.md). Їх наявність не встановлює CLI
на сервер і не дозволяє записувати evidence на production host під час аудиту.

### B. Maintenance та ownership/ACL adoption — окремий GO

До запуску власник погоджує конкретний plan digest, ціль, maintenance window
та спосіб відкату. Контракт source executor перевіряє confirmation,
прив'язаний до operation ID, цілі й плану; інтерактивний операторський CLI
належить майбутньому maintenance adapter. Універсального
токена або обходу test guard немає.

Операторський сценарій має:

- Узгодити backup/retention/telemetry, інші DB clients і Timescale background
  jobs; невідома активна сесія або непідтримувана фонова робота — відмова.
- Перекрити ingress, зупинити фактичні API, collector, notifier, watchdog
  та surge worker; підтвердити фактичну зупинку. Не видаляти SQLite spool,
  volumes, контейнери чи дані й не завершувати чужі DB sessions примусово.
- Після зупинки повторити catalog capture. Новий chunk між початковим
  inventory та maintenance — нормальна причина відмови при drift;
  чужу зміну не перезаписувати, план переглянути заново.
- Отримати advisory/object locks до repeatable-read snapshot і повторно
  звірити fingerprint, сесії, journal та дозволену topology перед SQL.
- Опублікувати apply-intent, виконати лише ownership/ACL forward,
  перевірити expected fingerprint і commit. Потім записати committed
  receipt, виконати read-only privilege gate й acceptance receipt.

Production executor утримує окремий database-wide session advisory lock від
початкової target перевірки до завершення receipt/acceptance. Guard працює в
`postgres` після звірки cluster/session/target identity, тому не послаблює
перевірку target sessions. Один ключ охоплює різні operation IDs/evidence paths
для тієї самої target DB. Конкурентний apply або inverse отримує
`production_operation_busy`; він не може вклинитися між fresh capture та
accepted receipt іншої операції. Володіння lock перевіряється без повторного
захоплення перед acceptance; після release connection закривається. Втрата
guard або непідтверджене звільнення після можливого COMMIT означає
`commit_unknown`, навіть якщо accepted файл уже опублікований. Автоматичних
повторів, inverse чи runtime restart у такому стані немає.

Цей етап не змінює DSN, паролі або ролі й не застосовує міграції.
Перезапуск можливий лише після підтвердженого DB outcome, на збережених
для кожної служби DSN та exact images. Потрібні повний фактичний Compose
набір із override, явні service names і `--no-deps`; голий `compose up`
або навіть список служб без `--no-deps` може неочікувано запустити migrate.
Ingress повертається після API/collector/worker перевірок.
Restart failure після прийнятого adoption не означає DB rollback.

### C. Runtime DSN cutover — окремий GO

Переходити лише для служб, які ще використовують legacy superuser,
по одній службі з окремим збереженням попереднього секретного DSN.
DB ownership/ACL adoption не доводить runtime cutover.

Підтверджувати фактичний database session user, дозволені/заборонені
операції та робочий сценарій кожної служби. Для collector:
успішний новий цикл, 60-секундний інтервал, незмінний Device ID,
збереження кожного циклу і стану spool. Не додавати upstream probes.
Для watchdog — DB acceptance та штатний щоденний звіт;
FCM acceptance не є доказом показу на телефоні.

Відкат cutover повертає попередній DSN конкретної служби та перевірений
runtime; він не запускає ACL inverse автоматично.

### D. Soak і retirement — окремий GO

Після погодженого періоду спостереження підтвердити, що жодна служба,
backup, timer або operator procedure не залежить від legacy `avelren`.
Retirement не є автоматичним завершенням adoption і не виконується
через REASSIGN OWNED/DROP OWNED. Перед зміною LOGIN/SUPERUSER потрібні
інвентаризація залежностей, спосіб відкату й окреме погодження.

## Помилки та відкат

| Стан | Дія оператора |
| --- | --- |
| Refused до mutation | Нічого не виправляти автоматично; якщо maintenance вже почався, стан служб оцінити окремо перед поверненням |
| Помилка до COMMIT | Transaction rollback, перевірка before fingerprint; непідтверджений стан не називати rolled_back |
| COMMIT acknowledgement втрачено | commit_unknown; не повторювати COMMIT/apply, не робити автоматичний inverse, залишити maintenance і провести read-only діагностику |
| Receipt/acceptance втрачено після COMMIT | commit_unknown; лише відсутність receipt не доводить rollback |
| Підтверджений post-commit acceptance failure | Inverse тільки за валідних intent/committed records, plan hash і exact expected fingerprint; сторонній drift зберегти |
| Inverse failure або неочікуваний fingerprint | rollback_failed; залишити maintenance, не запускати runtime автоматично |
| Adoption прийнятий, клієнт не запустився | Окремий runtime failure; перевірити й відновити службу, не називати DB adoption невдалим лише через restart |

Inverse повертає ownership/ACL, включно з grantors/defaults/columns/functions,
але не змінює дані, журнал або застосовані міграції. Production inverse CLI
поки відсутній. `apply-test` не застосовувати до live DB і не обходити guards.
Поточний [restore orchestrator](../ops/restore-production.sh) не є adoption
executor; його spool/worker обмеження не обходити заради цієї процедури.

## Що ще потрібно реалізувати

DB executor/confirmation contract, session/job gates, receipts та explicit
inverse реалізовані як source кандидат (`c84d0a9..69c25cc`). Isolated tests
перевіряють forward/inverse, compressed chunks/CAGG, journal/data/function
preservation, lock waits, foreign drift і невизначений COMMIT/receipt outcome.
Two-cluster rehearsal перевіряє відмову чужої цілі за однакових dbname/catalog/
plan та незмінність ACL/data обох кластерів. Physical-clone unit case доводить
виклик injected runtime gate, а не реальну перевірку host provenance.

Наступний етап реалізує actual maintenance adapter: фактичні host/Compose/
image/override manifests і checkout provenance; stop/start усіх DB clients,
timers та job pause/resume; операторський CLI і restart/failure-state acceptance
(включно з runtime rc 5). Production apply/inverse CLI залишається закритим
до його приймання. Runtime DSN cutover — окремий план.
Після source review/CI/integration потрібні свіжий backup/preflight, окремий
GO та operational приймання adoption, cutover і soak. Сервер, active DSN,
collector spool і APK цим source етапом не змінені.
