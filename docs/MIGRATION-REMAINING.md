# Залишки перенесення

## Актуальний стан — 22.10.2026

### Серверна частина

За останнім зафіксованим прийманням collector працював упродовж 22 природних циклів з інтервалом 60 секунд. Резервна пара `20261020-090106` пройшла публікацію, перевірку після запису та ізольоване відновлення з повторним відтворенням даних: 6 циклів, 228 спостережень, `pending_after=0`, вхідні файли не змінені, очищення тимчасових ресурсів підтверджено. Деталі наведено в [аудиті від 20.10.2026](audits/COLLECTOR-RECOVERY-DEPLOYMENT-2026-10-20.md).

Це підтверджує конкретне серверне приймання, але не означає, що всі операційні залишки або міграцію загалом завершено. Інструмент відновлення походить із source `4c0f139`; його hosted CI/інтеграцію потрібно звіряти окремо, не прирівнюючи до приймання production-сервера.

### Наступний крок — Android і телефон

Не повторювати всю телефонну матрицю з нуля. Історичний аудит від 04.10 уже підтверджує локальний голос для п’яти КПП, один успішний фоновий FCM-прогноз Чопа та придушення точного дубля на зазначеному QA APK. Див. [звірку телефонних доказів від 22.10.2026](audits/PHONE-EVIDENCE-RECONCILIATION-2026-10-22.md).

В актуальному APK перевірити лише сценарії, які стосуються змін після того тесту: threshold/ETA, ACK («ОК») і природний повтор через п’ять хвилин, повторне «ОК», foreground reconciliation та ручний DELETE/cancel. Зафіксувати commit, версію APK, SHA-256 і результат кожного сценарію. Історичний успіх не переноситься автоматично на нову збірку; відсутні докази також не є приводом повторювати вже підтверджений сценарій без потреби.

### Окремий етап — Google Play

Після телефонного приймання окремо перевірити готовність оновлення Play, сумісність підпису та збереження даних. Цей етап не вважається завершеним лише на підставі успішного CI або серверного приймання.

Нижче збережено датовані записи попередніх етапів. Вони описують стан на відповідні дати; у разі розбіжностей слід враховувати новіші докази, не переписуючи історію перевірок.

## Пріоритет після аудиту — 19.10.2026

[Свіжий серверний аудит і review](audits/RECOVERY-REVIEW-2026-10-19.md):
API та 60-секундні цикли працюють, paired backup залишається у
`recovery_required`; остання успішна копія — 15.10. У PR #150 виправлено
три дефекти завершення/повтору handoff і durability. Локальні регресії
та повторний review пройшли. Потрібні hosted CI нового head, інтеграція,
чистий main image та цілісний host/helper пакет; далі окремий server GO,
handoff і нове paired backup/restore приймання. Потім — телефонні сценарії
повторного «ОК», звуку та cancel з точним APK hash.

## Recovery handoff — 17.10.2026

