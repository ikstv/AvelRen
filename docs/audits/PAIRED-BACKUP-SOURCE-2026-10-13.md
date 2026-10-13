# Узгоджений PostgreSQL + SQLite backup: source-етап 13.10.2026

Цей запис описує кандидат гілки `codex/paired-backup-20261013`, а не
серверне встановлення. [Погоджена специфікація](../superpowers/specs/2026-10-13-paired-postgres-sqlite-backup-design.md)
визначає межі. Локальний execution report —
`.superpowers/sdd/2026-10-13-paired-postgres-sqlite-backup/task-5-report.md`
(приватний робочий запис, не versioned repo artifact). Hosted CI точного PR head,
злиття, конкретний installation package і production GO — окремі етапи.
Зелений source-тест не приймає production RPO/RTO.

## Що зберігається

`backup.sh` за замовчуванням лишається `sql-only`. Намір перейти на paired
означає після окремого GO встановити весь пакет і явно записати
`AVELREN_BACKUP_MODE=paired` у приватний `/etc/avelren/backup.env`.
Саме перенесення нового `backup.sh` режим не вмикає. Нова backup unit має
безумовний `ExecStopPost=avelren-paired-backup recover` також для sql-only:
встановлення лише unit без coordinator/runtime manifest є неповним пакетом.

Під shared lease coordinator записує owned intent, чекає штатний writer on
ACK, робить SQL consistent dump і SQLite Online Backup поза live volume.
Producer продовжує штатні цикли: один persistent Device ID, початки через
60 секунд, незмінні endpoint/headers/error policy. Writer off ACK і pending
drain обов'язкові перед completion manifest. API доступний, але свіжість
тимчасово відстає під час capture-only. Копіювання має budget720s;
capture-only разом зі скасуванням/off ACK ≤900s, reserve180s; після off ACK
мережевий етап має окремий budget900s.

Комплект має `avelren-<UTC>.sql.gz`, `.spool.sqlite3.gz`, обидва `.sha256`
і `.pair.json`. Crypt upload/readback перевіряє plaintext bytes/SHA,
completion marker публікується останнім. Retention7 daily/4 weekly/3 monthly
прибирає перевірені paired groups; legacy SQL-only не видаляється під час
початкового ввімкнення. Каталоги приватні0700, artifacts/state0600.
Manifest/receipt не містять credentials, DSN, Device ID, payloads/raw errors.

## Датовані докази та межі

13.10 SQL backup від13.10 відновлено із schema/API PASS. SQLite від02.10
мала419 ACKed, pending0; SHA/integrity/payload validation/native open PASS.
Ці різні дати не утворюють узгоджену пару. Встановлений SQL-only backup SHA
`de881a23614d40336cb1a7f51495124e30e152b1762f32fb0e90bae9b86dfae9`
SQLite не включав. Source synthetic WAL/ACK/retry докази не замінюють нову
реальну пару off-host.

Локальний `bash ops/paired-backup-integration-test.sh` використовує справжні
daemon/Coordinator/Runtime, named Docker jobs, окремі projects/internal
network/volumes та synthetic HTTP transport, без єЧерги/FCM/Drive.
Тест блокує реальний pg_dump, вбиває coordinator SIGKILL, доводить припинення
owned job до off ACK, restart/drain, цикл до/під час/після backup, crypt
filesystem roundtrip і native Task4 restore/replay. Helper будується із
поточних package files у site-packages pinned app, з actual module origin,
SHA та UID10001 proof; mounted source/PYTHONPATH не є installed-helper proof.
Локальний offline base і WIP source tree фіксуються окремо від merged commit.
Hosted fixture будує backend звичайним Dockerfile із чинним lock; не додає
залежностей, workflow, schedule, visibility чи budget змін.

Internal `Runtime.for_disposable` приймає validated test manifest і лише
SQL project `<manifest project>-sql`; production CLI/defaults не змінені.
Task4 disposable rehearsal дозволяє `--app-image sha256:<64hex>` після
inspection exact immutable Linux amd64 image; mutable/missing image
відхиляється до startup. Production restore CLI/guards не відкриваються.

