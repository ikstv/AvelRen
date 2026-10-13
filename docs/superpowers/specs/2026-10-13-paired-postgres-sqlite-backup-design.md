# Узгоджений backup PostgreSQL та SQLite-черги

Дата: 13.10.2026. База дизайну: `c7419ae8cccd719c05a42ca61981d85b2bdc0410`.
Стан: підхід погоджений власником; письмова специфікація для перегляду.
Цей документ не є дозволом на встановлення чи зміну production.

## Мета й докази проблеми

Зберігати поза сервером комплект PostgreSQL + SQLite, з якого можна
відновити primary history та захоплені, але ще не підтверджені цикли.
Успіх backup означає перевірений комплект, а не лише успішний SQL dump.

13.10 локально відновлено справжній SQL backup від 13.10: schema/API PASS.
Окремо перевірено реальну SQLite-копію від 02.10: 419 ACKed, pending=0,
SHA/integrity/payload validation/native open PASS. Синтетичний наскрізний
WAL → Online Backup → restore → FIFO/retry пройшов без дублів.
Це не актуальна узгоджена пара. Перевірений серверний backup executable
`de881a23614d40336cb1a7f51495124e30e152b1762f32fb0e90bae9b86dfae9`
копіює PostgreSQL; у цьому штатному path SQLite не включено.

Фактичні докази збережено локально як `restore-rehearsal-report-20261013.md`
та `sqlite-restore-rehearsal-20261013.md/.json` поза checkout. Приймання
реалізації має додати безпечний датований аудит у репозиторій.

## Розглянуті підходи

1. **Обраний:** короткий capture-only, SQL dump, SQLite Online Backup,
   повернення writer, шифроване завантаження комплекту. Producer продовжує
   штатний збір; writer не змінює ACK під час формування обох копій.
2. Незалежні SQL/SQLite jobs простіші, але допускають ACK у SQLite для
   циклу, якого немає у SQL snapshot. Не дають потрібної гарантії.
3. Зупинка всього collector або сервера спрощує snapshot, але перериває
   збір; наявний capture-only дозволяє уникнути цієї зупинки.

## Межі й незмінні контракти

- Один producer, початки запитів через 60 секунд, незмінний Device ID,
  endpoint/headers/error policy. Тести не звертаються до єЧерги чи FCM.
- Використати чинні `SpoolStore.backup_to`, capture-only writer ACK,
  `avelren_backup` для dump, crypt remote, native restore/schema guards.
- Не змінювати міграції, ролі/ACL, DSN, Android чи інші сервіси побічно.
- API доступний під час backup. Свіжість даних може тимчасово відставати,
  поки writer призупинений; не називати це відсутністю затримки.
- Межа capture-only вікна: **до 15 хвилин**, включно з on/off ACK.
  Звичайний budget копіювання 12 хвилин; решта 3 хвилини зарезервовані
  для скасування дочірніх операцій та повернення writer. Це ліміти,
  а не гарантія успіху при недоступній БД чи зламаному collector.
- Upload/remote verification виконувати після повернення writer.
  Ліміт мережевого етапу 15 хвилин; quota/error завершує запуск помилкою,
  без нескінченних retries і без продовження паузи writer.

## Формування узгодженої пари

1. Взяти міжпроцесний lock, спільний для paired backup та несумісних
   maintenance/restore/adoption операцій. Паралельний запуск відхилити.
   Чинні legacy команди самі цей новий lock не поважають: до адаптації
   їх паралельний запуск забороняє операційний runbook, а не уявний guard.
   Сучасні operator entrypoints мають перевіряти активний backup lease.
2. Перевірити identity контейнера/образу/volume за чинним runtime manifest,
   schema versions, crypt remote та доступне місце. Штатний maintenance
   preflight перевіряє integrity, pending digests, 2 GiB free та запас
   spool quota для 15 хвилин. Невідомий runtime відхилити до mutation.
3. Якщо capture-only уже ввімкнено, відмовитися без зміни режиму: backup
   не має права скасувати чуже maintenance. Початковий стан записати.
4. Зафіксувати намір увімкнення; викликати штатний capture-only on та
   дочекатися writer ACK. Навіть timeout може означати, що intent уже
   записано: cleanup повинен обробляти невизначений результат on.
5. Після ACK зробити SQL dump з consistent PostgreSQL snapshot, gzip
   integrity/size/hash validation. ACK означає закриті DB task/pool,
   включно з можливим завершеним commit без SQLite ACK.
6. Поки writer залишається paused, виконати SQLite Online Backup у
   приватний файл **поза** live volume через сумісний pinned helper.
   Helper не запускає collector, не має мережі чи production DSN.
   Live main-файл окремо від WAL не копіювати.
7. Перевірити статичну SQLite-копію: integrity, schema/payload versions,
   states, усі наявні payload hashes/models, range/counts. Зафіксувати
   початок/кінець SQL та SQLite snapshot, runtime source/image hashes.
8. Перевірити незмінний collector identity та ACK протягом критичного
   вікна. Несподіваний restart/зміна режиму робить комплект неприйнятним.
9. Повернути capture-only off і підтвердити writer ACK до upload.
   Відстежити pending/last_error до drain або контрольованої помилки.

**Чому це узгоджено:** кожен ACKed цикл SQLite вже committed у PostgreSQL
до SQL snapshot. Після on ACK writer не робить нових commits/ACK/prune.
Pending може вже бути committed через crash-before-ACK: native replay
звіряє всі primary fields перед ACK і не створює дубль. Нові цикли між
SQL та SQLite snapshot лишаються pending і потрапляють у комплект.

