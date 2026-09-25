# Дизайн production restore capability

**Статус: дизайн для review.** Це не операторська інструкція, не дозвіл
застосовувати міграції й не дозвіл на production restore.

## Цілі та межі

- Залишити публічний `ops/restore.sh` fail-closed лише для `restore_test`.
- Зберегти окремий production entrypoint; ніколи не додавати `avelren` до
  звичайного CLI.
- До першого stop/drop перевірити артефакт, середовище, конфігурацію і доступи.
- Після початку maintenance при будь-якій невизначеності лишати ingress та
  DB-клієнтів зупиненими й вимагати ручного відновлення за чинним планом.
- Усі розробницькі й CI перевірки використовують тимчасові Compose-проєкти,
  синтетичні дані й credentials. Не підключати production volumes, `.env`,
  Drive або зовнішнє джерело даних.

## Запропоновані фази

### 1. Неруйнівний preflight

Перед maintenance перевірити точне підтвердження оператора, локальний файл
дампа, його sidecar SHA-256 і gzip цілісність; за наявності зашифрованого
артефакту — provenance/decrypt перевіряє окремий дозволений процес, а не
orchestrator із неявним доступом до ключа. Усі DSN, Compose file, project,
project directory, env-file та isolation/production context мають бути
визначені явно. Перевірити, що project і DB service справді належать
очікуваному production stack.

До зупинки сервісів перевірити підключення `avelren_admin`, `current_user`,
наявність сумісних ролей для міграцій і runtime, очікуваний migration pin,
діапазон міграцій, schema allowlist та доступність snapshot-каталогу. Паролі й
DSN передавати тільки через середовище процесу/container, не аргументи CLI та
не журнали.

Стан ролей і schema має бути узгоджений із вибраною гілкою recovery. На
2026-09-23 production було зафіксовано на 001–009 із незавершеним
adoption/pin переходом. Якщо актуальна read-only перевірка перед майбутньою
операцією покаже інший стан, цей план спочатку переглянути; не вгадувати роль
із номера міграції.

### 2. Maintenance та захисний snapshot

Після успішного preflight зупинити ingress, потім відомих DB-клієнтів і
перевірити `pg_stat_activity`; будь-яка невідома сесія блокує destructive
крок. До drop створити узгоджений pre-restore dump із перевіреним SHA-256.
Окремо вирішити й задокументувати, чи відмова цього snapshot блокує recovery:
старий orchestrator продовжує без нього, але це не повинно залишитися
неявним fallback.

Після входу в maintenance будь-яка помилка лишає ingress і відомих DB-клієнтів
зупиненими, чітко записує фазу та причину і не запускає сервіс автоматично.
Звичайного безпечного rollback до попередньої production DB немає; snapshot
допомагає ручному recovery, але не робить overwrite автоматично оборотним.

### 3. Timescale-aware restore та migration gate

Production engine має бути доступний лише окремому production orchestrator;
публічний CLI та disposable engine залишаються обмежені `restore_test`.
Production capability має перевіряти target і роль до `dropdb`, викликати
`timescaledb_pre_restore()` перед імпортом і гарантувати спробу
`timescaledb_post_restore()` після нього, не маскуючи первинну помилку.
Ownership, extension owner, relation allowlist та відсутність unexpected
objects перевіряти до передачі БД runtime.

Після імпорту запустити лише узгоджений migration gate з явною версією/pin.
Поточний Compose ховає `migrate` за профілем, а host override може містити
pin. Оркестрація мусить перевірити ефективну модель і очікувану верхню версію;
звичайне `compose up migrate` без такого gate не приймати як достатню
перевірку.

### 4. Перевірка і вихід із maintenance

До повернення ingress перевірити точну історію міграцій і hash, фізичну схему,
ownership/grants, read-only API health/auth/device smoke та snapshot/API mount.
Потім контрольовано підняти DB-клієнтів і ingress останнім. Перевірити зовнішній
HTTPS health та новий успішний collector cycle після restore; stale health сам
по собі не доводить, що збір відновився.

## Обов'язкова ізольована матриця тестів

- Невірний token, відсутній/пошкоджений дамп, поганий sidecar hash, відсутні
  credentials або неправильний Compose project відхиляються **до першої
  stop-команди**.
- Disposable `restore_test` CLI і надалі відхиляє `avelren` без запуску Docker.
- Production engine викликається тільки з orchestrator context; target,
  database role та expected Compose labels перевіряються до `dropdb`.
- Повний dump і допустимий префікс 001–009 відновлюються на synthetic
  TimescaleDB, після чого міграції доходять до явно обраної версії, schema/API
  smoke проходить.
- Перевірити помилки `pre_restore`, імпорту SQL, `post_restore`, migration,
  ownership/schema/API/readiness/freshness. Для кожної точки перевірити, що
  немає хибного `success` і що maintenance лишається закритим.
- Активна невідома DB-сесія, stop failure чи неможливість перевірити фінальний
  стан блокують restore або лишають сервіси зупиненими згідно з дизайном.
- Перевірити, що fake command boundaries не можуть викликати хостовий Docker
  за межами випадкового Compose project; після кожного сценарію volumes,
  networks і containers цього project видалені.

Наявний старий production integration test уже покриває частину цих пунктів на
ізольованій БД. Він не перевіряє нові шляхи, sidecar gate, новий low-level
engine або актуальну production role/pin конфігурацію; його не можна вважати
приймальним тестом майбутньої реалізації.

## Окреме підтвердження перед реальною операцією

Успішні CI та bench тести доводять лише код на синтетичному середовищі. Перед
будь-яким production restore потрібні актуальний read-only preflight, точний
план змін і ручного recovery та окрема велика команда власника з явним
дозволом на конкретну операцію. Цей дизайн такого дозволу не надає.