Фінальний local GREEN: base commit
`3a3504ea0313fe3c2e1be205a4f5b5ce1222e3b3` + Task 5 WIP host scripts;
project `avelren-runtime-test-pair-29216-867`, три цикли до/під час/після,
monotonic intervals **60.002721269 / 60.001747849 секунди**, pause **34.149s**.
API smoke в усіх трьох stages, persistent ID/restart/drain/один producer PASS.
Actual SIGKILL job termination перед off ACK і native ACK→SQL→spool→off
ordering PASS. Crypt ciphertext відрізняється; plaintext readback і manifest
SHA `a2a5057be3cef55988d0e61b89b6b3adf89d4fef124c3b892b13196d835f621e`
перевірено. Native isolated restore: retained ACKed1 + pending sequence2,
exact2 cycles/2 observations, primary2 runs/2 observations, pending0.
Own containers/volumes/networks/image tags прибрано; попередня `.tmp/task4`
fixture збережена. Це synthetic local measurement, не production SLA/RPO/RTO.

Actual local helper image
`sha256:3429403fa4d9b42247248f3067fcf44a04882115bfed9eaa822ada263ddc358c`;
collector transport fixture image
`sha256:582e4f9d2fa5d31a0df1e5f23ad1e5f673a478428310c7cd1fd13e9673a25806`.
Imported module `/usr/local/lib/python3.14/site-packages/avelren/paired_backup_spool.py`,
SHA `8d183918437e0e6c66cf8c35e428749512c0b9e349ed1b7f9148a3f2ccdf464b`,
UID10001/network none, actual own named live volume і окремий bind output.
Ці тимчасові images видалено після rehearsal; це не production package pins.

Source hashes host package на цьому WIP зрізі (після merge перелічити заново):

| Файл | SHA-256 |
| :--- | :--- |
| `backup.sh` | `fe0f5934652b6ef5944e69d2321a9adbffd02b2ceaf8e13cc841449509cd5077` |
| `paired-backup.py` | `efa50badd146d6b86e6afdecfff7edb0a5108c12efb61e3a9cba784b3e758251` |
| `paired_backup_manifest.py` | `705e8e2457a8763f64e3e348e9bc5b86f6a2bfadecd76ae3db700e09b4e83c24` |
| `paired_backup_state.py` | `a8a8fc7728994174ef768ddc0db5673612ea7cce36edbbf04bf03d71a3525a2d` |
| `collector-runtime-control.py` | `821b092594f7e836c2b9538242cb9b2a9b9fe1a0126d6afb380cc62530aad1c9` |
| `collector-runtime-preflight.py` | `f10d7f7a99ce9382b252fa5cafa4d32b889c02612aab10722a29e3518d321295` |
| `compose.collector-runtime.yml` | `a9a3f6024c8e7e673f459ca23b126379953a11b6c982fe96be258bf1216a9f24` |
| `avelren-backup.service` | `718afe586ffe55897813be4c8e6dca4fae48f7bbfcc35e63fbd3776ae5e26a20` |
| `avelren-backup-recovery.service` | `cd484ee800de61416614fb3a473b550f2c537e777474f8c2f29b8099b191c3da` |

Local GREEN: provenance/core/Android, backend Ruff, scoped host Ruff,
95 helper/collector units,210 classifier/workflow cases, host/native contracts
і Bash syntax/diff checks. Hosted exact-head CI та actual Ubuntu
`systemd-analyze verify` ще не виконані в цьому local stage.

Review fix-round 1 уточнює acceptance: TERM/HUP/INT входять у bounded cleanup;
усі removals виконуються best effort з aggregate errors, partial creation
реєструється **до** Docker/Compose call у private durable `owned.json`.
Outer shell чекає background Docker interruptibly, дає owner завершити cleanup,
потім за потреби запускає окремий bounded cleanup reader із exact fixture
prefix/labels/generation/runtime checks. Початкова помилка/receipt зберігається;
непідтверджений cleanup залишає private volume/ledger для розбору, не PASS.

