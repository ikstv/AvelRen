# Залишки перенесення

## Власність FCM-токена — локальне source приймання 12.10.2026

Після whole-branch findings R1–R3/M1 Android source виправлено комітом
`5ab29ea4a49dfed1075cd2e935c5db1f7fe2233a`: точна full JVM suite
**301/0/0**, compile/lint успішні; lint **0 errors/40 warnings/6 hints**.
Same-token active callback coalesced, scheduler APPEND_OR_REPLACE,
реальний foreground pending recovery і blocked startup SDK readback
перевірені; terminal Rejected має explicit retry без rotation.
[Точний контракт, RED/GREEN і межі](FCM-TOKEN-OWNERSHIP-2026-10-12.md).
Scoped re-review та exact-head hosted CI/SBOM ще очікуються. M2 warning baseline
збережено; acknowledged commit не замінювався apply. Server deployment,
APK/version/SHA-256, телефон і Play не виконувалися й приймаються окремо.

[Контракт, перевірки та послідовність релізу](FCM-TOKEN-OWNERSHIP-2026-10-12.md)
описують server typed409 та bounded durable Android recovery. Інтегрований
попередній кандидат від `f1cfde8` до `3d1358a`: backend unit 669 passed, full API 104 passed;
default DB 190 passed (14 notifier), Android JVM 293/0/0, compile/lint успішні;
фактичний urllib3 2.8.0. Whole-branch review, exact-head hosted CI/SBOM та
злиття ще очікуються; API deployment, APK/SHA-256, телефон і Play — окремі gates.

Цей запис уточнює нижчі датовані статуси: notifier PR #122 MERGED у main
`ad9e92a6`, 7 PR checks успішні, main push run не спостерігався. urllib3
update `162669e` незалежно reviewed та інтегрований у кандидата. Maintenance
plan і CI-gate plan погоджені, але не реалізовані. Production CLI/DSN cutover
залишаються закритими; PostgreSQL logging і свіжий rollback перевіряються
перед окремим deployment GO. Старий APK може потребувати update для conflict
recovery; доступ до оновлення не повинен залежати від push. Release 0.1.3
не опублікований до phone/Play gates.

## Уточнення — 12.10.2026

[Звірка надісланого аудиту](audits/AUDIT-TRIAGE-2026-10-12.md) підтвердила
два кодові сценарії FCM token і відсутність main protection. Виправлення,
real API/PostgreSQL-регресії та aggregate CI gate ще не реалізовані.
Rulesets API повертає тарифний403; privacy/billing не змінені.