Producer продовжує працювати: SQLite може містити `started`. Відновлення
використовує штатний `recover_started`, записуючи interrupted cycle без
вигаданих observations. Гарантуються durable результати до snapshot;
відповідь, що ще не була збережена, не входить у гарантію. Межу snapshot
та кількість started явно показати в receipt/RPO evidence.

## Помилки та повернення writer

Виконавець має зовнішній deadline, контрольовані дочірні процеси й cleanup
для EXIT/HUP/INT/TERM; після скасування dump/helper дочекатися їх виходу.
Cleanup повертає тільки власний змінений режим для того самого runtime.
Не вимикати capture-only при втраті lock, зміні identity або takeover.
У такому разі зберегти категорійний durable state та повідомити оператору.

SIGKILL/host crash не можна виправити shell trap. Потрібен обмежений
recovery entrypoint для незавершеного запуску: під спільним lock перевіряє
записаний intent, identity та відсутність нового власника, завершує
cleanup/повернення writer. Безпечна точка запуску — systemd failure/stop
recovery та preflight наступного запуску; не покладатися лише на завтра.
Повна відмова хоста потребує операторського recovery після його запуску.
Наявний capture-only не має owner token: автоматичний takeover стороннім
оператором під час активного backup lease заборонений; при неможливості
довести власність cleanup відмовляється, не вгадує її лише за boolean.

Якщо off ACK не отримано, job завершується помилкою; receipt не видається,
успішний backup stamp не оновлюється. Pending не видаляти. Відсутність
БД/collector не обіцяє автоматичного повернення нормальної роботи.

## Off-host формат і сумісність

Зберегти legacy `avelren-<UTC stamp>.sql.gz` та його `.sha256`, щоб старі
SQL restore процедури могли читати dump. Додати з тим самим backup ID
`avelren-<UTC stamp>.spool.sqlite3.gz` та `.sha256`, і фінальний
`avelren-<UTC stamp>.pair.json` — versioned completion manifest.

Manifest містить лише basenames, hashes, sizes, source/image/schema versions,
snapshot times, state counts, cycle range й outcome повернення writer.
Без DSN, credentials, Device ID, payloads або сирих error messages.
Усі файли й manifest завантажуються через перевірений crypt remote.

Спочатку upload обох artifacts/sidecars та перевірка віддалених plaintext
hash/size; completion manifest публікується останнім і також read-back
перевіряється. Paired reader приймає тільки валідний manifest і повний
набір з exact names/hashes; довільне змішування двох dates заборонено.
Відсутній manifest або частковий upload — неповний комплект.

Retention зберігає наявні 7 daily / 4 weekly / 3 monthly й видаляє старі
paired artifacts групою за backup ID тільки після перевірки нової пари.
Legacy SQL-only copies розпізнаються окремо, не видаються за paired;
не видаляти їх побічно під час початкового ввімкнення нового формату.
Plaintext artifacts/temp files — 0700 directory/0600 files; cleanup при
всіх штатних виходах, жодних secrets у argv/logs. Невдалий upload не має
змінювати чинний success stamp чи видавати успішний receipt.

## Ізольоване відновлення й приймання

Paired rehearsal читає manifest, перевіряє hash/size/gzip/integrity/schema
до restore. Окремі PostgreSQL/SQLite copies та internal Docker project,
без published ports, production volumes/DSN або зовнішніх запитів.
SQL відновлюється native engine з Timescale pre/post hooks та role/schema
identity guards. SQLite відкривається тільки як власна робоча копія.

Перед replay звірити кожен retained ACKed cycle з restored SQL через
чинну exact primary verification. Відсутній/відмінний ACKed цикл означає
невідповідну пару: fail closed, не скидати ACK. `started` перетворюються
штатно; тільки після pair acceptance дозволити off та pending FIFO replay.
Перевірити точні primary values, commit-before-ACK retry, відсутність
duplicates та delayed-derived skip для старих cycles.

Обов'язкові сценарії: pending WAL; SQL commit перед ACK; mixed ACKed/pending/
started; уже чужий capture-only; on timeout; dump/helper timeout; SIGTERM;
SIGKILL recovery; runtime restart/takeover; off ACK failure; corrupt/unknown
payload; missing ACKed primary; conflicting pending primary; quota/частковий
upload; wrong crypt remote; retention; cleanup й незмінний success stamp.
Окремий daemon тест перевіряє producer rhythm/ACK під час реального backup.

## Розгортання й наступний етап

Реалізація, локальні tests/review, PR/CI й документація — source етап.
Після злиття підготувати точні host/helper artifacts, hashes, installation
paths, systemd timeout/recovery wiring і restore rehearsal команди.
Серверне встановлення, capture-only та перший backup потребують окремого
конкретного GO. Відкат — точні збережені старі host/unit files; спочатку
підтвердити повернення writer, не підміняти runtime чи видаляти spool.

Фінальне приймання: нова реальна пара off-host, download/decrypt/hash,
ізольований SQL+SQLite restore/replay, runtime health/drain після backup.
Виміряти snapshot boundary, pause та повний recovery час. До цього RPO/RTO
не оголошувати прийнятими. Наявні legacy production restore guards не
послаблювати: цей етап не відкриває production disaster restore.