Повторний actual local GREEN на base `9b1e99d` + fix WIP:
`avelren-runtime-test-pair-15752-25204`, intervals **60.024991173 / 60.001225144s**,
completion monotonic **816.748304372**, новий **completed/ACKed** producer start
**848.959997069** (після boundary на32.211692697s). Старі три captured requests
під час довгого backup більше не задовольняють «після»: потрібні timestamp
після completion, pending0 та ACKed count не менший за trace count свіжого
spool. Actual SIGKILL/crypt/native restore2 cycles/2 observations/pending0 PASS;
cleanup receipt PASS/errors[]/first_failure=null, own resources прибрано.
Focused cleanup/signal/partial-start/slow-backup regressions входять у existing
database workflow; незмінні довгі suites повторно не запускалися.
Перед native job startup observer атомарно записує private `job-owners.json`
із full runtime identity/generation та exact own spool/network; це покриває
preflight job до появи durable backup state. Interrupted Task4 rehearsal має
private `project.json` до startup; failed down зберігає WORK, а fixture fallback
перевіряє exact project/config/path/image/owner перед cleanup. Cancellation
чекає TERM cleanup власного live/unreaped child і лише тоді застосовує bounded
kill; збережений numeric PGID після reap не є authority. Narrow actual probes
перевірили foreign preservation, malformed journal aggregation і продовження
removals після першої помилки; ці observer/cleanup зміни не змінюють native
happy-path operations. Hosted exact-head gate лишається окремим.

## Конкретний пакет перед GO

### Уточнення final fix F1–F4, 13.10.2026

Наступний source-кандидат від base `8b2b38d105f5e891148dcf0364a201d7a9b01bf5`
виправляє lifetime control mutation та ownership recovery. Paired ON/OFF
виконує installed native `collector_control` у immutable helper image:
`avelren-paired-<generation>-control-on` та `-control-off`, network none,
UID10001, лише exact spool volume. Collector не recreates; native ACK,
CLI defaults, роль, DSN та cadence незмінні. Internal callable доступний
тільки з typed lease authority, native runtime preflight та operator lock;
public CLI/env authority bypass немає. Fixed Docker environment і shared
remaining deadline збережено. Імпорт control helper не має сигнатури producer
для чинного strict inventory guard; сам guard не послаблено.

Після read-only identity/off ACK checks coordinator атомарно записує
`prepared` **до** першого Docker create, включно з check. Production Runtime
перевіряє durable generation/runtime/authority перед create і перед start;
recovery адресно stop/inspect/remove/absence перевіряє п'ять job kinds:
check, sql, spool, control-on, control-off. Unproven termination не дозволяє
off/resumed/success. Початковий чужий capture-only відхиляється до generation
write/job creation. Це production protocol, а не лише observer journal.

Standalone recovery доводить exact expected record перед кожним write,
після cancel і off ACK. Заміна generation або інших полів означає categorical
nonzero ownership loss; replacement bytes, phase/reason/time не переписуються.
CI root-only existing contracts запускаються через sudo, усунуто лише дубль
control suite та додано syntax/run guard harness. Hosted non-root caller і
actual Ubuntu systemd verification лишаються required exact-head gates.

Actual baseline SIGKILL перед set-mode відтворив late ON **після** terminal
recovery/release. Focused actual daemon contracts пройшли17 tests,157.560s:
ON/OFF death після create до start та перед mutation, timeout/remaining budget,
no-state/old-terminal check death created/running, foreign mode/generation/runtime
preservation. Pure coordinator36 tests і CI privilege/guard wiring PASS.
Native rehearsal і остаточні exact source hashes/evidence описані нижче;
private повний запис — `final-fix-report.md` у тому самому SDD directory.

Попередня concurrent rehearsal відхилена strict single-producer guard;
own cleanup PASS. Serial rehearsal completed backup/off ACK/drain, але strict
HTTP-handler trace interval59.999789516s відхилив її. Обидва first failures
та cleanup receipts збережені. Timestamp усередині synthetic transport має
dispatch latency після штатного `RequestPacer.wait`; fixture тепер лише
awaits **original** wait і записує його actual `self.last_start` перед send.
Strict≥60s та completed/ACKed-after-backup перевіряються на native request
attempts із one-to-one request trace; transport timestamps/intervals збережені
окремо. Clock/sleep/production pacing і deadlines не змінені, tolerance немає.
Observer додає лише append/read після штатного wait; це synthetic acceptance
boundary, а не production timing/RPO/RTO. Jitter predicate RED→GREEN2 PASS.

