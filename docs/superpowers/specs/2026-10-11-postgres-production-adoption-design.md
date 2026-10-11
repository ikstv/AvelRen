# Production adoption PostgreSQL 001–016: специфікація для перегляду

Дата: 11.10.2026. Статус: підхід і письмову специфікацію погоджено
власником 11.10.2026. Етап 1 реалізований та ізольовано перевірений як
source кандидат; публічний production CLI закритий. Actual maintenance
adapter, DSN cutover і operational acceptance не виконані. Whole-branch
review, exact-head CI та integration ведуться окремими gates у
[плані](../plans/2026-10-11-postgres-production-executor.md).

## Мета й погоджені межі

Завершити перенос ownership/ACL механізму двох старих репозиторіїв до
AvelRen-ORIGINAL без втрати даних, журналу міграцій або collector spool.
Власник погодив розширення перевіреного Python-механізму та окремі етапи
maintenance і DSN cutover. Підготовка коду не дозволяє операцій на сервері.

Основи: ORIGINAL main `aa1d879dd868e59f93f9bba53567eb34dac6de53`,
disposable executor PR #107, privilege gate PR #106 та
[production runbook PR #120](../../POSTGRES-ADOPTION-PRODUCTION-RUNBOOK.md).
Frozen legacy sources і їхні контрольні суми наведені в runbook.
[Аудит 11.10](../../audits/MIGRATION-SERVER-2026-10-11.md) встановив:
collector/watchdog використовують legacy superuser, API/notifier/surge
worker уже мають окремі обмежені ролі. Перед deployment це перевіряємо знову.

Результат: перевірений executor forward/inverse, керування maintenance
для фактичної topology та окреме приймання DSN cutover. Застосовані
міграції 001–016, дані, функції, паролі й адміністративні ролі не змінюються.
Повний PostgreSQL/SQLite restore, retirement legacy ролі, перевірка телефона
та закриття старих репозиторіїв залишаються окремими роботами.

## Вибір механізму та поділ реалізації

Використовуємо поточні Python inventory, planner, evidence та privilege
gate. Спільний транзакційний механізм отримує окремі перевірки для
disposable і production: не замінюємо test guard дозволом із environment.
Старий shell executor не копіюємо як другу реалізацію ACL контракту.

Реалізація поділена на три послідовні зміни:

1. DB executor: target binding, production preflight, forward, receipts,
   explicit inverse і перевірки помилок. Production apply CLI ще закритий,
   доки не прийнятий maintenance adapter із наступного етапу.
2. Maintenance adapter та операторський CLI: фактичні Compose stacks,
   клієнти, timers/jobs, зупинка, перевірка й відновлення runtime. Саме ця
   зміна відкриває production apply після повного isolated acceptance.
3. DSN cutover окремих legacy clients: погоджена зміна конфігурації,
   приймання фактичного session user та відкат конкретної служби.

Кожна зміна має власний PR, документацію та relevant CI; не запускаємо
повторно повний DB suite лише через текстові уточнення. Implementation
plan цієї специфікації спочатку деталізує етап 1; етапи 2–3 мають окремі
плани після приймання залежностей. Наведені нижче вимоги зв'язують їхні
інтерфейси, але не є дозволом пропустити наступні перегляди.

## Target binding та read-only підготовка

Новий модуль `adoption_target.py` представляє immutable TargetBinding:
version, PostgreSQL system_identifier, database name/OID, очікувану
адміністративну session role, exact source commit і runtime manifest digest.
Target digest — SHA-256 канонічного JSON. Значення credentials не входять.

System identifier читається через `pg_control_system()`; OID — із
`pg_database`. Це додаткова прив'язка операції, а не зміна переносного
inventory fingerprint: restore на іншому кластері повинен вимагати новий
binding. Physical clone може зберегти system identifier; тому його самого
недостатньо без звірки host/Compose/container identity в adapter.

Перед SQL mutation executor повторно звіряє binding, plan digest,
before fingerprint, точний journal/SHA 001–016, PostgreSQL 16 та
TimescaleDB 2.30.1. Відсутність прав прочитати identity — відмова, а не
fallback до порівняння dbname. Connection лише через захищене середовище;
application DATABASE_URL не використовується як запасний DSN.

Existing snapshot/plan format 1 і disposable CLI лишаються сумісними.
Production operation manifest має окремий format_version 1 і посилається
на hashes цих артефактів. Зміна каталогу після планування, включно з новим
chunk, вимагає нового плану та нового підтвердження.

## Production preflight і межа maintenance

DB executor вимагає типізований MaintenanceContext від adapter, але не
вважає його JSON або позначку maintenance достатнім доказом. Перед forward
і inverse adapter повторно перевіряє runtime, executor — DB sessions/jobs.
Чужа, пошкоджена або не підтверджена повторними фактичними перевірками
context/receipt відхиляється до SQL. Context прив'язаний до operation ID,
target/runtime/plan digests і maintenance phase; timestamp сам по собі
не дозволяє mutation. Після завершення чи втрати керування maintenance
context не можна використати повторно без нового preflight.

Runtime manifest описує фактичні host identity, DB container/image,
Compose projects, повний впорядкований список Compose/override файлів,
їх hashes, service names, collector stack/control, timers та image IDs
кожної служби. Секретні env/DSN не копіюються в manifest; для них зберігаємо
лише приватну rollback-конфігурацію без логування значень. Зміна env
перевіряється приватно, а не публікується як низькоентропійний password hash.

Adapter підтримує тільки підтверджену topology. Невідомі stacks,
DB clients, автоматичні writers чи відсутні конфігурації — відмова.
Ingress Caddy закривається до зупинки API. Зупиняємо API, collector,
notifier, watchdog і surge worker, включно з окремим collector stack,
якщо він фактично активний. Перевіряємо всі контейнери за labels/IDs,
а не лише exit status compose stop. Не видаляємо контейнери чи volumes.

Зберігаємо попередні active/enabled states дозволених timers; зупиняємо
їх і чекаємо завершення запущених служб із обмеженим timeout. Невідомих
служб не завершуємо примусово. Collector spool не відкриваємо для запису,
не очищуємо й не підміняємо; identity шляху/volume має лишитися незмінною.

Timescale jobs інвентаризуємо окремо від ownership fingerprint: job ID,
procedure, owner, schedule/config та статус виконання. Production executor
приймає лише перевірений maintenance стан без scheduled або running jobs.
Якщо інформація неповна, worker невідомий або jobs ще працюють — відмова.
Adapter призупиняє тільки явно погоджені jobs через штатний Timescale API,
зберігає їхній попередній стан і відновлює тільки власні підтверджені зміни.
Це maintenance операція, окрема від forward/inverse ACL; direct UPDATE
Timescale catalog заборонений. Підтримуваний job layout і pause/resume
поведінку доводимо на pinned 2.30.1, не лише за документацією latest.

Відсутність сторонніх client sessions перевіряємо незалежно від того,
чи session idle. Перевіряємо також непідтримувані background writers і
prepared transactions у цільовій БД. Не застосовуємо pg_terminate_backend.
Перевірки повторюємо під locks; жодна allowlist не складається лише з
контрольованого клієнтом application_name.

## Оператор і погодження

Production CLI працює на Linux із локальним інтерактивним `/dev/tty` та
оператором root, як чинний production restore contract. DSN, confirmation
і секрети не передаються через argv. Test failpoints і test-mode environment
відхиляються в production path. Немає універсального `--force`/`--yes`.

Після read-only preflight оператор бачить дію, target digest, повний plan
digest і зміни maintenance. Фраза містить `ADOPT` або `INVERSE`, target
digest та plan digest; вона зчитується з TTY і звіряється точно. Inverse
потребує нового окремого підтвердження. Фраза не замінює явний GO власника
на конкретну серверну операцію та погоджене maintenance window.

Для isolated acceptance production branch викликається через injected
operator/runtime adapters та окремі disposable fixtures. В production
CLI такі injections/failpoints недоступні. Чинний `apply-test` не отримує
можливості працювати з live DB.

## Транзакція, evidence та inverse

Повторно генеруємо SQL із перевіреного snapshot/plan; arbitrary statements
з evidence не виконуються. Advisory lock очікуємо з обмеженим timeout до
repeatable-read snapshot, object locks отримуємо до capture. Identity,
sessions/jobs і drift перевіряємо знову до першого ownership/ACL statement.

Production evidence каталог абсолютний, поза checkout, Linux 0700;
файли 0600, власник оператор, exclusive atomic publication із fsync,
без symlinks/hardlinks/overwrite. Production receipts version 1 включають
operation ID, target digest, plan digest і before/expected fingerprints;
intent, committed, accepted та inverse записи зв'язані з тією ж операцією.
Production receipts відокремлені від disposable records і не приймають
їх як дозвіл на inverse. Resume не перезаписує попередній журнал операції.

До commit перевіряємо expected fingerprint. SQL failure відкочує
транзакцію; статус rolled_back можливий лише після read-only доказу
before fingerprint. Після commit — новий read-only capture, privilege
gate та accepted receipt. Втрата COMMIT acknowledgement або committed/
accepted receipt означає commit_unknown: не повторюємо apply/COMMIT
і не виконуємо автоматичну компенсацію.

Production post-commit acceptance failure не запускає inverse автоматично.
Окремий inverse вимагає валідні intent/committed records, binding,
maintenance, нове підтвердження та exact expected fingerprint під locks.
Він повертає лише власників/ACL зі snapshot, включно з grants/defaults/
columns/functions. Data, journal/applied_at та function bodies незмінні.
За чужого drift inverse відхиляється, стороння зміна зберігається.

Для inverse діє та сама межа COMMIT: втрата acknowledgement чи receipt
після inverse commit означає commit_unknown, а не rollback_failed або
rolled_back. Автоматичний повтор inverse за такого результату заборонений.

Shared engine зберігає чинну перевірену поведінку disposable компенсації;
production policy explicit inverse не змінює тести чи статуси `apply-test`.

## Runtime outcome та failure state

| DB результат | Дія runtime |
| --- | --- |
| Відмова до maintenance | Сервіси не змінювати |
| Відмова після часткової зупинки | Відновити тільки власні перевірені зміни за незмінного before fingerprint; невідомий стан залишити на діагностику |
| Verified pre-commit rollback | Дозволити adapter відновити збережений runtime; окремо перевірити результат |
| adopted / already_target з повним evidence | Відновити ті самі DSN, exact images, timers/jobs; перевірити кожну службу до ingress |
| commit_unknown / непідтверджений rollback / drift | Залишити maintenance, jobs/timers paused; не запускати clients чи автоматичний inverse |
| Accepted DB, restart failure | Окремий runtime_failed; DB adoption не називати rolled_back |
| Verified explicit inverse | Відновлення збереженого runtime дозволене після окремого результату adapter |

DB коди сумісні: 0 adopted/already_target, 1 refused/rolled_back,
2 unavailable/invalid arguments, 3 rollback_failed, 4 commit_unknown.
Orchestrator повертає код 5 для runtime_failed зі статусом DB у JSON; не
перевикористовує код 3 як legacy «commit успішний, restart failed».
HUP/INT/TERM після початку maintenance не означає автоматичний restart:
спочатку фіксуємо phase і встановлюємо фактичний DB outcome.

Restart використовує повний збережений Compose набір, явні service names
та `--no-deps`, без pull/build/migrate. Спочатку DB clients і локальне
приймання, після цього ingress. Exact image drift чи підміна конфігурації
блокує recreate. Процедура не чистить dirty серверний checkout.

## Окремий DSN cutover

Adoption не змінює DSN. Після приймання прав переключаємо лише фактичні
legacy clients по одному: collector та watchdog за поточним аудитом.
Для кожної служби — власний GO, приватна попередня конфігурація,
незмінний image, session user acceptance і службовий сценарій.

Collector зберігає Device ID, 60-секундний цикл і кожен запис/spool state;
спостерігаємо штатні нові цикли без додаткових upstream probes. Watchdog
перевіряємо через штатний звіт; FCM acceptance не означає показ на телефоні.
Cutover failure повертає попередній DSN лише цієї служби, без ACL inverse.
API/notifier/surge уже обмежені: не переводимо їх назад на legacy.

## Обов'язкове isolated приймання

- Два кластери/БД з однаковою назвою: чужий binding відхиляється;
  changed DB OID, source/runtime digest, admin role і recovery target також.
- Відсутній TTY, неправильна фраза/дія/plan digest, test environment,
  сторонній або пошкоджений context/evidence — нуль SQL mutation.
- Fresh та legacy-like 001–016 із compressed chunks/CAGG: forward/gate/
  explicit inverse; точні original ACL/data/journal/function definitions.
- Active/idle client, prepared transaction, scheduled/running/unknown job,
  timeout і chunk drift — відмова; нікого примусово не завершуємо.
- Injected SQL failure, COMMIT acknowledgement loss, publication/fsync
  failure, acceptance failure, inverse failure та post-commit drift:
  достовірний DB outcome, receipts і відповідний maintenance state.
- Partial stop, Compose override omission, image/env drift, окремий
  collector stack, restart failure, HUP/INT/TERM і повтор операції:
  збережені volumes/spool та відсутній випадковий migrate/rebuild.
- Jobs/timers pause/resume повертають тільки збережені власні зміни;
  чужий drift не перезаписується. Невідомий DB outcome лишає їх paused.
- Негативні ACL probes під сімома ролями; unchanged disposable CLI,
  unit suite, provenance та relevant database/runtime CI.

Ці сценарії працюють у disposable Docker projects без production env,
volumes і доступу до єЧерги. Production-shaped не означає live target.

## Критерій завершення та operational handoff

Source етап завершений після relevant exact-head CI, незалежного review
та злиття трьох змін із актуальними ops docs/MIGRATION-REMAINING/
RELEASE-READINESS. Жоден зелений тест не позначає production прийнятим.

Перед першою серверною операцією потрібні свіжий read-only audit, реальна
актуальна off-host копія з checksum і isolated restore, погоджені target/
plan/maintenance window, exact runtime rollback та окремий GO. Adoption,
DSN cutover і подальший soak/retirement приймаються окремо. Старі
репозиторії зберігаються до повного фінального приймання міграції.

## Первинні технічні джерела

- [PostgreSQL 16: control data functions](https://www.postgresql.org/docs/16/functions-info.html#FUNCTIONS-CONTROLDATA):
  `pg_control_system()` і system_identifier для target binding.
- [Timescale jobs](https://www.tigerdata.com/docs/reference/timescaledb/informational-views/jobs)
  та [job stats](https://docs.timescale.com/api/latest/informational-views/job_stats/):
  metadata/scheduling і статуси; сумісність доводиться на pinned 2.30.1.
- [Timescale alter_job](https://www.tigerdata.com/docs/reference/timescaledb/jobs-automation/alter_job):
  штатний API pause/resume, окремо від ownership SQL.
