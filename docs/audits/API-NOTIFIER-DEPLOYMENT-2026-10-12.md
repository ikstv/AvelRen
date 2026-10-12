# API та notifier — приймання розгортання 12.10.2026

Після окремого дозволу власника виконано application deployment лише API та
notifier. Підсумок оператора — `forward_verified`; свіжа звірка завершена
12.10.2026 о 19:57:05 UTC. Це приймання конкретного розгортання, а не всього
перенесення чи Android-релізу. Попередні аудити збережено на їхні дати.

## Канонічне джерело й образ

Джерело — Git archive канонічної `AvelRen-ORIGINAL/main`
`574b25cbf622c008a9e7d11a4d280af91963f71b`, tree
`b75da8d4f340e0666f7215222b2485209f22c105`; preparation helpers не змінювали
canonical source. [PR #124](https://github.com/ikstv/AvelRen-ORIGINAL/pull/124)
злитий; усі 11 main CI jobs SUCCESS. Windows preparation directory не є
окремим джерелом походження коду.

| Identity | SHA-256 |
| --- | --- |
| Runtime image index API/notifier | `9d32a0d54ff9711b54a082f39074e21ba456775b078caf01a293b95109674735` |
| Linux/amd64 platform manifest | `573bc8d7c437b1a00f03358ba7c66b43606acccf99a833c1a189f4bbf7d57bf2` |
| Platform image config | `79fcb2822f5c1ebfd2b82a24b54e2e81996d894ff1f1bc5c07dadb43f805ac53` |
| Переданий application archive | `c1aea8879fb33c681e84a4a0272360afea5d89c2c5d151236df258885f68985f` |

До простою перевірено imported-server identity, усі 35 dependency pins,
56 packaged Python/model файлів та installed model. Ізольовані installed-image
API/notifier regressions: 15 passed; actual old → candidate → actual old
startup/readiness перевірено на власній synthetic DB без production DSN,
volumes, upstream чи живих FCM sends. Offline перевірка імпортованого образу
на фактичному сервері також PASS. Inventory не є vulnerability scan.

## Фактичне вікно та результат

Власник змінив підхід і прийняв короткий простій зі звичайною плашкою до
15 хвилин та відкатом за невдалого приймання. Перед stop пройдено свіжий
preflight. Перші відмови `unsafe_input_file`/`KeyError` були до плашки й
service actions; виправлення перевірено перед остаточним запуском.

| Подія / вимір | UTC / тривалість |
| --- | --- |
| Публікація звичайної плашки | 19:53:12; планове завершення 20:08:12 |
| Початок service window | 19:54:12.957 |
| Forward приймання API та notifier | 19:55:27.258 |
| Зняття власної плашки | 19:55:27.566 |
| Підтверджена тривалість плашки | 135.263 s |
| Service window | 74.301 s |

Вимір service window охоплює stop/deploy/readiness та перевірку; це не вимір
суцільної HTTP-недоступності. Локальні rehearsal timings не підмінюють цей
production вимір. Відкат у production не виконувався, бо forward приймання
успішне; old → candidate → old було лише ізольованою репетицією.

Свіжий readback: сім контейнерів running, DB healthy, RestartCount=0;
API і notifier мають exact новий image index. Health `ok`, age 16 s,
last observation `19:56:49Z`, alert channel/undelivered alerts `ok`,
`/status` maintenance `null`. IDs/images інших п'яти служб — DB, Caddy,
surge_worker, watchdog, collector — збігаються з preflight baseline.

## Межі та решта робіт

Змінено лише API/notifier, власний staging і власну плашку. Не виконувались
міграції/adoption/DSN cutover, зміни collector/spool/Caddy/watchdog/OS або
reboot. Ручного FCM push, нового APK/AAB, перевірки телефона та Play не було.
Application rollback повертає executable/config і не є DB restore.

Подальшу реалізацію розширеного maintenance плану для цього application
оновлення замінено прийнятим коротким deployment. Часткові напрацювання
збережено без operational приймання. Production DB CLI лишається закритим;
перехід прав БД/DSN — майбутня окрема робота з конкретним дозволом. Повний
restore зі звіркою БД/SQLite spool, live monitor та решта backend operational
робіт відкриті. Android FCM ownership/recovery, доставка/голос/ACK, APK з
commit/version/SHA-256 і Play приймаються окремо за
[реєстром готовності](../RELEASE-READINESS.md) та
[залишками перенесення](../MIGRATION-REMAINING.md).

Репозиторій тимчасово PUBLIC за рішенням власника; ця операція не змінювала
visibility чи доступів. Секретів, DSN або effective environment тут немає.

## Приватний handoff доказів

Докази збережено поза Git: `app-image-preparation-20261012.md`,
`app-deployment-window-20261012.md`, `app-deployment-acceptance-20261012.json`;
host release directory — `/var/lib/avelren-app-release/574b25c-20261012`.
JSON містить operator journals, offline proof, outcome, runtime і свіжий
health/status readback. Offline log SHA-256:
`ba5d34963a44c090db5abed5c125980aaa8fbbd59884aabcd4576304dc996b6d`.
Фрази «production не виконано» у preparation/window описують попередні
моменти підготовки; актуальний результат наведено в цьому аудиті.
