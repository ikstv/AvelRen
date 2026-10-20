# Collector recovery, paired backup і off-host restore — 20.10.2026

За окремим owner GO встановлено погоджений host/helper пакет, завершено
керований handoff legacy collector, прийнято природні цикли, створено нову
production-пару та відновлено її off-host. Timer повернуто після цих PASS.
Це фактичне приймання серверного етапу, яке уточнює
[стан 19.10](RECOVERY-REVIEW-2026-10-19.md); Android і Play не приймалися.
Усі часи нижче — UTC.

## Source, образи та межа зміни

- Production source: `6ba462b5ed9341270d552626b8af1039813ec721`, PR #150.
  [Main CI 39390778658](https://github.com/ikstv/AvelRen/actions/runs/39390778658)
  завершив 11/11 jobs SUCCESS о 08:44:53.
- Exact collector/helper image:
  `sha256:c5ed1370f6880cfd0d57f3f4866f8d0bfac5f8f8d04a3abb8dda3f4775fae3ab`.
  Локальне й серверне installed-byte attestation пройшли; host install
  перевірено о 08:52:08. API/notifier, DB, watchdog, surge worker і Caddy
  цим rollout не перескладали й не перестворювали.
- Off-host harness:
  `4c0f13907e5de7b0a9bd7f40d6213b8c24f5f8f2`, окремий від source образу.
  Review і локальні regressions прийняті; hosted CI/merge цього малого
  виправлення на момент запису ще не виконані.
- Локальний runner SHA-256:
  `cd444e11381939c2806db8d2e1d311bd2b6ef7ed4c5a59479c9fd35c8cb3ce01`.
  Linux controller:
  `sha256:350ee315fbb8a9a50bf674eb3e0c9449267b905d645dafbcfc7ddd866b86ae86`;
  restored app використовував exact production image вище. Контролер без
  мережі, окремий daemon-visible volume, штатний isolated Compose; пакети
  під час запуску не встановлювали.

## Handoff і природні цикли

Штатні prepare → switch → finish завершені о **08:56:40**:
journal `complete`, backup state `resumed`, children порожні, source/image
активного collector збігаються з pins. Постійний Device ID збережено;
приватне значення до доказів у Git не включено.

О **09:00:30** прийнято перші п'ять циклів. Фінальна повторна перевірка
о **09:17:49** підтвердила:

- 22 природні цикли; усі 21 спостережений SQL-інтервал — 60 секунд.
  Між останнім циклом старого й першим нового writer — 235 секунд;
  це інтервал між циклами, не вимір тривалості недоступності API.
- HTTP200, успішний запис і derived processing; 38 актуальних рядків workload,
  SQL-значення та legacy/measured ETA formulas перевірені. Health `ok`,
  вік останнього observation у фінальному snapshot — 34 секунди.
- Spool: 22 ACK, pending=0, capture_only=false, mode_ack=false,
  last_error відсутній. Journal `complete`, після нової публікації state
  перейшов у `published`.
- Identity решти контейнерів незмінна; owned handoff helper прибраний.
  Після backup stamp вже відбулися три наступні природні цикли.

## Нова production-пара та фактичне off-host відновлення

Backup ID **`20261020-090106`** має нові invocation, generation, receipt і
stamp. Service працював 09:00:45–09:14:53, завершився exit 0 / success.
Пауза запису до PostgreSQL — **45,276 с**, збір у spool продовжувався;
решта часу включала публікацію й перевірку
сховища. SQL snapshot — 09:01:06.004851–09:01:22.669594,
spool snapshot — 09:01:22.669645–09:01:27.309905.
Receipt підтвердив writer resumed і pending=0 на resumed/before_manifest/published.

П'ять файлів отримано off-host і перевірено за manifest, gzip та SHA-256.
Manifest SHA-256:
`20341bda2a2a7a32a66a6084ffcf727511d5e4b55672144fcea11f0e9b94f18a`.
У snapshot 5 ACK, 1 pending, 0 started; діапазон sequence 19646–19651.

Native restore із Timescale pre/post hooks, ownership/schema/API verification
та strict replay завершився exit 0:

| Перевірка | Результат |
| --- | --- |
| Verified cycles / observations | 6 / 228 |
| Уже ACK cycles / observations | 5 / 190 |
| Replayed sequence | 19651 |
| Recovered started / pending після replay | 0 / 0 |
| SQL totals після відновлення | 107267 runs / 4014776 observations |
| SHA п'яти вхідних файлів до/після | Незмінні |
| Cleanup / власний volume | PASS / видалений |

Це відновлення **нової production-пари**, окреме від synthetic RED/GREEN
перевірок інструмента. SQL totals належать відновленому snapshot; вони
не зобов'язані дорівнювати пізнішій live БД, куди collector продовжує писати.

Чотири SQL Timescale jobs зберігали owner `avelren`; новий writer manifest
цього не змінює. Явна `--legacy-timescale-owner avelren` створила guarded
NOLOGIN placeholder лише у disposable DB. Manifest і payload profile
лишилися `modern_strict`; production роль, writer allowlists та per-cycle
markers не послаблювали. Виконання legacy background jobs у DR не прийняте.

## Timer, відкат і докази

Timer повернуто о **09:19:20**, після actual restore і фінального runtime PASS:
enabled, active, waiting. Наступний trigger за readback —
**21.10.2026 03:25:27 UTC**; майбутнє виконання цим записом не підтверджене.
Receipt/manifest корелюють за backup ID; stamp — за UTC,
state — за новою generation/identity/phase та тією самою invocation.

О **09:20:37** завершено операційний cleanup: зупинено чотири завершені
transient handoff units і скинуто лише історичний failed-статус recovery
від 03:23, після всіх фактичних PASS. Published state незмінний;
`reset-failed` не був доказом успішного backup.

Host rollback-файли та safety SQL/spool captures залишені root-private.
Збережено старий image `sha256:40219d6c8ceee5a862382dbb62fe3df06181a20488635d47c5a965512eda9a72`
як `previous-collector-image.tar` у приватному release-каталозі на сервері:
70496768 bytes, SHA-256
`06b85b03fe62e5630f4e1ffa44a1ba5e020f626f4f5b7cd456c924a92e1e9920`.
Це збережений матеріал відкату, не доказ виконаного production rollback;
чинні guards щодо backlog і identity залишаються обов'язковими.

[Скорочений безсекретний receipt](collector-recovery-2026-10-20-receipt.json)
містить exact pins, counts, п'ять input hashes, timer readback і SHA-256
одинадцяти вихідних evidence JSON. Повні receipts збережено локально в
`deployment-20261020-pr150`; SQL, SQLite, credentials, device identity
та сирі remote command arguments до Git не переносили.

## Що залишається

Наступний користувацький етап — FullTest APK із чистої актуальної main,
commit/version/certificate/SHA-256 та телефонна матриця threshold/ETA:
звук, кожен «ОК», природний п'ятихвилинний повтор, foreground reconciliation
і DELETE/cancel. Android reconciliation після DELETE вже у source;
його наявність не є прийманням конкретного APK.
Потім потрібен окремий Play update/release етап із сумісним підписом
і збереженням даних. Android, телефон, Play, R08 sender/availability gate,
legacy role retirement та решта backlog цим серверним етапом не закриті.
