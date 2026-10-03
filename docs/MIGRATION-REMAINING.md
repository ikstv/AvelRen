# Залишки перенесення

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
| Production adoption прав БД, legacy [AvelRen#15](https://github.com/ikstv/AvelRen/issues/15) | [Функціональна звірка 01.10](POSTGRES-ADOPTION-GAP-2026-10-01.md): старі `deploy/postgres-adopt.sh`, `postgres-ownership.lib.sh`, `postgres-privilege-gate.sh` і тести не мають production-еквівалента. `ops/postgres-bootstrap.sh` — лише fresh/disposable bootstrap. Старі allowlist/ACL та runbook до 009 несумісні як готова процедура зі схемою 001–014; потрібні design review, ізольовані forward/inverse і privilege-тести. Production — лише після окремого явного GO та свіжої read-only звірки. |
| Forecast legacy #111 / ORIGINAL [#70](https://github.com/ikstv/AvelRen-ORIGINAL/issues/70) | Семантику missing/0/legacy_unknown описано в погодженій специфікації та чернетці плану [PR #71](https://github.com/ikstv/AvelRen-ORIGINAL/pull/71); ці файли ще не в main. Draft [PR #72](https://github.com/ikstv/AvelRen-ORIGINAL/pull/72) — кандидат серверних задач 1–3, 8/8 CI checks на `e68e731` та короткий незалежний backtest із `count_hours` без фільтра за wait. MAE кількості нижча за базиси на чотирьох КПП, але час піку гірший на КПП 1, 29 і 6; це не release gate. Залишаються Android DTO/UI, rollback/restore gate, довший holdout і приймання після окремого deployment GO. Старе held-out evaluation вже перенесено; повторювати його перенос не потрібно. |
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