Наведені вище історичні source hashes не є pins цього уточнення; після merge
отримати нові package hashes. Immutable helper має також installed
`avelren.collector_control` (origin/hash proof), без backend source changes.

Final serial native GREEN: `avelren-runtime-test-pair-11788-9542`, base8b2b38d
із final-fix WIP, `source_kind=working_tree_fixture`. Actual native attempt
intervals **60.007477482 / 60.001416136s**; downstream transport intervals
**60.010783215 / 59.998247277s** записані окремо. Completion2142.900992896 →
new completed/ACKed native request2148.736782367; pause40.383s. SQL-job SIGKILL:
owned jobs absent2066.804507428 → off ACK2075.227818891. API/persistent ID/
native restart/drain/single producer, crypt readback та restore/replay PASS:
ACKed1 + pending sequence2 → exact2 cycles/2 observations, pending0.
Manifest SHA `fa3bd260de61b1dd1cb880f7509daeb5976352a40cadb094139dedd7e6ad52db`.
Cleanup PASS/errors[]/first_failure=null; Task4 inputs збережені.

Installed helper image
`sha256:a360e2024963357c598f2d17a9bef2723fc3fcda67f692ae1ac539c7f53116ac`;
collector fixture `sha256:e292d81062953a301f82ecb8cdcc295bba9cc2d72b34ba76922f67965c383669`.
Helper UID10001, imported site-packages paired module SHA8d183918…464b,
native collector_control origin `/usr/local/lib/python3.14/site-packages/avelren/collector_control.py`,
SHA `650235032a897abe06ceaa55b0fcf6c45569873900f8a0a38e6a2500a4a98b4f`.
Тимчасові images прибрані; source/installed fixture proof не є production pins.
Final state26 tests PASS; FIFO startup має окремий bounded ready handshake,
сам FIFO read зберігає deadline0.5s. Strengthened actual timeout1 PASS21.275s:
shared remaining2s/<4s call, running exact owned helper/marker до cancel,
absence перед release і no late ON. Timeout gate стоїть перед native imports/
SpoolStore initialization; SIGKILL probes окремо gate-ять exact set-mode hook.
Раніший слабкий timeout тест не доводив досягнення remote mutation boundary;
його source звіт уточнено, deadline не розширено.

Після merge отримати actual merged SHA, source hashes і approved immutable
helper image ID: не підставляти WIP rehearsal IDs у production пакет.
Зберегти поточні host/unit/env files та їхні hashes/UID/GID/modes поза checkout.
Пакет має містити:

- `/usr/local/sbin/avelren-backup` ← `ops/backup.sh`, root0755;
  `/usr/local/sbin/avelren-paired-backup` ← `ops/paired-backup.py`, root0755.
- Поруч root0644 `paired_backup_manifest.py`, `paired_backup_state.py`,
  `collector-runtime-control.py`, `collector-runtime-preflight.py`: native
  imports залежать від сусідніх файлів. Не переносити один executable окремо.
- Trusted root-owned `compose.collector-runtime.yml`, точний приватний
  `/etc/avelren/collector-runtime.json`0600 і state directory0700, matching
  active source/image/container/volume/network. Чужий старий exited collector
  не є active producer. Не recreates collector для helper installation.
- `/etc/avelren/docker-client`0700, `cli-plugins`0700 та офіційний executable
  Compose5.5.1 root0755 SHA
  `db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576`.
  Лише default Docker context; config absent або `{}`/default. Серверний
  plugin SHA `9c0f3f21b463fbdd42afed3be203c1a65f0cd440c9b59c68785f35e78d2ebf6a`
  не приймається за збігом version. Не змінювати expected hash мовчки.
- Approved helper image із installed `avelren.paired_backup_spool`, imported
  SHA, embedded `AVELREN_GIT_SHA`; network none, UID10001, окремий0700 output
  bind. Без baked DSN/password/token. Env: `AVELREN_BACKUP_HELPER_IMAGE`,
  `AVELREN_BACKUP_HELPER_SOURCE_COMMIT`, `AVELREN_BACKUP_HELPER_SHA256`,
  `AVELREN_BACKUP_COMPOSE_SHA256`. `AVELREN_BACKUP_PASSWORD` inherited лише
  dump child, role саме `avelren_backup`; пароль не в argv/stdout.
