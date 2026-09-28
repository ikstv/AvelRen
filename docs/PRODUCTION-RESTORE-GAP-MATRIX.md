# Матриця розбіжностей для production restore

**Статус: source implementation з ізольованими контрактами.** Документ не є
дозволом на deployment або production restore і не додає `avelren` до
публічного `ops/restore.sh`.

Він порівнює read-only старий кандидат
`deploy/restore-production.sh` із `ikstv/AvelRen` commit
`4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` та поточний ізольований engine
`ops/restore-engine.lib.sh`. Старий кандидат мав окремі contract та Docker
integration tests, але його пряме перенесення небезпечне: новий engine
навмисно відхиляє target `avelren`.

| Межа | Старий кандидат | Поточний ORIGINAL | Висновок для майбутнього production capability |
| --- | --- | --- | --- |
| Публічний CLI | Окремий `deploy/restore-production.sh` приймає точний confirmation token | `ops/restore.sh` підтримує лише `restore_test` | Зберегти два незалежні entrypoint-и; ніколи не розширювати публічний CLI на `avelren`. |
| Артефакт backup | Перевіряє наявність і `gzip -t` | Source-only `restore-artifact.lib.sh` перевіряє gzip і один безпечний SHA-256 sidecar рядок; контракт покриває підміну, шлях і формат | Майбутній internal-only orchestrator мусить викликати цей gate до першої stop-команди; provenance/decrypt лишається окремим дозволеним процесом. |
| Compose-контекст | Приймає file і project, але не вимагає project directory, env file чи marker контейнера | Source-only identity gate читає лише Compose project/service/working-dir labels `avelren-db-1` і звіряє canonical `/opt/avelren`, Compose file та `.env` | Майбутній internal-only orchestrator мусить викликати цей read-only gate до maintenance; isolated guard не є substitute для production identity. |
| Ролі й DSN | Перевіряє `avelren_admin`, password, три DSN і `current_user` до maintenance | Static evidence validator і read-only preflight перевіряють точний набір ролей, membership, owners/grants та journal; password передається лише environment | Реальну recovery-пару все одно треба окремо зняти й схвалити на production. |
| Схема до зупинки | Не фіксує фактичну верхню міграцію й relation inventory до maintenance | Allowlist перевіряється після restore | До maintenance перевіряти migration range/pin та сумісну schema/role модель. На зафіксованому аудиті 2026-09-23 production була на 001–009; це історичний факт, не припущення для майбутнього запуску. |
| Maintenance | Зупиняє ingress, відомих DB-клієнтів і блокує невідомі активні сесії | Новий manual orchestrator публікує ordinary maintenance, зупиняє Caddy/клієнтів і повторно вимагає повністю quiescent DB | Source-контракт завершено; server-side приймання не виконувалось. |
| Pre-restore snapshot | Робить best-effort gzip snapshot і продовжує, якщо він не вдався | `backup.sh` атомарно видає `0600` receipt тільки після remote digest/size/retention verification; відмова блокує maintenance | Треба окремо перевірити на реальному `rclone crypt` після read-only/deployment GO. |
| Timescale restore | Старий orchestrator викликає engine із `avelren` | Public engine лишився `restore_test`-only; окремий source-only wrapper жорстко задає `avelren` над спільною primitive | Production wrapper покрито fake-command контрактом, але на production він не запускався. |
| Migration gate | Виконує `compose up -d migrate`, але без явної перевірки ефективного pin до maintenance | Disposable tests перевіряють обрану схему в ізольованому Compose | Перед destructive кроком зафіксувати очікувану версію/pin і після import перевірити точну історію міграцій та hash. |
| Вихід із maintenance | Перевіряє schema/API, HTTPS readiness і новий collector run | Orchestrator повторно перевіряє journal/roles, запускає клієнтів, чекає природний успішний collector cycle, перевіряє API/Caddy й лише тоді відкриває ingress | Будь-яка відмова або сигнал лишає Caddy закритим і maintenance активним; потрібне майбутнє staging/production приймання. |

## Вже підтверджено ізольовано

- Старий `restore-production-contract-test.sh` перевіряв confirmation, ролі,
  DSN identity, порядок stop/snapshot/engine, active-session gate, readiness і
  fail-closed maintenance на фіктивних command boundaries.
- Старий Docker integration test перевіряв повний dump, migration prefix
  001–009, schema/API smoke та active-session refusal на синтетичній БД.
- Поточний `ops/restore-engine-contract-test.sh` і
  `ops/restore-integration-test.sh` перевіряють fail-closed `restore_test`,
  Timescale hooks, ownership/allowlist і cleanup у випадковому Compose project.

Ці результати не є доказом готовності production restore: вони походять з
різних контрактів і не доводять сумісність поточних production ролей, schema,
backup-артефакту чи Compose runtime.

## Що лишається після source implementation

Потрібні зелений CI і code review точного коміту, окремий source-only release
candidate, окремий GO на read-only production evidence capture, review
санітизованої recovery-пари, окремий GO на deployment сценарію та rehearsal з
реальним розшифрованим backup лише в `restore_test`/staging. Production restore
допустимий тільки за реальної recovery-потреби й нового окремого GO.

Окреме явне GO власника все одно потрібне перед будь-яким server-side
preflight, deployment або production restore.
