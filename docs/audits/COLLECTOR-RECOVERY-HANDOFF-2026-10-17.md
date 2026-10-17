# Локальне приймання collector recovery handoff — 17.10.2026

Результат: source-механізм і перевірки завершені локально. Сервер, його timer,
services, runtime manifest, spool і backup state не змінювалися. Новий diff не
публікували, hosted CI/merge цього diff не виконували.

База: main `b009a275e058af9334ef02cd23039f06cebdd3a8` після PR #149.
Native acceptance запускала working-tree fixture, не main release image.
Порівняно всі 58 установлених Python modules сучасного helper зі source;
додатково всі 64 runtime-файли backend/host збігаються з прийнятим snapshot.

## Перевірки

| Перевірка | Результат |
| --- | --- |
| Backend unit | 707 PASS, 2 сторонні deprecation warnings |
| PostgreSQL/TimescaleDB suite | 280 PASS; 296,73 с |
| Linux handoff | 22 PASS: CAS, locks, proc, boot/PID, crash/refusal, safety drift, candidate binding, WAL |
| Наявні lease/state | 26 PASS |
| Daemon boundary / real Docker cleanup | 9 / 7 PASS; повні generation/runtime label pairs, foreign jobs збережені |
| Handoff wiring / CI workflow | 4 / 38 PASS |
| Legacy ETA/collector | 17 PASS |
| Ruff / provenance / CI scope verifier | PASS |
| Native paired / restore | PASS, fixture `avelren-runtime-test-pair-261017-8055` |

Production-count тест: 1 439 aged ACK, по одному синтетичному observation.
Помилка останнього SQL рядка відкочує всі marker-записи. Після виправлення
fixture SQL повністю перевірено, payload і SQL збережені; штатний prune
видаляє лише 1 439 aged ACK/markers, зберігаючи новий started цикл. Це модель
кількості й формату, а не копія production даних. Окремий mixed тест охоплює
aged/unaged legacy ACK, committed pending, modern ACK, uncommitted pending,
started, повтор migration і strict restore без дублювання SQL.

## Native handoff і paired restore

Історичний disposable image встановлює точні captured collector/db/models/ETA
байти; його image ID відрізняється від production і явно так записаний.
Synthetic transport підтверджено до запуску, мережа internal. SQL справді
має `legacy_unknown`, без штучного UPDATE статусу. Сучасний helper встановлює
повний canonical package без legacy overlay.

Пройшли: orphan control-off при порожньому children[], empty-backlog rollback,
повтор prepare зі свіжими pins, реальний SIGKILL у durable start_intent,
відмова звичайного recovery під час handoff, продовження exact candidate,
native off ACK і drain. Зафіксований інтервал переходу 64,801 с.

Нова синтетична pair: `20261017-080544`, 17.10.2026 UTC. Publication,
local crypt ciphertext, перевірений plaintext readback і штатний isolated
restore/replay пройшли. Snapshot: acked=4, pending=1, started=0; pending був
replayed один раз. Restore перевірив 5 cycles / 3 observations; SQL totals:
6 runs / 4 observations, включно з legacy SQL поза spool. `pending_after=0`.
Started fixture відновився до створення pair; окремий DB restore-тест перевіряє
started recovery. API smoke до/під час/після, persistent Device ID і один
producer пройшли. Інтервали native starts: 60,001 с, 60,001 с; restart 124,157 с.
Cleanup іменованих ресурсів стенда та зовнішнього controller/data volume пройшов.

## Межі й наступний крок

- Перевірено синтетичний local crypt, не production remote, credentials або
  поточний серверний dataset. Docker engine стенда 29.8.2; попередній серверний
  read-only знімок містив 29.8.1. PostgreSQL/TimescaleDB і Python dependencies
  використовували pinned/cached образи й lock без оновлення залежностей.
- Crash між recreate і durable записом нового ID, інший boot, PID reuse,
  foreign jobs або backlog при legacy rollback залишають interlock активним.
  Автоматичного adopt/скидання JSON немає; потрібна окрема перевірена дія.
- Поточний strict legacy контракт приймає literal legacy_unknown; pre-015 NULL
  не маскується. Потрібна свіжа read-only звірка реального dataset перед GO.
- Зміна Docker inventory під час scan може безпечно зупинити крок. Паралельні
  контейнерні deployment/тести під час handoff не планувати.
- Новий source треба опублікувати на review/CI, злити й побудувати новий image
  з чистої main та узгоджений host/helper пакет. Старий b009a27 artifact не
  містить migration модуля. Deployment, реальна paired copy, off-host restore
  і повернення timer потребують окремого GO за [runbook](../../ops/COLLECTOR-RECOVERY-HANDOFF.md).

Технічні докази: native receipt/source-module SHA map, `recovery-tested-source-proof.json`,
Linux contracts і suite logs у локальному пакеті результатів. Вони не є доказом
production deployment або свіжої production копії.