- `avelren-backup.service` і `avelren-backup-recovery.service` root0644;
  `/etc/avelren/backup.env` та crypt config0600; exact work/stack/remote/
  receipt/stamp paths. Actual Ubuntu `systemd-analyze verify` обов'язковий
  hosted gate; source assertions не замінюють його.

Read-only 13.10: canonical `/etc/avelren/collector-runtime.json` і controlled
Docker client ще відсутні. Наявний root0600 runtime manifest:
`/var/lib/avelren-collector-runtime/c655b2a2e928d480431f26508a122f69a3e87411/manifest.json`.
Свіжі поля: source_commit `a4a16b64147fcf28c6245f2032a61279ca7c74ec`, image
`sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3`.
Env/compose/state — `collector.env`, `ops/compose.collector-runtime.yml`,
`state` під тим самим exact directory prefix; production project/container/
network/volume стандартні. Canonical package manifest зберігає ці свіжо
перевірені fields та **існуючий state_dir**, щоб lock/recovery мали ту саму
authority; не вгадувати новий state directory або давній collector commit.
DB config_files має всі чотири **впорядковані** paths:
`/opt/avelren/docker-compose.yml`, `/opt/avelren/docker-compose.override.yml`,
`/var/lib/avelren-release-check-20260924/deploy-013.yml`,
`/var/lib/avelren-release-1.0.3/aecbfa66a2b704f6d1c266c756516d9c22bfbc02/release-off.json`.
Явний `AVELREN_BACKUP_COMPOSE_FILES` повинен зберегти цей порядок і чинні
pins; не вгадувати старий application prefix або release-on файл.

Root trust зараз відхиляє `/opt/avelren`1000:1000 mode0755, base Compose
1000:1000 mode0664 та `.env`1000:1000 mode0600. Пропозиція для окремого
перевіреного GO: bounded metadata normalization **лише** цих трьох attested
paths до root ownership і base Compose0644, directory0755, `.env`0600,
із незмінними content hashes/paths/config_files labels. Override вже
root0644, migration pin/release-off root0600. Жодного recursive chown,
перенесення stack в інший path або послаблення guard. Перед approval звірити
свіжі metadata/content hashes; rollback повертає точні prior1000:1000 і
0755/0664/0600 тільки цим paths. Це proposal, не дозвіл на запис.

## Перший запуск, відкат і reboot

До first-run GO перевірити повний пакет/hashes/installed imports, effective
ordered Compose labels/image/network/DB IP, crypt type, ≥2GiB work space,
spool quota запас на15хв, actual source schema/ACL та lease-free off ACK.
Після first run звірити unchanged producer identity, off ACK/drain/no error,
receipt/stamp і downloaded/decrypted five files із exact hash/size/manifest.
Відновити **нову реальну пару** штатним disposable rehearsal, звірити retained
ACKed SQL values та FIFO pending replay без дублів. Виміряти snapshot
boundary/pause/повний recovery час. До цього RPO/RTO не прийняті.

SIGKILL/host crash потребує owned recovery під shared lock після Docker
startup; intent/generation/identity і dead owner доводяться, named children
зупиняються/inspect/remove до off. Systemd ExecStopPost/OnFailure та next-run
preflight wired; після повної відмови host оператор викликає canonical
`avelren-paired-backup recover` після перевірки пакета/runtime. При чужому
takeover/restart, незрозумілій ownership/off ACK не вгадувати стан: залишити
категорійний recovery_required, spool не видаляти, success stamp не приймати.

Rollback: спочатку довести owned child termination/off ACK/drain; потім
повернути exact saved scripts/libs/units/env і bounded metadata, виконати
systemd reload/verify за окремим GO. Не замінювати runtime/volume. Legacy
maintenance/adoption/production restore commands, які не поважають новий
lease, заборонено запускати паралельно paired backup; відсутність у них
guard не є дозволом. Deployment/DB-role transition/monitor/APK/phone/Play
та production restore acceptance лишаються окремими пунктами реєстру.