DB executor source етапу 1 прийнято [PR #121](https://github.com/ikstv/AvelRen-ORIGINAL/pull/121),
main eed0cb0f5a337e88467943017bbca3a04d2593e2. Усі 8 exact-head PR checks та relevant
main workflows успішні. Hosted DB: 176 passed; upgrade: 262 passed, 1 попередній skip.
Це уточнює нижчий запис про source кандидата, review/CI та злиття; live adoption
не виконаний, production CLI залишається закритим.

Підготовлено [план maintenance adapter та відновлення служб](superpowers/plans/2026-10-12-postgres-production-maintenance.md)
для перегляду власником. Його реалізація, isolated приймання та operational GO попереду.
DSN cutover, recovery PostgreSQL/SQLite, live monitor, телефонне приймання
і закриття старих репозиторіїв залишаються окремими роботами.
## Оновлення urllib3 — source кандидат 12.10.2026

[Обмежений security update](URLLIB3-SECURITY-UPDATE-2026-10-12.md) змінює
лише urllib3 2.7.0 → 2.8.0 та його офіційні hashes. Оригінальне походження
lock збережено окремо від revision. У повторній PyPI metadata перевірці
35 точних Python pins: 0 affected packages, 0 помилок; контейнерні/Gradle
та live залежності не перевірялися цим scan. Review, інтеграція та hosted
CI кандидата від `c70dd8c` ще очікуються. Exact-image handoff і окремо
погоджене deployment залишаються відкритими; production та телефон
не прийняті цим source оновленням. Загальний scope supply-chain #23
залишається ширшим за ці три urllib3 advisories.

## Захист оновленого FCM-токена — кандидат 12.10.2026

[Контракт і локальна перевірка](NOTIFIER-TOKEN-RACE-2026-10-12.md): notifier
очищає лише точний токен, надісланий до FCM. Запізніла dead-token відповідь
не видаляє новий токен, а cancel зберігає чинну обмежену політику повторів
за віком. 14 регресій на справжній ізольованій PostgreSQL/TimescaleDB
перевіряють threshold/ETA, normal/cancel, оновлення другим підключенням,
поточний dead token і недеструктивний INVALID_ARGUMENT.
Це source кандидат у гілці `codex/notifier-token-race-20261012` від бази
`eed0cb0`; review, hosted CI, злиття та operational приймання ще очікуються.
Серверне розгортання й телефонну доставку цими тестами не підтверджено.

## Актуальний підсумок — 11.10.2026

[Свіжа звірка сервера й підготовлених PR](audits/MIGRATION-SERVER-2026-10-11.md)
уточнює історичні рядки нижче: на сервері schema 001–016 і TimescaleDB 2.30.1,
collector працює щохвилини, прогноз має non-null scores на чотирьох КПП.
Collector/watchdog досі під legacy superuser; повний restore зі spool
і production перехід прав не прийняті. PR #106/#107/#113–#116 злиті в main
після успішного CI відповідних heads; [merge-коміти й докази](audits/MIGRATION-INTEGRATION-2026-10-11.md).
Спільні ізольовані перевірки виконані. Наступні блоки —
права/recovery/monitoring і release acceptance. Не повторювати
вже прийняті переноси лише через незакритий історичний рядок.

Зовнішній monitor: [ручний перенос](EXTERNAL-MONITOR-TRANSFER-2026-10-11.md)
зберігає три перевірки та lifecycle issues. PR #118 злитий у main `1fdcbf2`
після 4/4 CI checks head `f94243c` та незалежного review. Live приймання попереду;
старий scheduled monitor активний, автоматичний запуск у ORIGINAL не увімкнено.

Права БД: [production adoption runbook 001–016](POSTGRES-ADOPTION-PRODUCTION-RUNBOOK.md)
адаптує процедуру старого AvelRen-ops. DB executor та explicit inverse
реалізовані й ізольовано перевірені як source кандидат етапу 1
(`c84d0a9..69c25cc`, [контракт і rehearsal](../ops/POSTGRES-ADOPTION.md)).
Публічний production CLI закритий. Actual maintenance adapter, його host/runtime
provenance, stop/start/job pause/resume і operational acceptance ще попереду;
runtime DSN cutover має окремий план. Whole-branch review, exact-head CI
та злиття цього кандидата не підтверджені цим source записом.

## Ownership/ACL — кандидат 08.10.2026

Додано [inventory, forward/inverse та disposable executor](../ops/POSTGRES-ADOPTION.md)
для 001–016, включно зі стисненими chunks і continuous aggregate. Це source
кандидат поверх [PR #106](https://github.com/ikstv/AvelRen-ORIGINAL/pull/106);
CI має підтвердити точний head. Production adoption, provisioning, DSN cutover
та retirement ще не прийняті. Попередні датовані рядки описують історичний стан.

## Перевірка прав БД — кандидат 08.10.2026

Додано [read-only privilege gate](../ops/POSTGRES-PRIVILEGE-GATE.md) для
схеми 001–016 із негативними тестами на одноразовій TimescaleDB.
Це перенос introspection-контракту старого `AvelRen`, а не adoption.
Ownership forward/inverse, runtime DSN cutover і процедура зі старого
`AvelRen-ops` залишаються наступним блоком. Production gate не запускали;
міграції, ролі та active DSN не змінювали. Нижчі датовані рядки про відсутній
gate описують стан до цього кандидата.

Оновлення 03.10.2026: [серверна частина 1.0.3 прийнята](audits/RELEASE-1.0.3-SERVER-2026-10-03.md),
прогноз увімкнений; TimescaleDB 2.30.1, schema 016. API/notifier/worker
мають перевірений main bc41a15. Collector, watchdog і Caddy зберігають
свої попередні прийняті образи. Повне переведення legacy runbook/прав БД,
відновлення зі spool та телефонне приймання лишаються окремими роботами.
Наведений нижче зріз 28–30.09 є історичним; новіші датовані докази мають пріоритет.

Документальна звірка 30.09.2026 на базі main
`01e467c0dcf711067c6b0afa831652e4b305060b` після merge PR
[#67](https://github.com/ikstv/AvelRen-ORIGINAL/pull/67): repository,
source-sbom та image-sbom checks цього коміту успішні.
Це поточний контрольний список; датовані старі аудити зберігають історичний зміст.
Перенесено [серверний аудит 28.09](audits/PRODUCTION-IMAGE-PARITY-2026-09-28.md)
із AvelRen-ops PR #1 зі збереженням походження. Цей перенос не є новою
перевіркою сервера або телефона; наведений runtime-стан датований 28.09.

## Уже є в новому репозиторії

- Серверне ядро, API/Admin, Android, міграції, runtime Compose та телеметрія.
- Retention 90 днів, виправлення MAE=0, оцінювання прогнозу на окремих семи днях.
- Backup, ізольований Timescale restore, manual production restore orchestrator
  із перевірками та зупинкою процедури при невідповідності передумов.
- PR #53: шість успішних CI checks для `f52f68e`; локально 200 backend unit,
  22 database tests, Android unit/compile та ізольований restore rehearsal.
- Source SBOM із перевіркою Python lock completeness (PR #65/#66) та
  candidate image SBOM для app, TimescaleDB і Caddy (PR #67). Перевіряється
  Python/OS package coverage; artifacts зберігаються 30 днів без push/deploy.

## Відкриті роботи

| Блок | Конкретний результат для закриття |
| --- | --- |
| Supply-chain legacy #140 / issue #23 | Source та candidate image SBOM уже реалізовані й мають успішні checks; повторно переносити їх не потрібно. Залишилися рішення по Gradle artifact checksums, Dependabot, dependency/container vulnerability audits і CodeQL із ліцензійним блокером для приватного user-owned repo. Перед exact-image deployment потрібен окремий handoff immutable image/digest: SBOM CI candidate не засвідчує окремо перебудований production image. |
| Production adoption прав БД, legacy [AvelRen#15](https://github.com/ikstv/AvelRen/issues/15) | DB executor001–016, binding/receipts та explicit inverse прийняті [PR121](https://github.com/ikstv/AvelRen-ORIGINAL/pull/121), main eed0cb0, exact-head CI успішний. Повторна реалізація не потрібна. Production CLI закритий до actual maintenance adapter: [план для перегляду](superpowers/plans/2026-10-12-postgres-production-maintenance.md). Actual host/runtime provenance, stop/start/jobs, DSN cutover і operational acceptance ще попереду з окремими GO та свіжим audit. |
| Forecast legacy #111 / ORIGINAL [#70](https://github.com/ikstv/AvelRen-ORIGINAL/issues/70) | PR #72 злитий 02.10.2026, merge d134c0b; server missing/0/legacy_unknown і Android wait_estimate/DTO/UI уже у main. Повторний перенос не потрібний. Короткий історичний backtest не є release gate: залишилися довший holdout, recovery та окреме приймання на телефоні. Див. [звірку аудиту12.10](audits/AUDIT-TRIAGE-2026-10-12.md); не оголошувати missing справжнім нулем без урахування status. |
| Сповіщення про реліз, R08 | Завершити серверний release_notice, перевірку доступності в Play та наскрізне приймання доставки. |
| Старі issues #19/#23/#25/#26 | По пунктах звірити FCM ownership/delete-installation, supply-chain вимоги, privacy та release/recovery runbooks; реалізувати або явно відкласти прийняті залишки. |
| Ops і recovery | Аудит із AvelRen-ops PR #1 перенесено; сам старий PR лишився відкритим. Завершити звірку deployment/recovery runbooks, доступів/key escrow, матеріалів Play та унікальних серверних змін із новим кодом. Історичні документи потребують рішення про збереження або заміну. Наявність архіву не доводить відновлення. |
| Керування spool-collector | PR [#77](https://github.com/ikstv/AvelRen-ORIGINAL/pull/77) злитий; 02.10 після окремого GO встановлено collector-only Compose і control, прийнято п'ять циклів на сервері. Повторювати цей перенос не потрібно. Restore guard встановлено й перевірено 02.10 о 11:29: [приймання runtime](audits/RESTORE-REAL-BACKUP-2026-10-02.md#встановлений-runtime--приймання-о-1129-за-києвом). Залишилися адаптація legacy postgres-adopt і окремий повний restore зі звіркою БД/SQLite. |
| Приймання на сервері та телефоні | За погодженими операціями зняти свіжі докази runtime/ролей/міграцій, перевірити реальний backup лише в ізольованій БД, сумісність APK↔API та спосіб відкату. Злиття #53 цього не виконує. |
| Закриття міграції | Звірити гілки без PR, теги, releases, issues та унікальні файли обох джерел. Після приймання — окреме рішення про архівування чи видалення. |

## Серверний стан, який потрібно перевірити заново

За [аудитом 28.09](audits/PRODUCTION-IMAGE-PARITY-2026-09-28.md) сервер
використовував checkout `/opt/avelren` на `81e5b04` із чотирма зміненими
tracked-файлами та п'ятьма untracked backup-файлами. Runtime мав різні
локальні образи й стару Compose-модель із overrides; notifier додатково
використовував `deploy-013.yml`. TimescaleDB 2.17.2 і Caddy 2.9.1 старіші
за pins нового main 2.30.1 і 2.11.4. Це не дозвіл їх оновлювати.

Наступний read-only зріз має підтвердити:

- Фактичні image IDs і походження коду кожного контейнера. Для collector
  running image `f52aad81…` відрізнявся від `latest` (`978ec2d9…`), а старий
  image object не знаходився; перед recreate потрібен recovery plan.
- Повний effective Compose із усіма overrides, dirty checkout і host pin.
- SHA всього журналу міграцій, фізичну схему, runtime-ролі та права БД.
  Остання позначка 014 у старому зрізі не доводить повної сумісності схеми.
- Хеші встановлених host-скриптів, backup-стан і доступність recovery-артефакту.
- Функціональні відповіді API та роботу collector/notifier/watchdog.
  `running`, `healthy` БД і revision labels не замінюють ці перевірки.

Наявність API/watchdog/notifier revisions в історії нового main не доводить
тотожності їхніх окремих production-збірок CI candidate або його SBOM.

## Контроль інвентаризації

Зріз GitHub 30.09.2026: AvelRen має 11 відкритих PR і 8 відкритих issues,
19 гілок включно з main; AvelRen-ops — 1 відкритий PR
[#1](https://github.com/ikstv/AvelRen-ops/pull/1), 0 відкритих issues і
2 гілки включно з main. Попередній запис «0 PR в ops» був застарілим.
За [реєстром PR](LEGACY-PR-REGISTER.md): 8 замінені, 2 відкинуті з причиною,
1 (#140) тепер частково замінений: SBOM реалізовано, а CodeQL потребує
окремого ліцензійного рішення. Старий рядок реєстру про неперенесений SBOM
замінений цією звіркою. Це не загальний лічильник усіх
залишків: issues, приймання й фінальна інвентаризація ведуться окремо.
Issue #195 закрита 26.09.2026.
Відсутність відкритих питань у ops не означає завершеного перенесення файлів.

Звірку трьох dependency PR завершено в [LEGACY-DEPENDENCY-AUDIT.md](LEGACY-DEPENDENCY-AUDIT.md):
source-оновлення образів прийняті. Legacy #140 оновлює pins у старих CI workflow;
SBOM адаптацію завершено PR #65–#67, а CodeQL ліцензійний блокер описано в
[дизайні supply-chain CI](SUPPLY-CHAIN-CI-DESIGN-2026-09-28.md).
Повний scope issue #23 ширший за #140.
PR [#56](https://github.com/ikstv/AvelRen-ORIGINAL/pull/56) злитий 28.09.2026
у main `08a16a254e25b67ce590475957380e66062de10d`. Фінальний head `e6e5586`
має 5/5 успішних CI checks. Python pins узгоджено, CVE baseline review
зафіксовано, NNP/cap_drop п'яти Python-служб та Compose-регресії прийнято.
Локальні unit/DB/API/watchdog/snapshot/restore перевірки пройшли.
[Докази та залишкові ризики](PYTHON-BASE-UPDATE-2026-09-28.md).
Legacy #138 закрито саме як пункт source-перенесення, не як production
deployment чи усунення всіх CVE. Старі репозиторії та їх PR не змінювалися.
Caddy 2.11.4 та виправлення IP-заголовка злиті PR #58 у main `64511b8`;
4/4 CI merge-коміту успішні. [Докази](CADDY-UPDATE-2026-09-28.md).
[Ізольована TimescaleDB upgrade-репетиція](TIMESCALE-UPGRADE-2026-09-28.md)
злита PR #59 (main `dc2b83e`, 4/4 CI успішні). Три pins 2.30.1 для
Compose/DB/restore прийняті PR #60 (main `ee31a7b`, 4/4 CI успішні).
#143 завершено як source-пункт; сам старий GitHub PR лишився відкритим.
Production deployment — окремий етап.
Серверні операції мають окремі дозволи за AGENTS.md.

## Звірка restore після репетиції 02.10.2026

Для [issue #41](https://github.com/ikstv/AvelRen-ORIGINAL/issues/41) реальну
копію backup із міграціями 001–014 відновлено локально, потім у disposable
Compose-проєкті на сервері. Native ownership/schema finalization і API smoke
exact main `857eb61e` успішні; ресурси й копії видалено,
робочі контейнери/checkout незмінні.
[Доказ](audits/RESTORE-REAL-BACKUP-2026-10-02.md).
Залишилося окремо узгодити встановлений restore runtime із перевіреним
кодом; старі host-скрипти не змінені, issue #41 не закрита.
Production adoption та production restore зі spool залишаються окремими
неприйнятими етапами; зелений disposable restore не закриває їх.

## Після встановлення restore runtime — 02.10.2026 о 11:29

Залишок #41 із попереднього розділу виконано після окремого deployment GO:
чотири встановлені host-сценарії адаптовано до перевіреного main 857eb61e,
native ownership/schema/API acceptance пройшов на реальному backup
через встановлений шлях; rollback backups збережено, stand прибрано,
live API/collector/backup перевірено.
[Доказ](audits/RESTORE-REAL-BACKUP-2026-10-02.md#встановлений-runtime--приймання-о-1129-за-києвом).
Критерії issue #41 виконано. Production adoption та full restore зі spool
не виконані й не закриваються цим прийманням.
