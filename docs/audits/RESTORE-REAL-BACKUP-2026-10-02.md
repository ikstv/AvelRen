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

## Що залишалося після першої репетиції о 11:01

Реальне відновлення перевіреним main **на ізольованому серверному стенді
підтверджено**. Старі `/opt/avelren/deploy/restore*.sh` не замінювалися;
встановлений production restore runtime ще не прийнято як узгоджений з main.
Issue #41 лишається відкритою до окремої перевіреної адаптації/встановлення
runtime після конкретного дозволу та перевірки його фактичного результату.

Ця репетиція не перевіряє перехід прав живої БД, production restore
orchestrator зі spool, оновлення TimescaleDB, RTO/RPO, APK, телефон або Play.
Безпечний JSON доказу також збережено локально в ignored dist; SQL,
тестові паролі, PIN, токени та installation IDs не додані в Git.


## Встановлений runtime — приймання о 11:29 за Києвом

Після окремого погодження дизайну й конкретного deployment GO замінено
лише чотири host-файли. Встановлення: **11:26:59–11:28:22**, остаточна
перевірка **11:29:22**, 02.10.2026. Попередній стан issue #41 у розділі
вище описує етап до цього встановлення.

| Встановлений файл у /opt/avelren/deploy | SHA-256 | Походження |
| --- | --- | --- |
| restore.sh | `4c2644e9dde2146700fa665ab3048814c45c330aaa2836ddc82434ff91fb4104` | main 857eb61e; тільки source path ops → deploy |
| restore-engine.lib.sh | `f0b0364b0895c5a4bacf64f042b27ec55b82cf3020594100cfabf929f81dc5b4` | exact main 857eb61e |
| restore-verify.sh | `c3c21cb796db80d5d95ed6cdd150f45fee46b8929e6e28d55b3a3f27f3d55ef3` | exact main 857eb61e |
| restore-production.sh | `2af5e7c1b1f5402820d7edb179cad866f14be4f412ce2aa3b0a998004f2da34f` | збережений legacy source; додано ранній native collector topology guard |

Усі чотири файли root-owned 0755; bind mounts на них відсутні.
Старі bytes і uid/gid/mode збережено в root-only 0700
`/var/lib/avelren-restore-runtime/20261002-857eb61e/backups/`;
файли backup й `rollback.json` — 0600. Контрольні суми оригіналів
звірено з preflight, включно з раніше зміненим legacy engine.
Фактичну atomic replace/rollback функцію перевірено локально у Linux:
штучна відмова після третьої заміни, old bytes/uid/gid/mode відновлено.
На сервері відкат не знадобився.

Native engine включає ownership фіналізацію функції міграції 014
`activate_admin_after_pin(uuid)`. CLI зберігає старий source path,
verifier допускає лише disposable restore_test. Старий production
orchestrator тепер запускає вже встановлений, перевірений root guard
`/var/lib/avelren-collector-runtime/c655b2a2e928d480431f26508a122f69a3e87411/ops/collector-runtime-preflight.py`
перед traps, stop та читанням restore artifact. SHA guard:
`f10d7f7a99ce9382b252fa5cafa4d32b889c02612aab10722a29e3518d321295`.
Поточна managed spool-топологія отримує відмову до зупинки служб.

Три захисні сценарії не проходили на старих файлах; на кандидатах пройшли
разом із додатковим dependency-тестом CLI → engine → DB guard (4/4).
На фактично встановлених файлах повторно перевірено exit 2 для раннього
production guard, CLI без isolated contexts та verifier із live target.

### Повторне відновлення через встановлені entry points

Окремий проєкт `avelren-restore-issue41-20261002-857eb61e-installed`
використав той самий перевірений backup із SHA, наведеним на початку звіту.
Цього разу запускали **/opt/avelren/deploy/restore.sh** та
**/opt/avelren/deploy/restore-verify.sh**, які завантажили встановлений engine.
Bootstrap/source backend лишалися readonly exact main, disposable DB —
2.17.2 з власним томом/internal network, без ports/pollers/production volumes.

Усі сім native етапів — exit 0: DB start, fresh roles, legacy NOLOGIN,
guarded restore, schema/API verify, counts, cleanup. Відновлено
**3026358 observations**, **38 КПП**, **14 міграцій**; restoring=off.
Ownership/schema finalization і API smoke успішні на встановленому runtime.

Тестові Docker resources, backup, паролі в Compose, env, source і upload
видалено. Безпечний доказ 0600 залишено у 0700 каталозі
`/var/lib/avelren-restore-rehearsal/issue41-20261002-857eb61e-installed/`.
Receipt встановлення: root-only `acceptance.json` у каталозі restore-runtime.

### Робочі служби й критерії issue #41

- ID/image/restarts/started усіх робочих контейнерів незмінні; жодних
  stop/recreate/reload/reboot служб. До dirty checkout додалися лише
  погоджені заміни; сторонні локальні зміни та overrides збережено.
- API health/alert channel — ok. Останні п'ять циклів collector
  **11:25:21–11:29:21**: HTTP 200, по 38 observations, derived complete,
  60-секундний інтервал; 490 acked, **pending=0** (readonly звірка).
- Backup service: `Result=success`, `ExecMainStatus=0`, `ActiveState=inactive`.
  Це перевірка останнього успішного запуску; новий backup не запускався.
  Сам backup уже пройшов реальне відновлення двічі на серверному стенді.
- Живу БД, застосовані міграції, ролі, ОС і Docker не змінювали.

Критерії **issue #41 виконано**: встановлений isolated runtime узгоджено
з main, окремі preflight/GO отримано, installed-path rehearsal завершив
ownership/schema finalization, live API/collector/backup перевірено.
Закриття #41 не означає приймання повного production restore зі spool:
він навмисно залишається заблокованим. Production adoption, full restore,
Android/телефон і Play залишаються окремими етапами.
