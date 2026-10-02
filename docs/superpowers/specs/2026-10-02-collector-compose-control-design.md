# Керування collector через окремий Compose

## Мета й погодження

Власник погодив дизайн 02.10.2026 відповіддю «го»: перенести керування
новим collector у окремий Compose, зберегти образ, налаштування та чергу,
перевіряти відсутність другого збирача й узгодити операторські процедури
обслуговування БД. Критерій успіху: штатні команди керують саме новим
collector; заміна контейнера не губить pending; старий збирач не запускається
як побічний результат цих команд.

Це погодження дизайну. Воно не є дозволом на запис на production.
Кожне розгортання має окремі конкретні перевірки, відкат і GO за AGENTS.md.

## Перевірений вихідний стан

Джерела: [серверне приймання](../../PRODUCTION-AUDIT.md#collector-spool--02-жовтня-2026-року),
[контракт єЧерги](../../../INTEGRATION.md),
[операторський контракт spool](../../../ops/COLLECTOR-SPOOL.md).
Read-only аудит цієї сесії повторно підтвердив:

- `avelren-collector-1`, ID `cab603af19ac…`, running, RestartCount=0;
  контейнер створений напряму, без Compose labels.
- Образ `sha256:1ab8437b7e789ec44a6971604bd56d9c43a1117c04278cb5faf550ca7d3235a1`,
  код `0c62f543643b74a177ee56e5351cf518c1b9053d`, PR
  [#75](https://github.com/ikstv/AvelRen-ORIGINAL/pull/75).
- Приватний зовнішній том `avelren_collector_spool_v1`, мережа `avelren_default`.
- `avelren-collector-rollback-a28360af` stopped, але має labels
  project=`avelren`, service=`collector`. Його образ відсутній в image store;
  контейнер необхідно зберегти без recreate.
- `/opt/avelren/deploy/postgres-adopt.sh` керує collector через старий Compose.
  У main `ops/restore-production.sh` також зупиняє і запускає collector разом
  із клієнтами БД через загальний Compose.
- Telemetry шукає ім'я `avelren-collector-1`; інші п'ять робочих служб
  залишаються в старому stack. Загальний Compose main містить кандидати
  оновлень БД/Caddy, які не встановлені на сервері.

Це датований стан. Перед майбутнім перемиканням повторити інвентаризацію.

## Вибір підходу

Обрано окремий collector-only Compose project `avelren-collector-runtime`.
Повний перехід stack потребував би окремого приймання інших служб та локальних
overrides. Пряме Docker-керування не усуває розбіжність операторських процедур.
Окремий project не знаходить старий rollback-контейнер за Compose labels.

## Compose і постійні ресурси

Додати `ops/compose.collector-runtime.yml` з єдиною службою `collector`:

- явне `container_name: avelren-collector-1` для чинної telemetry;
- image визначається приватним release manifest; preflight перевіряє точний
  image ID та embedded SHA. Заборонені build, pull та `latest`;
- зовнішні існуючі network `avelren_default` і volume
  `avelren_collector_spool_v1`; відсутність будь-якого ресурсу зупиняє операцію;
- spool mount `/var/lib/avelren/collector-spool`;
- приватний `env_file` поза checkout, root-owned 0600, без виводу значень;
- той самий Device ID, endpoint, заголовки, інтервал 60 секунд та чинний DSN;
- UID/GID 10001, read-only root filesystem, cap_drop ALL,
  no-new-privileges, tmpfs `/tmp` 64 MiB, pids_limit 128,
  restart unless-stopped — відповідно до встановленого контейнера;
- немає db/migrate залежностей, міграцій, портів і інших служб.

Нові memory/CPU limits не додаються під час цього переходу. Compose-файл і
manifest встановлюються у root-owned release-каталог поза `/opt/avelren`.
Будь-яка команда явно задає файл і project: автоматичного discovery overrides
немає. Не використовувати `down -v` або `--remove-orphans`.

## Операторський інтерфейс і захист

Додати `ops/collector-runtime-control.sh` із командами `status`, `logs`,
`start`, `stop`, `restart`, `capture-only status|on|off` та `preflight`.
Статус показує image/SHA, container ID, spool pending, найстаріший pending,
capture-only request/ack, last_error і RestartCount, без секретів.

Мутації серіалізуються host lock. Перед ними звіряються manifest, effective
Compose, контейнер, image, мережа, том, приватні файли й інвентар збирачів.
Додатковий running collector або неоднозначна відповідність означають помилку
до запуску/перезапуску. Для пошуку враховуються ім'я, Compose service labels
і команда запуску модуля collector, а не лише ім'я одного контейнера.

При start після stop та при restart витримати щонайменше 60 секунд після
повної зупинки попереднього poller. Час зупинки записується атомарно у
root-owned state поза контейнером; якщо доказу безпечного інтервалу немає,
витримати повні 60 секунд перед стартом. Після запуску звірити фактичний
контейнер і відсутність другого poller. Збій перевірки не спричиняє автоматичний
запуск старого контейнера. Операційні логи не містять DSN чи env.

Цей інтерфейс захищає штатний керований шлях. Він не забороняє root вручну
виконати довільний `docker start`. Старі Compose start/up/restart collector
залишаються забороненими runbook; попередження й preflight переходу БД мають
явно виявляти нову топологію. Не заявляти, що старий script став безпечним,
якщо його фактично не адаптовано та не встановлено.

## Обслуговування БД та restore

Для планового обслуговування БД collector продовжує опитування джерела:
спочатку spool maintenance preflight, Online Backup й перевірка запасу;
потім `capture-only on` з підтвердженим закриттям writer/DB pool.
Після відновлення БД `capture-only off` чекає schema gate та writer ack,
після чого перевіряються FIFO replay, pending та свіжий природний цикл.
Помилка/timeout підтвердження зупиняє перехід; черга залишається збереженою.

Старий postgres-adopt не запускати до окремої адаптації його фактичної версії.
У цьому етапі додати сумісний інтерфейс і runbook для наступного переходу
прав БД, без перенесення всього legacy orchestrator та без зміни ролей.

Restore старого snapshot може конфліктувати з уже acked циклами SQLite.
Тому restore не прирівнюється до короткого обслуговування БД.
Додати у source restore preflight відмову від непідтримуваної окремої
collector-топології **до** safety snapshot, maintenance та інших мутацій.
Наявний звичайний Compose-сценарій лишається доступним за чинним контрактом.
Повний production restore з новим spool потребуватиме окремого дизайну
звірки snapshot/SQLite; цим етапом його не оголошуємо прийнятим.

## Перемикання й відкат

Compose labels неможливо додати до вже створеного контейнера: потрібна
керована заміна з використанням того самого volume й образу.
Майбутній production-план має включати:

1. Свіжу інвентаризацію, перевірений штатний backup БД, manifest/config
   preflight та Online Backup spool поза томом.
2. Graceful stop поточного collector; offline перевірку spool/digests.
   Якщо є pending або помилки — зберегти їх; використовувати лише образ,
   сумісний із цим форматом. Не очищати чергу для проходження перевірки.
3. Зберегти поточний контейнер з іншим ім'ям для відкату; старий legacy
   rollback також зберегти зупиненим. Не запускати обидва на спільному томі.
4. Після повних 60 секунд від stop запустити єдиний Compose collector
   з поточним image та volume. Повторно звірити Device ID без виводу значення.
5. Прийняти щонайменше п'ять природних циклів, інтервал 60 секунд,
   primary/derived, pending/replay, API freshness і telemetry.
   Інші служби мають зберегти ID/image/RestartCount.

Відкат цього переходу повертає збережений **сумісний spool-контейнер**,
а не legacy collector: зупинити Compose collector, зберегти Online Backup,
перевірити spool, звільнити canonical name, повернути його попередньому
контейнеру, витримати 60 секунд від повної зупинки й запустити лише його.
Це дозволяє зберегти pending. При пошкодженні spool зупинити перехід і
готувати recovery; обидва rollback-контейнери та volume не видаляти.

## Перевірки й облік готовності

- Compose contract: одна служба, зовнішні ресурси, точний image, security,
  без build/pull/migrate/DB recreate й випадкового нового spool volume.
- Контракт control: підміна Docker/годинника; lock, хибний manifest,
  додатковий poller, чужий контейнер/volume/image, timeout capture-only,
  зупинка/start/restart та пауза 60 секунд; негативні перевірки без мутацій.
- Restore guard: нова топологія відхиляється до будь-якої мутації;
  наявний контракт старої топології продовжує проходити.
- Ізольована Docker-репетиція з окремою БД/network/volume та синтетичним
  HTTP: заміна standalone на Compose, pending replay, збереження
  capture-only, повторний запуск і відкат до сумісного контейнера.
  Назви тестових ресурсів параметризовані; production ресурсів і запитів
  до єЧерги в тестах немає.
- Перевірки shell, repo/provenance та залежних workflow; CI перевіряє
  точний фінальний head. Відсутній CI не вважається успішним.

У [реєстрі релізу](../../RELEASE-READINESS.md) окремо записати spec, source,
CI, репетицію і production. Android/телефон/Play не закривати серверною
перевіркою. PR зберігає посилання на #74/#75/#76 і походження legacy
процедур. Автооновлення, автоматичний host reboot, OS/Docker updates,
права БД, applied migrations, TimescaleDB та Caddy не входять до зміни.