Підготовлено [source-механізм і локальні gates](../ops/COLLECTOR-RECOVERY-HANDOFF.md) для наявного recovery_required та legacy spool. Production не змінювали: новий diff потребує review/CI/merge, нового image з чистої main, окремого GO на host/helper/runtime операції та фактичного backup/restore приймання. [Стан етапів](RELEASE-READINESS.md#collector-recovery-handoff-і-legacy-spool--17102026).

## Collector і paired backup — локальний source-крок 16.10.2026

Небезпечний legacy Docker-рецепт вилучено; нові образи мають використовувати
повний canonical backend зі spool/writer supervisor, ETA-перетином і повторами
до DELETE. [Код, перевірки й окремі rollout gates](RELEASE-READINESS.md#canonical-collector-замість-legacy-overlay--16102026).
Історичні fixtures та датовані аудити збережені. Сервер, runtime manifest,
backup state, timers і встановлені images цим кроком не змінені.
Завершення наявного `recovery_required` та production-приймання лишаються
окремими погодженими діями; повторний DB upgrade не входить у цей diff.

## Історичний зріз станом на 15.10.2026

### Push-контракт до ручного скасування

Відновлюємо головний контракт для порогу та часу в’їзду: після «ОК» alert
лишається серверним pending до ручного скасування підписки або цілі; notifier
повторює доставку кожні п’ять хвилин, а collector не закриває його через
спад черги чи проходження цільового часу. Потрібні exact-head CI, окремий
immutable production package з відкатом у межах 15 хвилин і телефонне
приймання початкового push, звуку, «ОК», повтору, foreground reconciliation
та ручного cancel. До цього немає підстав вважати push-функції чи перенесення
завершеними; Play 1.0.4 не публікуємо.

Повторна звірка коду, GitHub і живого публічного API зафіксована в
[датованому записі](audits/MIGRATION-RECHECK-2026-10-14.md). Вона підтвердила
базові функції, свіжі дані КПП, зовнішній monitor і стан API; не замінює
приймання push/звуку/«ОК» на телефоні.

Після DSN приймання залишається оновлення та приймання образів collector/watchdog:
поточні збережені образи ще містять urllib3 2.7.0 та старі DB writer/models/replay
до контракту missing-wait, виправлення якого вже є в Original. Потрібен окремо
перевірений актуальний артефакт; DSN операція не розгортала ці source виправлення
і не доводить, що всі production образи зібрані з поточної main.

Collector/watchdog DSN прийняті 14.10: [production доказ](audits/POSTGRES-DSN-CUTOVER-2026-10-14.md). Залишки та межі:

1. DSN collector/watchdog переключені на власні ролі й перевірені; retirement
   legacy ролі та власників Timescale jobs цим не виконано.
2. Зовнішній monitor перенесено: старий workflow вимкнено, а ORIGINAL
   успішно виконався за розкладом 14.10 о 20:37 UTC. Відкритих monitor issues
   немає; докладний доказ — у повторній звірці вище.
3. [Підписаний APK-кандидат 0.1.3/code6](RELEASE-READINESS.md) з main `a8fc73c`
   зібраний. Пізніша ADB-звірка виявила один авторизований телефон:
   `ua.avelren.app`, 0.1.3/code6, installer `com.android.vending`.
   POST_NOTIFICATIONS granted=true, DND zen_mode=0. Підпис встановленого APK перевірений 19:23:32 за Києвом;
   Play certificate відрізняється від локального upload certificate; update і FCM/голос/ACK
   не прийняті. Власник відклав публікацію 1.0.4 до завершення перенесення;
   read-only перевірка Play не є публікацією.
4. Мінімальне виправлення пропущеного перетину ETA у PR #142 проходить
   повний ізольований CI; production collector не змінюємо до зеленого
   результату й точного повторного readback.
5. Повтори threshold/ETA push до ручного скасування підписки — погоджена
   нова поведінка, а не legacy parity: окремо реалізувати, перевірити на
   телефоні та розгорнути.
6. Фінальна звірка решти backlog і збереження історії старих репозиторіїв
   до їх видалення; архів п'яти Play PNG уже збережений з provenance у merged PR #133 (0d9b7b6).

- Реальна off-host пара `20261014-102249` пройшла штатне ізольоване відновлення за 84,863 с на source PR #131 `a793151`: усі 1440 ACK перевірені, єдиний pending відтворено, після replay `pending=0`; локальні резервні файли та власні Docker-ресурси прибрані. [Доказ і межі приймання](audits/PAIRED-LEGACY-RESTORE-2026-10-14.md). Незалежний review APPROVED; hosted CI 38558951014 пройшов усі обов'язкові jobs, PR #131 злитий у main `3e6df1ba059a680805c9b427f66198e944abe878` із точно протестованим деревом. Окремий main-push CI цим записом не приймається. Повторне встановлення r5 незміненого backup PR #130 прийняте: 13 файлів/SQL/helper перевірені, штатний timer enabled/active (наступний запуск за readback — 15.10 о 06:22:18 за Києвом), нової паузи або capture не було. Сім контейнерів незмінні, capture-only вимкнений, pending=0; Перевірка стабільності 14.10 о 15:12:09 за Києвом підтвердила API health ok, вік спостереження 15 с. Це не доказ production DR/background jobs або переходу прав/DSN.

- FCM ownership source злитий у [PR #123](https://github.com/ikstv/AvelRen-ORIGINAL/pull/123), main `4ee4b1bd911fec5b78ae908ae593a8d81ac3cfa8`.
- Aggregate CI-gate злитий у [PR #124](https://github.com/ikstv/AvelRen-ORIGINAL/pull/124), main `574b25cbf622c008a9e7d11a4d280af91963f71b`. [Main run 38287247895](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38287247895) завершив усі 11 jobs успішно, включно з Android, обома SBOM і `CI gate`. [Main run 38526654840](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38526654840) для `7c88b5162f875dc6a0a4ce7f460e1d6f121ac3ca` також SUCCESS.
- API/notifier розгорнуті 12.10 з main `574b25c`; результати та межі наведено в [аудиті розгортання](audits/API-NOTIFIER-DEPLOYMENT-2026-10-12.md). Це датований доказ, а не гарантія поточного health без нової перевірки.
- Діагностика публікації резервної пари з [PR #128](https://github.com/ikstv/AvelRen-ORIGINAL/pull/128) злита в main `ab74e078e6a3b602ade0fd33c6ba612d37ca7341`. [CI 38529944746](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38529944746) пройшов усі обов'язкові перевірки, включно з native paired restore. Це source/CI приймання. Пакет r3 зупинено **до встановлення**: повторна перевірка Google Drive повернула `403 rateLimitExceeded`. Нової паузи записувача й нового backup не було; попередній timer після відкату перевірений справним. Неповну приватну передачу пакета відхилено перевіркою хешу; source на сервер не встановлено.
- Попередній статус до успішної фактичної репетиції вище: спільна резервна копія PostgreSQL і SQLite та її ізольоване відновлення ще не були прийняті. Оперативний стан і результати спроб — у [датованому аудиті](audits/PAIRED-BACKUP-PRODUCTION-2026-10-14.md).
- Collector/watchdog DSN переключені після окремого GO: [production аудит](audits/POSTGRES-DSN-CUTOVER-2026-10-14.md). Обидва вікна в межах 15 хвилин; сім контейнерів running без restart, природні collector цикли та API пройшли перевірку. Legacy Timescale jobs і retirement ролі залишаються окремими. Scheduled monitor, телефонні сценарії та фінальна звірка старих репозиторіїв ще не завершені.
- Власник погодив коротке вікно технічних робіт до 15 хвилин із відкатом. Старий розширений maintenance-план не є обов'язковою наступною реалізацією: частковий код збережено без приймання. Погоджений DSN перехід прийнято окремим аудитом вище; це не дозвіл на інші операції БД.
- Read-only GitHub перевірка 14.10: репозиторій PUBLIC; classic protection main повертає `404 Branch not protected`, effective branch rules — `[]`. Блокування merge не ввімкнене. Старий тарифний 403 описує приватний стан на дату аудиту й не є поточним доказом недоступності. Налаштування доступу, бюджету та захисту цією документацією не змінюються.

Нижчі записи зберігають перебіг робіт на свої дати. Цей підсумок уточнює старі твердження про незлитий FCM, лише локальний CI-gate й відсутнє application deployment; він не підтверджує приймання телефона чи повного production DR.

## Звірка старих репозиторіїв — 14.10.2026

Уточнення після поелементного аудиту: п'ять Play PNG збережено без зміни
байтів у [локальному архіві з provenance](assets/legacy-play/README.md).
Залишок копіювання цих файлів закрито на рівні source-кандидата;
merge/hosted CI ще не підтверджені цим записом. Права, актуальність UI і
тверджень та Play-публікація залишаються окремим прийманням.
Датовану матрицю нижче збережено як стан до перенесення PNG.

[Поелементна матриця issues, PR, функцій і ресурсів](audits/LEGACY-REPOSITORIES-GAPS-2026-10-14.md) відділяє вже замінені зміни від відкритих production gates, R08, delete-installation, supply-chain і Play assets. Ці залишки мають різний обсяг; це не перелік непрацюючих серверних служб.

Read-only GitHub inventory: у [AvelRen](https://github.com/ikstv/AvelRen)
відкриті 8 issues і 11 PR; у [AvelRen-ops](https://github.com/ikstv/AvelRen-ops) —
0 issues і 1 PR. Основні гілки досі відповідають зафіксованим джерелам
`4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` та
`5be9da8b433813a664b4d4e21a0a92bae91c56a0` відповідно.
Ці кількості не означають стільки ж відсутніх функцій: потрібна поелементна
класифікація перенесеного, застарілого та окремого майбутнього backlog.
FCM ownership не закриває автоматично всі сценарії старого
[issue #19](https://github.com/ikstv/AvelRen/issues/19).
Старі репозиторії ще не готові до видалення.

## Спільна копія БД і черги — актуальний стан 14.10.2026

Останній preflight r3 знову отримав Google Drive `403 rateLimitExceeded`.
Метадані конфігурації показали вбудований спільний rclone OAuth client без
власного client ID; це можливий чинник, а не доведена точна причина ліміту.
Успішний попередній read-only запит не доводить можливість повної передачі.
Повторне встановлення, нова пауза й нова резервна копія не починалися.

PR #126 і виправлення preflight PR #127 злиті з успішними обов'язковими CI
перевірками. Друга серверна спроба створила обидва snapshots, але публікація
пари не завершилася; пауза не перевищила 40,589 с. Відкат перевірений, старе резервне
копіювання знову працює за розкладом; робочі контейнери не змінені.
[Датований звіт](audits/PAIRED-BACKUP-PRODUCTION-2026-10-14.md).
Потрібні безпечна діагностика передачі, повна публікація
спільної копії та її точне ізольоване відновлення. Сам PR green не закриває
production приймання. Видалення старих репозиторіїв ще не готове.

## API та notifier — актуальне production приймання 12.10.2026

API/notifier уже оновлено після конкретного owner GO з канонічної main
`574b25cbf622c008a9e7d11a4d280af91963f71b`;
[PR #124](https://github.com/ikstv/AvelRen-ORIGINAL/pull/124) злитий,
11 main CI jobs SUCCESS. [Новий аудит](audits/API-NOTIFIER-DEPLOYMENT-2026-10-12.md)
уточнює нижчі датовані записи про ще не виконане application deployment.
Фактична service window — 74.301 s; звичайна плашка — 135.263 s,
19:53:12–19:55:27 UTC. Новий image API/notifier підтверджено на сервері;
сім контейнерів running, DB healthy, health `ok`, maintenance `null`,
інші п'ять контейнерів та images незмінні. Відкат у production не виконувався.

Власник змінив підхід і прийняв короткий простій. Подальшу реалізацію
розширеного maintenance плану для цього deployment замінено цим прийманням;
часткові напрацювання збережені без підвищення їхнього статусу до verified.
DB production CLI лишається закритим; adoption прав/DSN, повний restore зі
spool, зовнішній моніторинг і решта backend operational acceptance відкриті.
Android APK/телефон/FCM delivery/Play потребують власних gates.
Перенесення загалом не оголошується завершеним. Репозиторій тимчасово PUBLIC
за рішенням власника; цей deployment не змінював visibility чи доступів.

## Єдиний CI-gate — актуальний source стан 12.10.2026

[Дизайн](superpowers/specs/2026-10-12-ci-aggregate-gate-design.md) і
[план](superpowers/plans/2026-10-12-ci-aggregate-gate.md) уточнюють нижчі
датовані записи про ще не реалізований CI-gate. [PR #123](https://github.com/ikstv/AvelRen-ORIGINAL/pull/123)
злитий у main `4ee4b1bd911fec5b78ae908ae593a8d81ac3cfa8`; сім звичайних
main workflows мають SUCCESS за старою схемою CI. Ці результати не є
прийманням нового aggregate gate.

| Етап | Поточний доказ / що лишилося |
| --- | --- |
| Source Tasks 1–4 | Manifest, повний Git diff, строгий evaluator і атомарна міграція реалізовані; незалежні reviews PASS. Migration commit `54528d50def02eed4c1bd5ad2598cca42900b5d6`; інтеграція актуальної main — `4df904759a5405864c0d1d420c78f2e24bcdc224`. |
| Локальні перевірки | Збережено 26 незалежних legacy cases; scripts suite 675 passed до останнього вузького import fix, після нього 35 focused passed і standalone verifier PASS. Actionlint, Ruff та provenance перевірки успішні в межах Tasks 1–4; final whole 676 run не заявляється. |
| Документація й review | Три актуальні документи оновлено в Task 5; незалежний review Task 5 та whole-branch review ще очікуються. |
| Новий hosted PR CI | Публікація одного CI PR та один all-components run ще попереду; потрібні gate success, усі вісім calls і artifacts одного run/attempt із base/head/tested SHA. |
| Новий hosted main CI | Після окремо дозволеного merge потрібен власний main-push run на фактичному merge SHA; PR green або старі сім main workflows його не замінюють. |
| Enforcement main | Не увімкнено; тарифний блокер branch protection/rulesets лишається. Окреме owner рішення щодо тарифу/моделі, reviewer та bypass, effective API readback і failing-PR test merge identity `ikstv`. |
| Production / телефон / Play | Цією CI зміною не виконані й не прийняті. Maintenance/DSN cutover, live monitor, APK із version/SHA-256, телефонні сценарії та Play лишаються окремими роботами. |

Dispatcher обробляє PR `opened/synchronize/reopened/ready_for_review/edited`
без обмеження target/path/draft, push лише main. Repository потрібний на
кожній події; docs-only PR до main також запускає обидва SBOM jobs.
Edited title/body повторно запускає потрібні jobs і витрачає бюджет;
shortcut для приховування failure немає. Control/unknown/history/diff
fallback запускає всі вісім компонентів навіть для non-main PR.
Gate вимагає scope та всі вісім calls у `needs`, має `always()`/2 хв;
required проходить лише з success, non-required — success/skipped.
Ручний live-monitor залишається поза CI та потребує свого приймання.

Для hosted приймання потрібні `ci-plan-<tested_sha>-<run_id>-<run_attempt>`,
`source-sbom-<tested_sha>` та `runtime-image-sbom-<tested_sha>`,
`expired=false`, узгоджені plan/summary SHA і результати саме цього run.
Failure/cancelled/required skip/missing, YAML error, conflict, fork approval,
skip-ci, outage чи budget block не вважаються pass. PR YAML лишається
недовіреним; privileged `pull_request_target`/`workflow_run` не додаються.
Помилки до merge виправляються в PR; після merge — revert без force-push
із явним записом про втрату aggregate gate, якщо він відкочений.

Бюджет $3 не збільшується; звіряти доступні billed usage/storage, не timeout
чи wall time. Billing, visibility, access, invitations, GitHub App та
production не змінюються. Self-approval `ikstv` не є незалежним review;
source gate та CI success самі по собі не забороняють merge у main.

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
| Collector/watchdog DSN та legacy [AvelRen#15](https://github.com/ikstv/AvelRen/issues/15) | DSN обох служб прийняті 14.10: [production доказ](audits/POSTGRES-DSN-CUTOVER-2026-10-14.md); образи збережені, runtime перевірений. Retirement legacy ролі та Timescale jobs не виконано; не повторювати ownership/ACL без нової потреби. |
| Forecast legacy #111 / ORIGINAL [#70](https://github.com/ikstv/AvelRen-ORIGINAL/issues/70) | PR #72 злитий 02.10.2026, merge d134c0b; server missing/0/legacy_unknown і Android wait_estimate/DTO/UI уже у main. Повторний перенос не потрібний. Короткий історичний backtest не є release gate: залишилися довший holdout, recovery та окреме приймання на телефоні. Див. [звірку аудиту12.10](audits/AUDIT-TRIAGE-2026-10-12.md); не оголошувати missing справжнім нулем без урахування status. |
| Сповіщення про реліз, R08 | [Старий payload helper і три тести перенесено без змін](RELEASE-NOTICE-TRANSFER.md). Sender та Play availability gate не були готовою частиною джерела; їх реалізація й наскрізне приймання залишаються окремою вимогою. |
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

## Уточнення 13.10: paired source-кандидат

[Paired backup source аудит](audits/PAIRED-BACKUP-SOURCE-2026-10-13.md):
native helper/coordinator/recovery/crypt/restore та disposable daemon rehearsal
підготовлено окремою гілкою. Local source checks, exact-head hosted CI/review,
merge, конкретний пакет/production GO і real off-host pair restore приймаються
окремо. Default `sql-only`; intended paired встановлення не виконано. Real
paired RPO/RTO, DB-role transition, зовнішній monitor, APK/phone/Play не закриті.
