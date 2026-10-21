# Що має дійти до телефона

## Бокове меню у FullTest — експеримент 21.10.2026

Власник замовив меню й анімацію за зразком встановленого Dron Alerts із
головним екраном AvelRen та попросив оновити наявну тестову APK поверх.
Панель виїжджає зліва за 300 мс, затемнює головний екран, групує чинні
переходи в округлі блоки та закривається через X, Back, scrim або свайп.
Кольори й шрифт узято з теми AvelRen: жовтий акцент у темній темі,
червоний у світлій, без синіх елементів. Унизу панелі —
«Developer: Tanko Viktor» і поточна версія програми; на малих екранах
підпис доступний прокручуванням.
У другій ітерації власник дозволив творчо допрацювати меню зі збереженням
палітри: додано контекст обраного КПП, фактичний стан сервера, заголовки
груп та швидкий вибір КПП / ручне оновлення через чинні потоки застосунку.
Деталі й збірка: [Android README](../apps/android/README.md).

Третя ітерація за дозволом власника заповнює нижню панель трьома діями
«Меню / Головна / Моніторинг», додає перемикання теми без закриття drawer,
лічильник активних порогів та ETA (лише після успішного читання) й окремий
рядок категорії транспорту в назві КПП. Нові налаштування FullTest:
збережений перемикач «Не гасити екран» лише для відкритого застосунку,
реальні системні переходи до сповіщень і батареї, «Поділитися додатком»
через Android Sharesheet та «Оцінити додаток» з поясненням обмежень FullTest.
Поширюється публічна сторінка звичайного релізу GitHub, не тестовий APK.
Оцінювання відкриває офіційний пакет `ua.avelren.app`, а не `.test`;
публічну доступність Play не підтверджено (анонімний HTTP 404 21.10.2026),
доступ тестувальника та можливість відгуку перевіряються в його акаунті.
Тема й keep-screen налаштування зберігаються локально; серверні повтори,
FCM і підписки не змінюються. Результати нової збірки та сценарії телефона
потрібно читати в окремому актуальному receipt, не переносити зі старої APK.

| Етап | Стан на час підготовки source |
| --- | --- |
| Код | Окрема гілка `codex/fulltest-drawer-20261021` на main `d5296d0`; `ENABLE_TEST_DRAWER` увімкнений тільки у FullTest debug |
| Головна, API, FCM, підписки | Чинна логіка збережена; новий код стосується навігації |
| Перевірки / APK / телефон | Окремі результати записуються в `dist/BUILD.txt`; source сам по собі не означає їх успіху |
| Hosted CI / merge | Цим експериментом не виконуються |
| Сервер / Play | Цим експериментом не змінюються |

Звичайна й release-збірки зберігають попередню навігацію. У прототипі
використано власну іконку AvelRen і наявні Material vectors; графіку
Dron Alerts не переносили. Скриншоти з телефона залишаються локальними
матеріалами порівняння.

## Collector, нова резервна пара й off-host restore — прийнято 20.10.2026

[Фактичне production-приймання](audits/COLLECTOR-RECOVERY-DEPLOYMENT-2026-10-20.md)
уточнює попередні source-етапи нижче: main `6ba462b5`, CI 11/11 SUCCESS,
canonical image `sha256:c5ed1370…` встановлений; handoff завершено.
Після нього прийнято п'ять, а фінально 22 природні цикли з інтервалами
60 с, pending=0, capture_only=false/mode_ack=false; SQL/API/ETA та
незмінність решти контейнерів перевірені.

Нова production-пара `20261020-090106` опублікована, отримана off-host
і відновлена: 6 verified cycles / 228 observations, 5 ACK / 190 observations,
pending sequence 19651 відтворено; pending_after=0, hashes незмінні,
cleanup PASS. Timer повернуто 09:19:20 UTC, enabled/active; наступний запуск
за readback — **21.10.2026 03:25:27 UTC**. Це не доказ його майбутнього виконання.

Off-host harness прийнято на `4c0f139`; це окремий source від production
image. Його hosted CI/merge ще не виконані. Наступний користувацький крок —
current-main FullTest APK і телефонна матриця threshold/ETA: звук, повторний
«ОК», природний повтор через п'ять хвилин, foreground та DELETE/cancel;
після цього — окреме приймання оновлення через Play. Android/телефон/Play
цим серверним етапом не прийняті.

## Off-host restore після заміни legacy collector — 20.10.2026

Сучасний manifest не усуває старого SQL owner Timescale jobs. Додано
явну [опцію ізольованої репетиції](../ops/COLLECTOR-RECOVERY-HANDOFF.md#off-host-restore-та-старий-власник-timescale-jobs)
`--legacy-timescale-owner avelren`: лише restricted NOLOGIN placeholder,
без послаблення `modern_strict` replay або зміни production-ролі.

Локально: 22 restore contracts PASS; native synthetic dump із чотирма
jobs owner=avelren відтворив default failure, а explicit opt-in пройшов
restore/schema/API/replay. Перевірено 3 cycles / 2 observations, recovered
started=1, pending=0; hashes п'яти вхідних файлів незмінні. Небезпечна
наявна роль відхилена. Source бази — `6ba462b5ed9341270d552626b8af1039813ec721`,
перевірений backend image — `sha256:c5ed1370f6880cfd0d57f3f4866f8d0bfac5f8f8d04a3abb8dda3f4775fae3ab`.
Повна native paired integration також PASS: synthetic modern-пара зі
старими owners відхилена без опції та відновлена з нею; verified 5 cycles /
3 observations, pending=0, незмінні manifest/hashes, cleanup PASS. Природні
інтервали collector — 60.001 / 60.000 s; API, SIGKILL recovery та restart/drain PASS.
Це локальне source-приймання: review/CI/merge виправлення й окрема
реальна off-host pair залишаються відкритими; Android/телефон/Play не зачіпали.

## Recovery review і стан сервера — 19.10.2026

[Свіжий read-only аудит і review PR #150](audits/RECOVERY-REVIEW-2026-10-19.md)
підтвердили роботу API/collector та блокування paired backup у
`recovery_required`. Остання підтверджена копія — 15.10; timer сам recovery
не завершує. Production цим кроком не змінювався.

Виправлено три відтворені дефекти handoff: перевірка identity/running після
drain, fsync фактичних каталогів і safety captures, повтор helper після
невдалого finish/rollback. Повторний незалежний review без зауважень;
31 handoff + 26 state + 4 wiring contracts та 707 backend unit tests PASS.
Початковий head `eb1d5ada` має успішні 11 CI jobs; нові fixes потребують
власного hosted CI. Review image перевірений, але фінальний пакет має бути
зібраний із чистої main після інтеграції. Deployment, нові backup/restore,
Android, телефон і Play цим записом не приймаються.

## Collector recovery handoff і legacy spool — 17.10.2026

Підготовлено [контрольований handoff](../ops/COLLECTOR-RECOVERY-HANDOFF.md):
одна backup/control lease, durable interlock, exact identity/pins, safety captures,
60 секунд між writers, native off ACK/drain і відкат лише без backlog.
Offline migration додає per-cycle provenance після read-only SQL звірки;
strict restore повторно перевіряє SQL, production legacy allowlist не розширено.

| Етап | Стан |
| --- | --- |
| Код | Source-кандидат на базі main b009a275e058af9334ef02cd23039f06cebdd3a8; [дизайн](superpowers/specs/2026-10-17-collector-recovery-handoff-design.md) |
| Локальні перевірки | PASS: 707 unit; 280 PostgreSQL/TimescaleDB (включно з 1439 aged ACK); 22 Linux handoff, 26 lease/state, 9 daemon boundary, 7 real Docker cleanup, 4 handoff wiring, 38 CI workflow contracts; 17 legacy/ETA; Ruff/provenance PASS |
| Native paired / restore | PASS: synthetic pair `20261017-080544`; 5 verified cycles / 3 observations, pending_after=0; SQL totals 6 runs / 4 observations; crypt readback і cleanup іменованих ресурсів PASS |
| Hosted CI / merge нового diff | Не виконувалися |
| Сервер / timer / state | Не змінювалися; нове production-приймання не виконувалося |
| Android / телефон / Play | Цим кроком не змінювалися й не перевірялися |

Чиста main image b009a27 попереднього кроку не містить нового migration модуля.
Після merge потрібен новий canonical image і узгоджений host/helper пакет.
Native fixture — working tree на базі b009a27, а не main release image; 58 installed Python modules збігаються з source. Старий образ має точні captured collector/db/models/ETA bytes, але synthetic image ID. Handoff після SIGKILL дочекався 64,801 с; producer starts — щонайменше 60 с. [Приймання й межі](audits/COLLECTOR-RECOVERY-HANDOFF-2026-10-17.md).

Crash між recreate і journal-ID, boot/PID drift та backlog rollback навмисно
блокуються; автоматичне adopt або редагування state не дозволені.

## Canonical collector замість legacy overlay — 16.10.2026

Вилучено Docker-рецепт `ops/eta-legacy-hotfix`, який підміняв сучасний
spool-capable collector старим прямим writer. Збірка має використовувати
повний `services/backend`; історичні ETA/collector fixtures залишені лише
для тестів. [Причина й маршрут збірки](../ops/eta-legacy-hotfix/README.md).
Canonical ETA, replay, повтори до DELETE, міграції та права не змінюються.

| Етап | Стан |
| --- | --- |
| Код | Legacy-рецепт і його build-контекст вилучені; регресійний guard пройшов RED/GREEN |
| Локальні перевірки | 17 legacy-контрактів, 705 unit, 49 PostgreSQL ETA/repeat/ACK/pipeline; paired contracts: 85 виконано, 12 Docker-only пропущено |
| Native paired backup/restore | PASS: synthetic пара `20261016-195228`, ACK on/off, SIGKILL recovery, local crypt/readback, restore/replay, pending=0, cleanup PASS; не є production backup |
| Hosted CI / merge | Для нового diff ще не виконані |
| Сервер | Не змінений; існуючий `recovery_required` не скидався |
| Android / телефон / Play | Цим локальним виправленням не перевірялися й не змінювалися |

Штатний `ops/paired-backup-daemon-test.py` перевірив справжні PostgreSQL/SQLite
snapshots, локальне зашифроване сховище та disposable restore: 2 cycles і 2
observations, pending після replay 0. Пауза writer 45,014 с; запуски source
розділені щонайменше 60 с. HTTP підмінено; native backup/recovery не підмінялися.
Fixture source — робоче дерево на базі `0f4e1f6c50cbd49926d36bdd3bf35a3136c21258`,
backend байти незмінні. Це не новий main release image і не приймання
production state. Повторна source-перевірка та документаційний review — без зауважень.

Перед deployment потрібні чиста main, immutable collector image, перевірені
runtime manifest/restore-сумісність, план відкату й окреме погодження завершення
наявного backup recovery. Вилучення рецепта не змінює встановлених байтів.

## OK після кожного resend — 15.10.2026

[Регресія ACK](ALERT-ACK-RESEND-2026-10-15.md) виправляє timestamp
підтвердження після другої та наступних доставок threshold/ETA, а також
transaction-start timestamp у notifier при ACK під час send. Новий тест
відтворив дефект для обох видів; API, database, immutable image, hosted CI
та phone acceptance мають окремі результати. Робочий сервер не змінено;
Google Play не оновлюємо. Наявність цього запису не закриває rollout gate.

## Скасування сповіщень після відписки — 15.10.2026

На встановленому 0.1.3 отримано фонові threshold alert77 і ETA alert32
для тестового КПП Рені. Після DELETE ETA-цілі сповіщення залишилося
у шторці під час негайної перевірки; затримку cancel-push цим не виключено.
Новий Android source запускає наявну fail-safe звірку `/active-alerts`
одразу після успішного DELETE обох видів моніторингу.
Failed DELETE не скасовує сповіщення. Телефонне приймання виправлення,
повтори через п'ять хвилин та ACK ще не завершені; старий телефонний тест
не є перевіркою нового APK. APK має бути з чистої main з перевіреним SHA-256.

## Повтори до ручного скасування — gates релізу 1.0.4

Read-only звірка production 15.10 підтвердила поточний health і runtime без
нової поломки: [датований результат](audits/PRODUCTION-READ-ONLY-2026-10-15.md).
Вона не є прийманням цього виправлення, телефона чи релізу.

Цей розділ описує приймання погодженого правила: «ОК» прибирає лише
поточне повідомлення, а поріг і ціль ETA продовжують надсилати той самий
alert до ручного скасування в меню. Жоден пункт нижче ще не означає
production-, телефонне або Play-приймання.

| Перевірка | Поріг | ETA |
| --- | --- | --- |
| Exact-head source CI | [ ] | [ ] |
| Перший push з коректним ID | [ ] | [ ] |
| Звук на адмінському телефоні | [ ] | [ ] |
| «ОК» прибирає лише поточну картку | [ ] | [ ] |
| Повтор через п’ять хвилин | [ ] | [ ] |
| Foreground reconciliation не повертає картку до успішного повтору | [ ] | [ ] |
| Скасування в меню припиняє push і надсилає cancel | [ ] | [ ] |
| Точний deployed image, preflight і rollback | [ ] | [ ] |

Play Console, AAB/APK та GitHub Release 1.0.4 не публікуються цим
виправленням. Вони можливі лише після всіх source, production і телефонних
пунктів вище.

## ETA: прямий перетин цілі — 14.10.2026

[Виправлення пропущеного ETA alert](ETA-FORWARD-CROSSING.md) додає
спрацювання, коли два послідовні придатні спостереження після створення
підписки переходять із часу перед ціллю на час після неї, перестрибнувши
вікно допуску. Чинний alert усередині вікна, pending dedup, порогові
сповіщення, повтори, cancel/ACK та звук не змінені.
Source і локальні тести підготовлені; hosted CI, розгортання та
доставка на телефон ще не прийняті. Поточний старий collector цим
записом не вважається оновленим.

## Підписаний production APK-кандидат — 14.10.2026

З чистої main `a8fc73cec2826d1ad1c62077306f1c5c2eb7baa3` зібрано
`ua.avelren.app`, versionName **0.1.3**, versionCode **6**.
APK SHA-256: `fa933d435f2c36641c91cd4369c3187d3dd707c080c443e7a1163db077078803`.
Certificate SHA-256: `b3c2c5c3479e31615876a631b88b08ce91b3c90835639f4884c41874d90018ce`.
`assembleRelease` і перевірка apksigner пройшли; це кандидат, не фінальний реліз.

Під час збірки ADB не виявив пристроїв. Пізніша read-only перевірка
підтвердила один авторизований телефон: `ua.avelren.app`, 0.1.3/code6,
installer `com.android.vending`, POST_NOTIFICATIONS granted=true, DND zen_mode=0.
Read-only apksigner перевірка 14.10 о 19:23:32 за Києвом підтвердила підпис установленого APK; оновлення не виконано. Перед встановленням потрібна
звірка фактичних package/cert/version; тут upload certificate відрізняється
від Play App Signing certificate. Не видаляти встановлений застосунок
і не обходити signature mismatch. Версію 0.1.3/code6 не слід автоматично
вважати наступною публічною версією. AAB, Play і GitHub Release не створені;
FCM/голос/ACK та інші телефонні сценарії залишаються неприйнятими.
Власник відклав публікацію 1.0.4 до завершення перенесення.


Встановлений Play APK SHA-256: `df060e7813f6bda3829aa301e75a06ee50c3777b04cba378c107371400bb005d`.
Його certificate SHA-256: `2739e755fd1f302adcfa318ef9fc27b243e6d1b6c8e978248844fd46f32e1ff4`;
він не збігається з upload certificate локального кандидата вище. Оновлення
зі збереженням даних має пройти через належний Play signing шлях; локальний
кандидат не доводить сумісності прямого встановлення. Тимчасову копію APK
видалено; застосунок і його дані не змінювали. Це не приймання доставки FCM/голосу/ACK.

[Ручний зовнішній monitor](EXTERNAL-MONITOR-TRANSFER-2026-10-11.md)
пройшов один healthy live запуск; notification failure/recovery і заміна
старого розкладу цим не прийняті.

## Актуальний підсумок — 14.10.2026
Після DSN приймання залишається оновлення та приймання образів collector/watchdog:
поточні збережені образи ще містять urllib3 2.7.0 та старі DB writer/models/replay
до контракту missing-wait, виправлення якого вже є в Original. Потрібен окремо
перевірений актуальний артефакт; DSN операція не розгортала ці source виправлення
і не доводить, що всі production образи зібрані з поточної main.

- Старі п'ять Play PNG перенесено без зміни байтів у [архів для перевірки](assets/legacy-play/README.md): source-кандидат, Git blob SHA/SHA-256 та візуальний огляд перевірені. Hosted CI/merge цим записом не прийняті; APK/AAB і телефонне приймання не виконувалися. Права та актуальність рекламних тверджень потребують перевірки; матеріали в Play не завантажувалися.

- Реальна off-host пара `20261014-102249` пройшла штатне ізольоване відновлення за 84,863 с на source PR #131 `a793151`: усі 1440 ACK перевірені, єдиний pending відтворено, після replay `pending=0`; локальні резервні файли та власні Docker-ресурси прибрані. [Доказ і межі приймання](audits/PAIRED-LEGACY-RESTORE-2026-10-14.md). Незалежний review APPROVED; hosted CI 38558951014 пройшов усі обов'язкові jobs, PR #131 злитий у main `3e6df1ba059a680805c9b427f66198e944abe878` із точно протестованим деревом. Окремий main-push CI цим записом не приймається. Повторне встановлення r5 незміненого backup PR #130 прийняте: 13 файлів/SQL/helper перевірені, штатний timer enabled/active (наступний запуск за readback — 15.10 о 06:22:18 за Києвом), нової паузи або capture не було. Сім контейнерів незмінні, capture-only вимкнений, pending=0; Перевірка стабільності 14.10 о 15:12:09 за Києвом підтвердила API health ok, вік спостереження 15 с. Це не доказ production DR/background jobs або переходу прав/DSN.

- FCM ownership source злитий у [PR #123](https://github.com/ikstv/AvelRen-ORIGINAL/pull/123), main `4ee4b1bd911fec5b78ae908ae593a8d81ac3cfa8`.
- Aggregate CI-gate злитий у [PR #124](https://github.com/ikstv/AvelRen-ORIGINAL/pull/124), main `574b25cbf622c008a9e7d11a4d280af91963f71b`. [Main run 38287247895](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38287247895) завершив усі 11 jobs успішно, включно з Android, обома SBOM і `CI gate`. [Main run 38526654840](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38526654840) для `7c88b5162f875dc6a0a4ce7f460e1d6f121ac3ca` також SUCCESS.
- API/notifier розгорнуті 12.10 з main `574b25c`; результати та межі наведено в [аудиті розгортання](audits/API-NOTIFIER-DEPLOYMENT-2026-10-12.md). Це датований доказ, а не гарантія поточного health без нової перевірки.
- Діагностика публікації резервної пари з [PR #128](https://github.com/ikstv/AvelRen-ORIGINAL/pull/128) злита в main `ab74e078e6a3b602ade0fd33c6ba612d37ca7341`. [CI 38529944746](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38529944746) пройшов усі обов'язкові перевірки, включно з native paired restore. Це source/CI приймання. Пакет r3 зупинено **до встановлення**: повторна перевірка Google Drive повернула `403 rateLimitExceeded`. Нової паузи записувача й нового backup не було; попередній timer після відкату перевірений справним. Неповну приватну передачу пакета відхилено перевіркою хешу; source на сервер не встановлено.
- Попередній статус до успішної фактичної репетиції вище: спільна резервна копія PostgreSQL і SQLite та її ізольоване відновлення ще не були прийняті. Оперативний стан і результати спроб — у [датованому аудиті](audits/PAIRED-BACKUP-PRODUCTION-2026-10-14.md).
- Collector/watchdog DSN прийняті після окремого GO: [production доказ 14.10](audits/POSTGRES-DSN-CUTOVER-2026-10-14.md). Legacy роль і Timescale jobs не retired. Відкриті scheduled monitor, push/голос/ACK на телефоні та фінальна звірка старих репозиторіїв; реліз 1.0.4 відкладено до завершення перенесення. Старі репозиторії зберігаємо до приймання заміни.
- Власник погодив коротке вікно технічних робіт до 15 хвилин із відкатом. Старий розширений maintenance-план не є обов'язковою наступною реалізацією: частковий код збережено без приймання. Погоджений DSN перехід прийнято окремим аудитом вище; це не дозвіл на інші операції БД.
- Read-only GitHub перевірка 14.10: репозиторій PUBLIC; classic protection main повертає `404 Branch not protected`, effective branch rules — `[]`. Блокування merge не ввімкнене. Старий тарифний 403 описує приватний стан на дату аудиту й не є поточним доказом недоступності. Налаштування доступу, бюджету та захисту цією документацією не змінюються.

Нижчі записи зберігають перебіг робіт на свої дати. Цей підсумок уточнює старі твердження про незлитий FCM, лише локальний CI-gate й відсутнє application deployment; він не підтверджує приймання телефона чи повного production DR.

## Спільна копія БД і черги — 14.10.2026

Source PR #126 і виправлення Compose preflight PR #127 злиті; обов'язкові CI
перевірки пройшли. Друга серверна спроба створила SQL і SQLite snapshots із
паузою не більше 40,589 с, але зупинилася під час публікації в сховище.
[Аудит спроби та перевіреного відкату](audits/PAIRED-BACKUP-PRODUCTION-2026-10-14.md).
Попередні файли й timer повернуті, сім контейнерів незмінні, API свіжий.
Нова production пара та її isolated restore **ще не прийняті**;
Діагностика передачі, повна публікація й operational приймання залишаються відкритими.
Ця операція не змінює статус Android, телефона чи Play.

## API та notifier — production приймання 12.10.2026

Після окремого дозволу власника API і notifier розгорнуто з канонічної
`main` `574b25cbf622c008a9e7d11a4d280af91963f71b`;
[PR #124](https://github.com/ikstv/AvelRen-ORIGINAL/pull/124) злитий,
усі 11 main CI jobs успішні. [Датований аудит розгортання](audits/API-NOTIFIER-DEPLOYMENT-2026-10-12.md)
фіксує installed-image перевірки та фактичний server readback о 19:57 UTC.
Обидві служби працюють на новому immutable image, RestartCount=0;
інші п'ять контейнерів та їхні images не змінилися. Health `ok`, age 16 s,
maintenance `null`. Плашка діяла 19:53:12–19:55:27 UTC: 135.263 s;
service window — 74.301 s. Production rollback не знадобився.

Власник прийняв короткий простій; подальша реалізація розширеного maintenance
плану для цього application deployment втратила актуальність. Збережені
часткові напрацювання не отримали нового operational приймання.
DB CLI залишається закритим; права БД/DSN, restore зі spool і live monitor —
окремі роботи. Нові APK/AAB, ручний FCM push, телефонні сценарії та Play
цим розгортанням не прийняті. Нижчі source/CI записи збережено як історичні.

## Єдиний CI-gate — source кандидат 12.10.2026

[Погоджений дизайн](superpowers/specs/2026-10-12-ci-aggregate-gate-design.md),
[план](superpowers/plans/2026-10-12-ci-aggregate-gate.md) та
[залишки приймання](MIGRATION-REMAINING.md) визначають окремі етапи.
Цей запис уточнює нижчий статус «CI-gate plan не реалізований».
FCM/security та датовані production/телефонні докази нижче збережені.

| Етап | Стан |
| --- | --- |
| Source та локальне review | Tasks 1–4 реалізовані й незалежно reviewed PASS; atomic workflow commit `54528d50def02eed4c1bd5ad2598cca42900b5d6`, актуальна main інтегрована комітом `4df904759a5405864c0d1d420c78f2e24bcdc224`. Docs Task 5 та whole-branch review ще потребують приймання. |
| Локальні перевірки CI-контракту | 26 незалежних legacy cases збережено; 675 scripts tests passed до final package-import fix, після fix 35 focused passed та standalone verifier PASS. Actionlint/Ruff/provenance PASS у звітах Tasks 1–4; final whole 676 run не виконувався. |
| Попередній hosted CI | PR #123 злитий у main `4ee4b1bd911fec5b78ae908ae593a8d81ac3cfa8`; сім звичайних main workflows SUCCESS. Це стара схема без нового `CI gate`. |
| Новий hosted PR CI | Ще не прийнято: після публікації CI PR потрібен один all-components run, точні base/head/tested SHA, gate, усі вісім calls і три artifacts одного run/attempt. |
| Новий hosted main CI | Ще не прийнято: після окремо дозволеного merge перевірити main-push на фактичному merge SHA. PR green його не закриває. |
| Enforcement main | Не увімкнено; protection/rulesets недоступні за тарифом. Потрібні окреме owner рішення про reviewer/bypass, effective API readback та failing-PR test для `ikstv`; self-approval автора не є незалежним review. |
| Серверне розгортання | Не виконано в CI етапі; API/maintenance/DSN cutover та live-monitor потребують окремого приймання й конкретного operational GO. |
| Android-збірка | Ця зміна CI не створює нового APK/AAB; чистий main, версія та SHA-256 лишаються вимогами релізу. |
| Телефон | FCM ownership/recovery, доставка/голос/ACK та решта реєстру приймаються своїми конкретними сценаріями з commit/version/APK SHA-256/датою. CI не закриває їх. |
| Google Play | Новий реліз цим CI етапом не опубліковано; окремі release/phone/Play gates залишаються відкритими. |

PR включно з draft запускає dispatcher без path/target-фільтрів на
`opened`, `synchronize`, `reopened`, `ready_for_review`, `edited`; push —
лише main. Repository завжди потрібний; docs-only PR до main і main-push
також виконують source та runtime-image SBOM. Edited title/body повторно
виконує потрібні jobs із витратами бюджету та не обходить failure.
Консервативний fallback вимагає всіх восьми calls навіть для non-main PR.
Усі checkout використовують `github.sha`, credentials false та read-only
permissions; чинні tests/pins/SBOM збережені, live-monitor ручний поза CI.

`CI gate` має scope + вісім calls у `needs`, `always()` і timeout 2 хв;
scope/план та required calls проходять лише з success, non-required —
success/skipped. Cancellation/required skip/missing або відсутній run не
є прийманням. Hosted доказ має містити не прострочені
`ci-plan-<tested_sha>-<run_id>-<run_attempt>`, `source-sbom-<tested_sha>`,
`runtime-image-sbom-<tested_sha>` та summary SHA саме одного run/attempt;
PR head може відрізнятися від tested synthetic merge SHA.
Бюджет лишається $3, витрати звіряються з доступними billed usage/storage;
budget block/pending/missing не є success. Billing/visibility/access/App,
production, телефон і Play цим планом не змінюються.

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

## Source acceptance DB executor — 12.10.2026

[PR #121](https://github.com/ikstv/AvelRen-ORIGINAL/pull/121) злитий у main
eed0cb0f5a337e88467943017bbca3a04d2593e2 після 8/8 успішних перевірок
head 418b747; relevant main workflows також успішні. Hosted основний DB набір
176 passed, upgrade 262 passed з одним попереднім skip. Це уточнює нижчий
запис про не підтверджене source review/CI/злиття, не є серверним прийманням.

Наступний source етап: [план maintenance та відновлення служб](superpowers/plans/2026-10-12-postgres-production-maintenance.md),
підготовлений для перегляду, ще не реалізований. Actual adapter, production
операції та DSN cutover не прийняті; production CLI закритий. APK/телефон/Play
цим етапом не змінюються.
## Оновлення безпеки urllib3 — кандидат 12.10.2026

[Залежність і межі перевірки](URLLIB3-SECURITY-UPDATE-2026-10-12.md): pin
urllib3 2.7.0 замінено на vendor-fixed 2.8.0 з офіційними SHA-256;
решта 34 Python pins незмінні. Ізольований Linux / Python 3.14.7 runtime
використовує 2.8.0, hash install, pip check і requests/google-auth imports
успішні; full unit — 669 passed, 2 dependency deprecation warnings.
Source кандидат від `c70dd8c`; review, інтеграція, hosted CI та
окремо погоджене server deployment ще відкриті. Android/APK, телефон і
Play цими локальними перевірками не прийняті; scan Python lock metadata
не є загальним CVE all-clear для контейнерів або production.

## Захист оновленого FCM-токена — кандидат 12.10.2026

[Notifier fix і докази](NOTIFIER-TOKEN-RACE-2026-10-12.md) зберігають новий
FCM-токен, якщо відповідь UNREGISTERED стосується старого токена.
Normal alert лишається pending; cancel після зміни токена записує одну
невдалу спробу й використовує наявну годинну межу повторів. Додаткового
FCM send у поточному циклі немає. 14 синтетичних PostgreSQL-регресій
успішні локально; код — source кандидат гілки
`codex/notifier-token-race-20261012` від `eed0cb0`. Review, hosted CI,
злиття, окремо погоджене deployment і live/телефонне приймання ще відкриті.
Android-код і APK не потребують зміни для цього серверного виправлення;
публікацію Play та доставку на телефоні не виконували.

## Уточнення стану — 11.10.2026

[Датований audit сервера та PR](audits/MIGRATION-SERVER-2026-10-11.md)
підтвердив non-null scores і API status=no_signal/reason=null для чотирьох
підтримуваних КПП. Нижча позначка insufficient_history від 08.10 описує
історичний стан після встановлення. Точність прогнозу та показ на телефоні
цим аудитом не приймалися. #106/#107/#113–#116 злиті після успішного CI
відповідних heads; [підсумок інтеграції](audits/MIGRATION-INTEGRATION-2026-10-11.md)
фіксує merge-коміти та спільні ізольовані перевірки.
Нижчі записи про підготовку цих PR є історичними. Нове розгортання не виконане;
готовність APK/телефона/Play не змінюється.

Зовнішній monitor: [ручний перенос](EXTERNAL-MONITOR-TRANSFER-2026-10-11.md)
переносить outage/alert-channel/undelivered перевірки. Source прийнято PR #118
у main `1fdcbf2`, CI head `f94243c`: 4/4 success, 17 tests PASS. Live запуск,
доставка GitHub notifications та заміна старого scheduled monitor ще
не прийняті. APK/телефон не змінюються.

Права БД: [адаптована production процедура](POSTGRES-ADOPTION-PRODUCTION-RUNBOOK.md)
відокремлює ownership/ACL, DSN cutover і retirement. DB executor source
етапу 1 реалізований та ізольовано перевірений (`c84d0a9..69c25cc`): binding,
manifest/confirmation, quiescence, transactions, receipts та explicit inverse.
Два кластери з однаковими dbname/catalog/plan відхиляють чужий target без
зміни ACL/data; physical-clone runtime boundary перевіряється unit fake.
Публічний production CLI закритий. Actual maintenance adapter, runtime DSN
cutover та operational acceptance залишаються окремими етапами. Review,
exact-head hosted CI та злиття кандидата ще не прийняті цим записом;
deployment/live DB, APK/телефон/Play не виконані. Android незмінний.

## Зупинка клієнтів після помилки restore — 11.10.2026

[Контракт та перевірки](RESTORE-FAILURE-STATE-2026-10-11.md).
Аварійний EXIT намагається зупинити Caddy, API, collector, notifier
і watchdog, потім перевіряє стан контейнерів. Непідтверджена зупинка
позначається unverified зі збереженням первинного коду помилки.
Source-зміна готується в окремому PR; CI відображено в ньому.
Production deployment і робоче restore не виконані. Android не змінено.

## Очищення перерваного відновлення БД — 11.10.2026

[Контракт і походження](RESTORE-INTERRUPTION-CLEANUP-2026-10-11.md).
Restore робить одну спробу TimescaleDB post-hook після HUP/INT/TERM,
зберігаючи первинний код помилки й зовнішній EXIT-обробник.
Код і перевірки готуються в окремому PR; результат CI наведено в ньому.
На production не розгорнуто, робочий restore не виконано. Android-код
не змінено; перевірка телефона та публікація до цього виправлення не належать.

## Захист інтервалу collector — 11.10.2026

Перенесено захист, виявлений у встановленому collector під час read-only
звірки: 60-секундна стартова пауза, відлік від фактичного початку циклу,
монотонний RequestPacer перед HTTP send, заборона redirects і обмежена
діагностика response headers. Це запобігає скороченню інтервалу після
запізнілого пробудження та додатковим запитам через перенаправлення.
Endpoint, Device ID, контракт даних і частота 60 секунд незмінні.

Локальні регресійні тести використовують MockTransport та підмінний
годинник; production й upstream не залучені. Код підготовлено в окремій
гілці; CI, злиття та розгортання саме цієї збірки ще не підтверджені.
Під час аудиту сервер уже містив ці виправлення, але це не доказ
тотожності майбутнього image усьому live runtime. Android/APK/Play
цим патчем не змінюються; телефонне приймання не виконувалося.

## Ownership/ACL — source кандидат 08.10.2026

[Adoption компонент](../ops/POSTGRES-ADOPTION.md) додає приватний inventory,
планування та disposable forward/inverse для схеми 001–016. Restore-приймання
входить до database CI; остаточний CI статус визначається за exact head PR.
Залежність — [PR #106](https://github.com/ikstv/AvelRen-ORIGINAL/pull/106).
Production executor і DSN cutover відсутні; сервер та APK не змінювали.

## Read-only перевірка прав БД — кандидат 08.10.2026

Окремий [операторський gate](../ops/POSTGRES-PRIVILEGE-GATE.md) перевіряє
контракт схеми 001–016. Код і disposable-тести — у цьому PR; CI має
підтвердити точний head. На сервері gate не встановлювали й не запускали.
Зміна не потребує APK або Play-публікації; runtime adoption і телефонні
сценарії інших функцій залишаються окремими етапами.

## Відновлення прогнозу й причини помилок джерела — 08.10.2026

[Інцидент і виправлення](SURGE-RECOVERY-DIAGNOSTICS-2026-10-08.md).
Невдалий прогноз повторюється після свіжого хвилинного вимірювання,
успішний залишається один за годину. Безпечні transport reason/errno та
тривалість зберігаються в spool, collector_runs і логах. Прогноз працює
для чотирьох підтримуваних черг; це не розширення моделі на всі КПП.
Код злитий у main через PR #108 (merge `61fff58`), 8/8 CI head `574e158`
успішні. Production worker/collector встановлені 08.10.2026 за окремим GO:
5 природних циклів кожного, collector HTTP200/60s, spool integrity/pending0,
встановлені hashes і решта контейнерів перевірені. API усіх чотирьох ID
повторив невдалий прогноз у тій самій годині після свіжих даних.
Повернення non-null score після безперервного вікна ще не прийнято;
API поки insufficient_history після паузи встановлення. Перевірки телефона
та публікації немає; Android-код не змінено.
[Деталі production приймання](audits/SURGE-RECOVERY-PRODUCTION-2026-10-08.md).

## Виправлення номера релізу — 07.10.2026

За прямим уточненням власника правильний номер наступного випуску після
0.1.2 — 0.1.3, не 1.0.3. Виправлено versionName, назву Test, поточний
заголовок історії, шляхи описів і перевірки артефактів. versionCode 6,
package, дата, підпис, функції та сам погоджений опис незмінні.
Історичні записи нижче з 1.0.3 лишаються доказами попереднього стану,
а не актуальним номером. Офіційні APK/AAB слід перебудувати з чистої main.
Після перевірки використати наявну порожню чернетку v0.1.3; помилковий
GitHub Release v1.0.3 видалити за дозволом власника, зберігши його Git-тег,
коміт і локальні артефакти. SECURE BACKUP не змінювати; це найстаріший запис.

## Фінальне оформлення 1.0.3 — 07.10.2026

Власник прийняв установлену Test 0360cf3 із зауваженням: прибрати
«у підготовці» з історії 1.0.3. Для погодженої публікації 07.10.2026
установлено дату 7 жовтня 2026 року; якщо день публікації зміниться,
дату слід звірити до фінальної збірки. Дата в коді не є доказом публікації.
У двох канонічних описах змінено лише завершення на «Функція в розробці».
Додаток і GitHub використовують той самий повний опис.
Підписаний official APK/AAB, перевірка їхніх package/cert/hash та
GitHub Release ще очікуються. Play не публікується в цьому кроці.

Контрольна звірка телефона 07.10.2026, 18:25–18:28 Київ: Test 1.0.3/6
з чистої main 0360cf371f6b8c6d69cb8798e2c3ebcd47a3e67e,
APK SHA-256 448aff0c14e513a43d69576f4aa54b3ffe57a125a1b7cbea92d2fd5dfdce9b81.
Підпис APK перевірено; запуск, прокручування історії описів, головна
картка та перехід до прогнозу працюють. У прогнозі «До 3 КПП»,
«Вибрано 0 із 3» та «Функція в розробці». Порядок налаштувань правильний;
сервер показує CPU/RAM/disk із GB, відсотки мають однаковий правий край.
Приватні дії Admin, нові push/голос та stress/performance не повторювалися.
Це звірка Test, не ще незібраного official APK; нова дата й завершення
опису потребують перевірки фінального артефакту.

## Три КПП та голосові повідомлення — 07.10.2026

За погодженням власника Android-вибір прогнозу обмежено трьома КПП.
Лічильники екрана та діалогу використовують спільний ForecastSelection.MAX.
Опис: «Моніторинг черги та голосові повідомлення для трьох обраних КПП:
прогноз можливого зростання й повідомлення про початок масової реєстрації».
Розрахунки, доставка голосу та серверний контракт підписок не змінюються;
серверні підписки автоматично не видаляються. Локальний парсер вибору
приймає до трьох коректних унікальних ID, як і решта Android-вибору.
Новий APK, телефонне приймання та публікація ще очікуються.

## Компактні ресурси сервера — 07.10.2026

Погоджено три окремі рамки CPU/RAM/disk: SignWarn ROAD SIGN, 1 dp,
кут 16 dp, padding 12 dp, без додаткового світіння чи анімації.
Назви зліва, відсотки однакового стилю вирівняно по правому краю;
RAM/disk обсяг окремим рядком під назвою, не у незалежному FlowRow.
Телефонні font/theme/scroll/рамки лишаються окремим прийманням.

Погоджено RAM/disk у GB (bytes / 1 000 000 000), не перейменовані GiB.
Відсотки незмінні. Прибрано часові підписи під кожною ResourceStrip;
залишається спільний CPU snapshot час біля «Оновити». Це не доказ одночасності
всіх ресурсів: їхні timestamps/expiry/stale перевіряються незалежно, старі
та некоректні значення й надалі показуються як недоступні.
Телефонне оновлення/приймання ще відкриті; нижній напис прогнозу
«Функція в розробці» входить у той самий кандидат PR #102.

## Короткий підпис прогнозу — 07.10.2026

За прямим погодженням власника нижній текст ForecastOverviewScreen змінено
на «Функція в розробці». Це лише текст: прогноз/розрахунки не змінюються.
Телефонне оновлення та приймання нового напису ще відкриті.

## Зрозумілий опис 1.0.3 — 07.10.2026

Погоджене уточнення навігації: меню «Про додаток → Тема → Для розробника».
Окремий пункт політики прибрано. У «Про додаток» опис зліва активний;
права вкладка «Політика конфіденційності» відкриває той самий URL у браузері.
Повернення з браузера не перемикає опис; preview callback збережено без
реального переходу. Не додано WebView, копії політики або HTTP polling.
Телефонні gates: порядок меню, повернення з браузера, довгий опис/scroll,
обидві теми, великий шрифт і читабельність довгого підпису правої вкладки.

У цьому ж кроці власник попросив прибрати «За історичними даними» після
часу очікування в головній картці КПП. Видалено лише suffix legacy_unknown;
seconds/status, ETA, missing/zero обробка й окремий прогноз не змінюються.

За погодженням власника додаток і GitHub використовують повний опис,
Google Play — короткий текст до 500 символів з тим самим змістом.
[Контракт та канонічні файли](RELEASE-0.1.3-DESCRIPTIONS.md).
Попередній fullTest з main `65f677c` встановлено о 15:42:23 Києва;
SHA-256 `2406ed1cfd9a33c152bd4d08bfa82e37910a21f6973e9743fc9a113c53136b99`,
readback MATCH. Цей запис підтверджує встановлення, не всі телефонні сценарії.
Новий опис ще потребує CI/інтеграції/clean-main APK/readback та прочитання
власником. Публікації GitHub/Play не виконані.

## Повнофункціональна 1.0.3 Test — кандидат 07.10.2026

Погоджений fullTest використовує основний код додатка, production API та
окремий Firebase-клієнт `ua.avelren.app.test`. Приватна конфігурація поза Git;
офіційний клієнт не змінено. У «Сервері» лише CPU, RAM і диск, без traffic.
Режим debug-only, несумісний з іншими тестовими режимами; фікстура тільки
для CI, не для встановлення. Деталі: [ANDROID-FULL-TEST](ANDROID-FULL-TEST.md).

Локально: 243 JVM tests без помилок, compile/manifest/lint успішні;
fullTest artifact contract, provenance, CI scopes та pushQa contract PASS.
Release і змішані режими відхилено очікуваними guards. Незалежний review
не знайшов Critical/Important дефектів; посилення перевірок private ACK/
provider flags лишається необов'язковим test-hardening.

Погодження інтеграції отримано. Ще відкриті: CI точного нового commit,
злиття, чиста main, APK з реальною конфігурацією, SHA/readback і телефонне
приймання FCM/голосу/підписок/ACK/екранів. Новий APK ще не встановлено.
Адмін-прив'язка не копіюється й автоматично не надається. Публікації GitHub
та Play очікують приймання власника. Нижче — історія попередніх gates.

## Три живі ресурси та нейтральне поле пароля — 07.10.2026

Після окремого GO розгорнуто вузький серверний пакет з кандидата
`7e35d93`: API, watchdog та host snapshot. [Фактичне приймання](audits/TELEMETRY-THREE-2026-10-07.md)
завершено о 14:52:56 за Києвом: public endpoint 200, CPU/RAM/disk свіжі,
два наступні штатні cycles, whitelist, host probes і watchdog hash PASS.
Міграції й п'ять інших контейнерів незмінні; reboot не виконано.
Traffic та витрати відкладаються. Підготовлений точний відкат не виконувався.

За прямим побажанням власника поле адміністратора має «Введіть пароль»
без «4 цифри»; повідомлення помилки — «Неправильний пароль».
Це лише UI-текст, не посилення захисту: numeric keyboard, довжина коду,
валідація, POST, блокування й авторизація залишилися без змін.
Android unit/compile offline успішні; є SDK XML version warning.
Новий APK не зібрано й не встановлено, телефонне приймання тексту відкрите.

До повнофункціональної 1.0.3 Test залишаються окремі gates:
погодження інтеграції гілки, чиста main, окремий client/package із реальним
API і робочим FCM, три смужки без незапитаного traffic placeholder,
збірка/SHA/readback та реальні телефонні сценарії. Наявний connectedTest
вимикає push; preview має локальні фікстури; pushQa не підключений до
production API. Жоден із них ще не є обіцяною повністю робочою Test-версією.

## RAM, диск і місце для місячного трафіку — 07.10.2026

Кандидат у гілці codex/resource-telemetry-20261007; не злитий і не розгорнутий.
Точні RAM/disk bytes, public whitelist, Android DTO/смужки, часткові дані,
expiry без HTTP та error-refresh включені. Traffic live лишається недоступним
до підтвердження provider billing period/read-only access; колектор не встановлений.
Деталі: [контракт і залишок](PUBLIC-RESOURCE-TELEMETRY.md).
Code/local tests/CI, production, clean-main APK, телефон і Play — окремі gates.
Телефонні великий шрифт/обидві теми та API↔APK ще не прийняті.
Після погодження власника додано відносний підпис «сьогодні/вчора» із часом;
старіші вимірювання мають дату, інший рік — повну дату. Часовий пояс Київ.

## Відгук кнопок і видиме оновлення — 07.10.2026

Погоджено короткий системний VIRTUAL_KEY-відгук як у нижній навігації
для активних кнопок, клікабельних плиток, фільтрів і вибору КПП.
Спільні hapticClick/hapticClickable/tapNoRipple замінюють розрізнені імпульси;
заблоковані дії не активуються, системне вимкнення відгуку не обходиться.
Оновлення CPU утримує busy щонайменше 400 мс паралельно запиту, а не після
нього. Cancellation скасовує таймер; мережевих повторів не додається.
Назву розділу змінено на «Для розробника» за окремим побажанням власника;
Server залишається публічним, Admin auth не змінюється.
Код і перевірки цієї гілки не підтверджують встановлення на телефоні.
Фізичний вібровідгук і індикатор треба перевірити після чистого main APK.
RAM у цей обмежений крок не входить; її дизайн/реалізація окремо попереду.

## Компактний CPU та індикатор оновлення — 07.10.2026

Власник погодив прибрати пояснення про секундний знімок і замінити підпис
на «Оновлено: dd.MM о HH:mm». Це час вимірювання з API у Києві, не час
натискання: невдалий запит не робить попередній знімок свіжим.
Під час запиту напис «Оновити» замінюється обертовим індикатором у тій
самій кнопці; її розмір і блокування повторних натискань збережені.
Автоопитування не додається. Код, CI та новий APK/телефонне приймання
цього уточнення ведуться окремо; до телефона ця зміна ще не доставлена.

Попередню CPU-версію PR #97 інтегровано після окремого дозволу власника:
main `f27cc8115f2273037c44e5776f0b8ccebcb63835`, preview `1.0.3-test`,
SHA-256 `2d72e9e8eec12cf015be2fcafc50df445b81628fcd85e92c5f152ffe72ffa5f9`.
07.10.2026 встановлено поверх тестового додатка; readback збігається.
14 CPU-сценаріїв пройшли (11 початкових + 3 повторних після невідтвореної
зупинки навігації тесту), світла/темна тема, шрифт 100/130/200%.
Вісім CI checks PR #97 успішні. Це локальні синтетичні дані;
production не розгорнуто, офіційний додаток і Play не змінені.
Повного релізного чи performance-приймання цей запис не підтверджує.
Нижче — попередній історичний запис підготовки, а не актуальний статус PR #97.

## Публічний CPU екрана «Сервер» — у роботі, 07.10.2026

Власник погодив дизайн і native-план у docs/superpowers/specs/ та plans/
для public-cpu-telemetry. «Адміністрування» має стати «Для адміна»,
«Сервер» залишиться загальнодоступним. CPU, компактний час біля ручного
«Оновити» та градієнт зі статичним слабким світінням не є готовим екраном.

Почато host snapshot: дев’ять справжніх CPU-тестів спершу впали через
відсутність поля, після реалізації пройшли в кешованому ізольованому
Alpine-контейнері без мережі. Для діагностики лише тестового контейнера
використано shim GNU relative-date; production-сценарій дати не змінений.
Незмінений baseline має відоме падіння test_full_snapshot_and_log_counts:
BusyBox awk переповнює 32-бітний printf для мережевого лічильника.
Це не зелений повний suite і не заміна штатного GNU/Linux CI.
Повний офлайн Windows unit suite: 340 passed, 2 deprecation warnings;
ruff і bash -n успішні, маніфести походження звірені. Для pytest використаний
новий ізольований --basetemp: старий системний каталог був недоступний.
Штатний GitHub GNU/Linux watchdog CI на a6b7408 пройшов: 9 watchdog/БД
та 14 snapshot-тестів (run 37583441119); Alpine-обмеження вище не є
падінням штатного CI. Публічний GET /api/server/status реалізований:
лише CPU, дата, односекундне вікно та stale; без БД, probe чи admin credentials.
Свіжість — до 300 секунд; некоректні й майбутні дані не стають 0%.
Нові 30 API unit-тестів бачили RED→GREEN; повний suite — 370 passed,
2 наявні deprecation warnings; ruff успішний. Контрактний CI нового API
ще очікується; старий сервер без endpoint поверне 404, не 0%.
Контрактний API CI b3f47bb: 78 passed (run 37584481197).
Android-екран реалізований у гілці: «Для адміна», загальнодоступний
«Стан сервера», CPU й дата біля ручного «Оновити». Legacy activeDevices
і Admin auth не видалені. Preview має лише локальні cpu_fixture
0/50/100/null/stale/error; стандартний CPU — синтетичні 37%.
Шість presentation/loader і два HTTP-тести спершу впали; повний
офлайн Android suite — 238 тестів, compile та lint успішні (0 errors,
34 warnings, 6 hints; також наявне попередження SDK XML version).
Маніфест Android: 64 записи та asset provenance успішно звірені. Незалежний review,
погоджена інтеграція, чистий main APK, телефон і deployment не прийняті.
Незалежний review fd9e6c4..5a8bf8b знайшов два P2: CPU не ставав
застарілим на нерухомому екрані та некоректні UTC-дати/наддовге JSON-число
могли спричинити 500. Виправлено одним RED→GREEN проходом: три API
регресії й тест локального застарівання; повні suites 373 backend / 239 Android
успішні, lint 0 errors/34 warnings/6 hints. Локальне одноразове застарівання
не робить HTTP-запитів. Остаточний CI виправлень ще очікується.
За явним рішенням власника телеметрію не зливати: PR залишається draft,
гілка збережена для можливих подальших метрик. Телефонне приймання CPU
не проведено, production не змінений. Повний Task 3 і план не завершені.
Hash-контракт snapshot/watchdog синхронізується
разом; встановлений production snapshot у цьому кроці не змінюється.

## Повна назва КПП, дата цілі та червоне прибирання — 07.10.2026

Власник погодив обмежене UI-виправлення без зміни API, прогнозу чи голосу:
моніторинг прокручується одним списком із природною висотою плиток;
повна назва КПП має власний рядок; дата й час цілі відокремлені від
в’їзду за поточною чергою. Навігація не використовує розрядку 0.2em.
Прибирання в прогнозі, порогах і часі в’їзду — спільна червона кнопка
ROAD SIGN `#D5382C`, 48dp, із назвою КПП для TalkBack. Підтвердження
видалення збережене; сам натиск хрестика не видаляє підписку.

Дефекти відтворені на preview 1.0.3-test із чистої main
`070c0a199afcc60ca1b6419e81a5260a7f1e089d`, SHA-256
`a595b6293a586b116817ead14d6bac24029c93d1730c9cec3818e4a6c8eb4846`:
при font_scale 2.0 зникає назва ETA-КПП, плитки стискають підписи,
а ціль «завтра 23:00» показується без дати. Перевірка великого шрифту
цього APK не прийнята, попри успішне встановлення й попередній CI.
Два JVM-тести відтворили втрату дати, ще один — втрату уточнення
типу вантажівки в дужках. Некоректна дата має безпечний підпис «—».

Локальні перевірки: 230 JVM-тестів, 0 failures/errors; compileDebugKotlin
і lintDebug успішні (0 errors, 34 warnings, 6 hints); verify_android —
64 записи. Незалежний read-only review не знайшов блокерів, його зауваження
до застарілих коментарів виправлене. Телефонний regression-сценарій
відхилив старий APK через відсутність доступного хрестика в прогнозі.
CI, merge, чистий-main APK, readback SHA-256 і повторне
телефонне приймання 100/130/200% в обох темах не підтверджені.
Перевірити довгу назву, дату цілі, останній рядок моніторингу з підказкою
автозапуску, скасування/підтвердження прибирання в усіх трьох сценаріях.
Production, офіційний пакет і Play не змінюються. Це не готовність релізу.

## Великий шрифт і дати в історії релізів — 07.10.2026

Погоджений локальний крок: адаптивна нижня навігація та фактичний резерв
під увесь нижній блок (джерело/розробник, оновлення, навігація). На головній
прокручуваний вміст не малюється за футером. ROAD SIGN, назви вкладок,
прогноз/голос, API та серверний стан не змінюються.

У «Про додаток» заголовки містять версію й дату публікації GitHub Release
у київському календарі: 0.1.0/0.1.1 — 24 вересня 2026 року,
0.1.2 — 26 вересня 2026 року. Для неопублікованої 1.0.3 — «у підготовці».
Джерело дат: `gh release list --repo ikstv/AvelRen-ORIGINAL`, поле
`publishedAt`, звірене 07.10.2026. Не плутати з датою APK чи затвердження Play.

Перед фінальним APK/AAB потрібно замінити статус 1.0.3 на погоджену дату
релізу й звірити її з фактичною публікацією; автоматичного підтягування
з GitHub на телефон немає. Канонічні тексти приміток не змінені.

Початковий дефект відтворено на preview 1.0.3-test, clean-main
`0f02f5258625d57328c2dff351cc5e518c6b0e0d`, SHA-256
`fd122c15ff528f437caeb8dfb2fdda27436737c902c654bd332525289f78b589`:
при font_scale 2.0 обрізана нижня навігація та накладення attribution.
Два тести нижнього відступу впали на старій фіксованій поведінці; три
тести заголовка впали до реалізації дати/статусу. Після виправлення:
226 JVM-тестів без failures/errors, compileDebugKotlin і lintDebug успішні
(lint: 0 помилок, 46 попереджень); verify_android перевірив 64 записи.
Незалежний read-only review не знайшов блокерів для PR. CI, merge та
встановлення нового чистого-main APK — окремі етапи.
Телефонне приймання виправлення ще НЕ виконано: перевірити 100/130/200%,
обидві теми, останню картку після прокручування, About і стан оновлення.
Короткі вікна/landscape також не прийняті: при недостатній висоті треба
перевірити доступність навігації разом із великим футером та update pill.
Це не готовність до GitHub/Play-релізу; performance також ще не прийнято.

## Читабельність екрана прогнозу — 06.10.2026

Власник погодив скорочення вступу, компактніші картки КПП та виразнішу
подачу події й можливого часового інтервалу без зміни логіки/API.
Внизу постійно: «Функція працює в тестовому режимі і вона тільки в розробці».
Розділення прогнозу/факту та кнопки з мінімальною висотою 48dp збережено.
Старий встановлений APK відхиляється телефонною перевіркою нового тексту.
Новий чистий-main APK, обидві теми, прокручування й великий шрифт ще
потребують приймання; це не готовий GitHub/Play-реліз.

## Виправлення тестової оболонки — 06.10.2026

Офлайн APK main `17c3a1b7a4c1984d3f849cfa794d993711897056`, версія
`1.0.3-test`, SHA-256 `4faa026da84a992ccd51b97d072a6c167822052c9ab5e6d552ee302011b8d34d`
встановлено 06.10.2026; readback збігається. Власник відхилив візуальну
відповідність: службова панель й обгортка зменшують екран.
Підготовлено виправлення без додаткової теми, відступів та видимої панелі.
Телефонний regression smoke-тест спершу відхилив встановлений старий APK
за наявністю службових елементів. CI, чистий-main APK і перевірка нового
інтерфейсу на телефоні ще відкриті. Production/офіційний пакет/Play не змінюються.

## Офлайн тестова копія — початок 06.10.2026

Погоджені дизайн і план `superpowers/plans/2026-10-06-offline-app-preview.md`.
Виділено атомарне паралельне завантаження моніторингу без зміни UI/API;
213 JVM-тестів пройшли, 0 failures/errors, provenance перевірено.
Повна ін'єкція клієнтів, preview-навігація, сценарії та APK ще не готові.
Додано контракт AppScreenClient і продуктовий адаптер; тест перевіряє
моніторинг із наявними installation credentials без нової реєстрації.
Повний JVM suite після додавання адаптера пройшов. Адаптер ще не
підключений до UI в початковому адаптері. Наступною зміною клієнти
передані у спільні екрани, ForecastScreen і ACK callback; повний JVM suite
та compileDebugKotlin пройшли. Локальний preview-клієнт і навігація ще
не підключені, тому це не готова тестова копія.
На телефон нову збірку не встановлювали; офіційний додаток не змінено.
Локальні сценарії й спільна preview-навігація тепер реалізовані.
219 JVM-тестів, preview lint та assembleDebug пройшли 06.10.2026.
Маніфест: ua.avelren.app.preview, без INTERNET/Firebase init/FCM service.
Це технічний APK з гілки: на телефон його не встановлювати. Review, CI,
інтеграція, чистий main кандидат і телефонне приймання ще відкриті.
Незалежний [review](audits/OFFLINE-PREVIEW-REVIEW-2026-10-06.md) знайшов
offline-state та обхідні серверні залежності; внесено виправлення.
Повторний повний прогін: 220 JVM-тестів без failures/errors, lint і assemble
успішні, manifest/provenance перевірені. CI нового head і UI-приймання
ще потрібні; review старого head не означає схвалення нового.

## Продовження системного голосу на ноутбуці — 06.10.2026

[Фактичні докази](audits/ANDROID-SYSTEM-VOICE-PHONE-2026-10-06.md):
main `1f30f6dc`, 1.0.3-push-qa/code6, SHA-256
`3df34578d008c88c0f4f74239058efdd25adb04c8aa1c41c4c01a507e6ab6f90`
звірено з установленим base.apk. Власник підтвердив прогноз і факт Чопа
у фоні з media0, а також нову подію після ACK. Доставлена спроба того
самого факту після ACK не відновила повідомлення чи голос (ART trace).
Спроба Краківця UNKNOWN через SSH/мережеве переривання; після cleanup
власник дозволив продовжити залишок ліміту. Locked Краківець, Ягодин
і Ягодин для порожніх вантажівок після цього підтверджені повністю.
Використано 8/8 спроб: 7 HTTP200, 1 UNKNOWN. QA видалений із телефона
і Firebase, офіційний додаток збережено. Locked Рава-Руська, TTS/lifecycle,
overflow/deadline та фінальна публікація лишаються відкритими.

## Системний голос — продуктова реалізація кандидата

Гілка `codex/system-notification-voice`, [опис компонентів](ANDROID-SYSTEM-VOICE.md).
Додано підготовку двох фраз, перевірку WAV/SHA, read-only provider,
сталі канали й послідовне системне озвучення через shortService.
Нові правила ресурсів, каналів і deadline пройшли RED→GREEN та локальний
Android JVM/assemble/lint. Серверних змін немає. PR88 і його main merge
2a7a849 мають усі4 CI SUCCESS; чистий main APK встановлений зі звіркою SHA.
[Докази телефона](audits/ANDROID-SYSTEM-VOICE-PHONE-2026-10-04.md): media0,
скасування та п'ять повних фраз підтверджені власником. Перша FCM-спроба
FAIL через тихі QA канали після Xiaomi off/on збережена. У погодженому
повторі 04.10.2026 використано 3/8 push (разом 4/9): справжній фоновий
прогноз з media0 власник почув повністю; точний доставлений дубль не озвучено.
Чутність другого нового прогнозу ще очікує підтвердження власника.
FCM факту/ACK/locked, решта телефонної матриці та публікація не прийняті.
QA cleanup підтверджений; на прохання власника роботу зупинено для переходу
на ноутбук. [Наступні дії й стан](HANDOFF-2026-10-04-VOICE.md).
Незалежний review завершено; чотири важливі findings виправлено з
поведінковими RED→GREEN тестами та зеленим повним локальним gate.
PushQa fixture і connectedTest assemble/lint успішні; release manifest
не містить тестового receiver. Fixture APK не встановлювався.

## Системний звук голосу — локальна проба 04.10.2026

[Докази й умови](audits/ANDROID-NOTIFICATION-VOICE-PROBE-2026-10-04.md).
Тимчасовий прототип `188ffee683b2aa0b58027526aa173f0c92f63da5`,
`ua.avelren.app.preview` 1.0.3-test/code6, APK SHA-256
`7fb328b848fa3b2665629d6f1d66084deaa92761e78e792547e269339b245952`:
власник почув прогноз у фоні й факт із заблокованим екраном 04.10.2026.
Це локальний broadcast і системний звук підготовленого WAV; media=1,
notifications=5. Продуктовий код, CI, справжній FCM, media=0, п'ять КПП,
ACK під час звуку та публікація ще не прийняті. Серверних змін немає.
[Специфікація](superpowers/specs/2026-10-04-system-notification-voice-design.md)
погоджена власником 04.10.2026 у PR #87, commit `8af9cc1`.
[План реалізації](superpowers/plans/2026-10-04-system-notification-voice.md)
погоджений власником 04.10.2026; виконання агентом у цій сесії.
Наступний prototype commit `5091aa2e24e2da05d62d7a3451eb598a1687be80`,
1.0.3-test/code6, APK SHA-256
`bd9a85e9ca091afd266896897d4fe564ee7caac49a6c9cc7947e993a541f08e9`:
04.10.2026 власник підтвердив тихе→звукове оновлення та скасування під час
фрази та всі п'ять фраз повністю («так почув»). П'ять системних завершень
підтверджені журналами; локальний gate update/cancel/sequence успішний.
Прототип не зливається в реліз; продуктовий код і справжній FCM ще попереду.

## Справжній FCM на телефоні — 04.10.2026

[Повний запис і відкат](audits/ANDROID-FCM-PHONE-2026-10-04.md).
PR #85, main `bc5abae47f1330fca421861b5c3ea0d1db9f0a33`, усі 5 CI успішні.
APK `1.0.3-push-qa`/6 встановлено й звірено за SHA-256
`f2f6cc71f5c450ca9d52d676ada0ae193ef5834ace5e484ab7486c136401ada5`.

Справжній high-priority FCM доставив сповіщення у фоні, але **голос не
пройшов**: Android 15 відхилив audio focus (`audio_busy`, 0 TTS callbacks).
Зупинено після 1 push; повтори, locked та ACK не перевірені. Media фактично
лишилося 5/15, тому сценарій media=0 цією пробою не підтверджено.
QA пакет і Firebase-клієнт прибрані з перевіркою; робочий клієнт збережено.
Голос залишається блокером фінального приймання й релізу 1.0.3.

## Окремий FCM QA — підготовка 03.10.2026

[Межі, перевірки й конкретний план](ANDROID-PUSH-QA.md): окремий debug
пакет для доставки FCM і голосу на телефоні зі збереженням Play-версії.
Код — кандидат; CI, реальна конфігурація Firebase, встановлення й
голосові push ще не прийняті. Серверний ACK цим пакетом не перевіряється.
Зовнішнє створення Firebase-клієнта й надсилання потребують окремого GO.

## Голос на телефоні — перевірка 03.10.2026

[Сценарії й фактичні результати](audits/ANDROID-VOICE-PHONE-2026-10-03.md).
PR #83 злитий у `0d8d2edbf94b8f7755c771220412b1289edbbece`; усі 4 CI
цього main успішні. Власник схвалив початковий тембр словами «так гуд».

- Прослуховування на відкритому екрані: 1.0.3-connected-test/code6,
  SHA-256 `a4b84353d1550a33635d29cb832a44e7e29dd8571200aa4d094b2293419a78e4`;
  обидві фрази озвучені, media=0, власник підтвердив голос.
- Офлайн службовий тест: 1.0.3-test/code6, той самий main,
  SHA-256 `92e57c0c5df477a03f081bba5ca0f7f9e937e1b5f57fe49b4b838f9f40c6b399`.
  Встановлений APK звірено за хешем.
- Після згортання: локальне сповіщення є, голос **не пройшов**;
  Android 15 відхилив audio focus (`audio_busy`).
- Після погашення екрана з відкритої тестової activity: під час події
  keyguard=true, audio focus надано й звільнено, служба завершилась без
  voiceProblem. Власник підтвердив чутність відповіддю «так» 03.10.2026.
- Це локальні проби з різними умовами запуску. Реальні FCM, холодний фон,
  повтори, ACK/offline та reboot не прийняті. Сервер не змінювався.

Повне приймання телефона й публікація 1.0.3 залишаються відкритими.
Тестові повідомлення прибрано з окремого QA пакета.

## Початковий тембр голосу — 03.10.2026

На прохання власника повертаємо початковий український голос
`uk-UA-language` і природну висоту `pitch=1.0` у службі озвучення та
технічному прослуховуванні. Поточний темп `0.88` і гучність сповіщень
зберігаються. Доступні лише встановлені локальні українські голоси;
якщо потрібного немає, діє наявний вибір локального голосу.

Код: кандидат; CI та встановлення нового APK ще не підтверджені.
Попереднє прослуховування 1.0.3/code6 з main `4b8d1c1` технічно
завершило обидві фрази з media=0, але власник попросив змінити тембр.
Серверних змін немає. Фінальне звучання, доставка FCM, повтори та ACK
на телефоні ще не прийняті. Попередні release APK/AAB з `bc41a15`
не містять цієї правки й потребують перебудови до публікації.

## Стан 1.0.3 на 03.10.2026 о 03:00 за Києвом

[Фактичне приймання сервера й артефакти](audits/RELEASE-1.0.3-SERVER-2026-10-03.md).
Цей запис уточнює попередню невдалу спробу пакування моделі нижче.

| Етап | Стан |
| --- | --- |
| Код і CI | main bc41a15, PR #81; усі 7 відповідних CI успішні |
| Сервер | Прогноз увімкнений; 2 worker цикли й 4 свіжі результати DB/API прийняті |
| Збір даних | Collector працює, pending 0; плашка прибрана |
| Android | Підписані APK/AAB 1.0.3 / 6 зібрані, SHA і підписи перевірені |
| UI | Офлайн емуляторні сценарії пройдено |
| Телефон | Фінальні FCM/голос/ACK/offline/PIN ще не прийняті |
| GitHub Release / Play | Не опубліковано; власник редагує опис |

Історичні дослідження: [28 днів](FORECAST-SURGE-28-DAYS-2026-10-02.md),
[Чоп](FORECAST-SURGE-CHOP-2026-10-01.md), [моделі](FORECAST-SURGE-MODEL-PROBE-2026-10-02.md).
Незалежна якість 99% / 99% залишається непідтвердженою.


## Керування collector через Compose — приймання 02.10.2026

Погоджено напрям: окремий Compose для встановленого spool-collector,
збереження image/Device ID/DSN/тому, перевірка відсутності другого poller,
операторські команди та процедури capture-only для обслуговування БД.
[Записана специфікація](superpowers/specs/2026-10-02-collector-compose-control-design.md)
і [план реалізації](superpowers/plans/2026-10-02-collector-compose-control.md)
схвалено власником; реалізацію виконано в цій сесії. Код:
окремий Compose, приватний manifest/preflight, серіалізований control,
60-секундна пауза та ранній restore guard. Локально: 17 runtime-контрактів,
11 Linux control-контрактів зі справжнім flock, 3 cleanup regressions,
28 DB-тестів, restore orchestration/preflight/identity, Ruff/provenance.
Ізольована репетиція до фінального коміту: 6 циклів, фактичний FIFO,
pending=0, без дублів/застарілих alerts; паузи перемикання/відкату
60,84/60,14 секунд. Перевірено буквальний env, persistent capture-only,
Online Backup поза томом та прибирання власних ресурсів.
PR [#77](https://github.com/ikstv/AvelRen-ORIGINAL/pull/77) злитий у
`857eb61e5a6c2ea35ca0c1648a55d89ecf7aa7fd`. Усі шість CI checks
`c655b2a2e928d480431f26508a122f69a3e87411` успішні; тестований merge-ref і
злитий main мають те саме дерево `10893f97d4f35630f973b4b9e120e494b20f5510`.
Усі шість checks самого merge-коміту `857eb61` теж успішні.
CI-репетиція: 6 FIFO циклів, pending=0, stopped duplicate відхилено до start,
cleanup PASS, паузи 61,18/60,15 секунд.

Після окремого GO власника шість runtime-операторських файлів встановлено
на сервер; їхні SHA-256 збігаються зі злитим main. Сам collector зберіг
image/source `0c62f54`, Device ID, DSN, network та volume. Managed контейнер
стартував 02.10 о 10:19:19 за Києвом; прийнято п'ять HTTP 200 циклів
10:19:21–10:23:21, по 38 observations, інтервали 60 секунд, derived без
помилок, pending=0. API/telemetry здорові, інші п'ять служб і legacy
checkout/override не змінилися. Перевірені DB/off-host та SQLite backups,
сумісний standalone збережено stopped для відкату. Деталі та контрольні
суми — у [датованому аудиті](PRODUCTION-AUDIT.md#collector-compose--02-жовтня-2026-року).
Відкат у production не виконувався; його ізольована репетиція пройшла в CI.
Ранній restore guard залишається **лише у source**: цей runtime-пакет не
встановлював `restore-production.sh` або повний restore engine.
Старий postgres-adopt не запускати з новою топологією до адаптації;
повний restore зі spool потребує окремого приймання. Android-збірка,
телефон та Play цим етапом не підтверджені. Наступні записи на сервері
потребують окремого конкретного GO; автооновлення й reboot не вмикалися.

## Черга collector: серверне приймання 02.10.2026

Код: PR [#74](https://github.com/ikstv/AvelRen-ORIGINAL/pull/74) і
[#75](https://github.com/ikstv/AvelRen-ORIGINAL/pull/75) злиті; робочий collector
встановлено з чистої `main` `0c62f543643b74a177ee56e5351cf518c1b9053d`.
CI цього merge-коміту успішний; локально на його дереві — 233 unit-тести.
Образ і SHA-256 архіву, backup та відкат зафіксовані в
[аудиті сервера](PRODUCTION-AUDIT.md#collector-spool--02-жовтня-2026-року).

Production: новий collector стартував 02.10 о 03:17:52 за Києвом. Прийнято
п'ять циклів 03:17:54–03:21:54: усі `200`, по 38 спостережень, інтервали
рівно 60 секунд, primary і derived завершені; `pending=0`, `last_error=null`.
API health/канал сповіщень/недоставлені сповіщення — `ok`, телеметрія бачить
collector `running`, перезапусків немає. Зроблено перевірений SQLite Online
Backup поза томом. Старий контейнер збережено зупиненим для відкату.

Ізольовану outage/restart/replay-репетицію виконано локально й у CI;
робочу БД для такого тесту не зупиняли. Інші п'ять служб, міграції, ролі БД,
ОС і Docker у цьому переході не змінювалися. Android-збірку, встановлення
на телефон, доставку конкретного push на телефон та Play не перевіряли:
цей етап не закриває їх. До переходу прав БД треба перенести Compose/runbook
керування на новий collector; сам перехід обмежених ролей потребує окремого GO.

## Черга collector під час недоступності БД (01.10.2026)

Source-кандидат у `codex/collector-durable-spool`: локальний SQLite WAL,
FIFO replay з read-back, режим `capture-only`, окремий постійний том і
[recovery-процедура](../ops/COLLECTOR-SPOOL.md). Стани приймання окремі:
код — PR ще не злитий; CI — перевірити на точному head; серверне
розгортання — не виконано; ізольована репетиція на сервері — не виконана;
Android/телефон — не змінювалися. Зелений unit-тест не доводить готовності
production. Перед використанням під час переходу прав БД потрібні окремий
GO, перевірений backup SQLite, `pending=0` після replay і доказ 60-секундного
ритму на реальному сервері.

Приймання 02.10.2026: review виявив і виправив збереження сирих помилок
та неефективне звільнення SQLite-сторінок. Локально: 233 unit-тести,
28 DB-тестів, provenance та Compose contract успішні. Репетиція daemon
відновила 7 циклів після двох SIGKILL і недоступності БД, підтвердила FIFO,
стійкий `capture-only` та відсутність дублів/запізнілих сповіщень.
CI фінального коміту ще потребує перевірки. Production і телефон не
оновлювалися; порядок підготовки й відкату додано в recovery-процедуру.

## Відсутня оцінка очікування — дизайн (30.09.2026)

[Issue #70](https://github.com/ikstv/AvelRen-ORIGINAL/issues/70) переносить
незавершену семантику legacy #111. Власник погодив напрям сумісного
розширення без переписування історії й зміни paused-політики.
[Специфікація](superpowers/specs/2026-09-30-wait-estimate-design.md)
погоджена власником у чаті 30.09.2026.
[План реалізації](superpowers/plans/2026-09-30-wait-estimate.md)
погоджений; реалізація почалась у чернетці PR #72.

| Етап | Стан |
| --- | --- |
| Контракт | Upgrade перед 015 та nullable internal status погоджені; nullable DDL і нормалізація helper реалізовані на d204056 без переписування історії |
| Product-код і міграція | Модель, INSERT/status, кандидат 015, `/workload.wait_estimate`, незалежні raw/hourly history, `forecast.count_points`, ETA alerts і сезонна quality зі спільним правилом; Android DTO ще не готовий. Не готово до merge/deploy |
| CI реалізації | На f77d813 локально 245 unit passed, Ruff/provenance успішні; API 66 passed, 12-тижневий EXPLAIN нового quality SQL 48,30 мс під timeout 5000 мс, old/new compressed restore PASS і recursive database tree 99 passed/1 очікуваний skip. Усі 7 workflows того head успішні. Backtest guard ведеться окремим зрізом нижче; Android і rollback старого runtime також не перевірені. Деталі у WAIT-ESTIMATE-IMPLEMENTATION.md |
| Backtest кількісної моделі | У draft-гілці інструмент має явні межі й відмовляється оцінювати holdout зі старих wait-фільтрованих `points`. Ізольований restore backup від 30.09 дав незалежні `count_hours`; на чотирьох КПП кандидат знизив MAE кількості відносно базисів у дев'яти повних вікнах на кожному. Проте вікна короткі й перекривні, а час піку на КПП 1, 29 і 6 гірший за seasonal. Це **не release gate** і не причина передчасного production deployment; деталі в `docs/forecast.md` |
| Серверне розгортання | Не виконано; потрібен окремий GO |
| Android-збірка | Не створена |
| Телефон | Не перевірено |
| Google Play | Не опубліковано |

Приймання: missing не стає справжнім 0; кількість авто й цикли
не втрачаються; count-only прогноз видимий; старий APK сумісний;
нова DTO працює і зі старим API. Детальні сценарії — у специфікації.
Точність кількісної моделі приймається окремо від цього виправлення.


## Supply-chain SBOM candidate (28.09.2026)

Source SBOM у main містить перевірку повного Python lock і Android Maven
залежностей. Окрема CI-гілка додає CycloneDX для зібраного, непублікованого
app candidate та зафіксованих TimescaleDB/Caddy образів. Її artifact — доказ
лише складу CI candidate; він не означає build, встановлення APK, розгортання
чи ідентичність production image. Приймання цього кроку вимагає успішного
GitHub CI та фактичної перевірки OS/Python package coverage у трьох файлах.

## Кандидат образу TimescaleDB (28.09.2026)

**Актуальний стан:** PR #60 злитий у main `ee31a7b`, усі 4 CI checks
merge-коміту успішні. Код і перевірки прийняті; розгортання, перевірка
реальної резервної копії й production upgrade не виконані.
Нижче збережено проміжний запис підготовки кандидата.

Після merge PR #59 (main `dc2b83e`, 4/4 CI успішні) у гілці
`codex/timescale-image-refresh` оновлено три pins до перевіреного
`2.30.1-pg16@sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9`:
production Compose, тестова БД та restore-репетиція. Старий образ у
upgrade-тесті збережено як baseline. PostgreSQL залишається 16.
Приймання нового head потребує повторного CI; зміна Compose у Git не є
розгортанням. На сервері образ, extension, ролі й міграції не змінювалися.
Перед production потрібні перевірка реальної копії, актуальних overrides,
план переходу всіх БД/template1 та відновлення старої копії при невдачі.
Не запускати старий образ над уже оновленим каталогом як «відкат».
Локально з новими pins: 22 DB-тести, повний restore/schema/API smoke та
перевірка cleanup після помилки пройшли. CI scopes (14 examples), provenance
і Android source/assets checks успішні; це не замінює CI точного head.

## Репетиція TimescaleDB (28.09.2026)

**Актуальний стан:** PR #59 злитий у main `dc2b83e`, 4/4 CI успішні;
PR #60 згодом оновив три pins у репозиторії до 2.30.1. Нижче — запис
етапу репетиції, коли pins іще лишалися на 2.17.2.

Гілка `codex/timescale-upgrade-rehearsal` додає ізольований перехід
2.17.2 → 2.30.1 на PostgreSQL 16 зі стисненими синтетичними даними.
[Сценарій і докази](TIMESCALE-UPGRADE-2026-09-28.md).
Production pins залишаються на 2.17.2. CI та merge фіксуються окремо;
сервер, APK, телефон і Play не змінювалися.

## Кандидат Caddy (28.09.2026)

**Актуальний стан:** PR #58 злитий у main `64511b8`, 4/4 CI успішні.
Серверне розгортання не виконане; нижче збережено запис підготовки.

У `codex/caddy-image-refresh` виправлено втрату довіреного IP-заголовка
та підготовлено Caddy 2.11.4 із digest pin. Локальні routing-тести на
2.9.1 і 2.11.4 пройшли з двома клієнтами; backend unit — 200 passed.
[Докази та обмеження](CADDY-UPDATE-2026-09-28.md).
CI/merge перевіряються окремо. Production deployment не виконаний;
APK, телефон і Play не змінювалися. Це не виправлення, уже доставлене користувачам.

## Кандидат Python runtime (28.09.2026)

**Актуальний стан:** PR #56 злитий у main `08a16a2`; фінальний head
`e6e5586` має 5/5 успішних CI checks. Source hardening і Python image
оновлення прийняті. Production deployment, перевірка фактичних overrides
і доступу UID10001 до bind mounts не виконані. Залишкові CVE збережені
в аудиті; merge не є підтвердженням їх повного усунення.
Нижче збережено проміжний запис етапів.

У гілці `codex/python-base-refresh` узгоджено оновлено Python base обох
Dockerfile. Локальні build/backend/DB/API/watchdog/restore перевірки пройшли;
приймання CVE **не завершене**, merge та розгортання поки не виконуються.
[Докази й залишки перевірки](PYTHON-BASE-UPDATE-2026-09-28.md).
CI head `bcbccda`: api/core/repository/watchdog пройшли; database впав
на Compose-контракті. SIGPIPE-причину виправлено з 4/4 локальними регресійними
тестами; head `f8b78bf` має 5/5 успішних CI checks. Baseline CVE-порівняння
показало покращення; системний review виявив залишкові SUID/NoNewPrivs=0.
Посилення прав п'яти Python-контейнерів реалізовано через NNP/cap_drop;
200 unit, 8/8 Compose регресій та фактичний runtime security guard пройшли.
Інтеграційна матриця DB/API/watchdog/snapshot/restore також пройшла локально;
CI нового head потрібно підтвердити окремо.
Production не змінювався;
Android-збірка, телефон і Play у цьому кроці не виконувалися.

## Попередній запис цільової версії

Цільова версія коду: **0.1.2, versionCode 5**. Це не підтвердження публікації.
Нові зміни живуть у PR #1. Реєстр доповнено виправленням Play Update R07.
Жодне встановлення на телефон або production-розгортання нового репозиторію
в цьому етапі не виконувалося. Старі усні підтвердження іншої збірки не
замінюють перевірки майбутнього APK.

## Production restore source readiness (28.09.2026)

У source підготовлено окремий manual fail-closed orchestrator, статичний
migration/role evidence gate, verified safety-snapshot receipt, ordinary
maintenance publisher і hardcoded production Timescale wrapper. Публічний
`ops/restore.sh` як і раніше приймає лише `restore_test`. Fake-command
контракти та ізольована Docker-репетиція не є deployment або дозволом на
production restore. Наступні три незалежні дозволи: read-only evidence capture,
deployment сценарію, а за реальної recovery-потреби — окремий GO на сам restore.

## Кандидат 0.1.2

Реліз `0.1.2` готується як наступний patch після опублікованого `0.1.1`.
Він містить виправлення self-lock на сервері (PR #37) та безпечний показ
несекретного ID інсталяції в Android під час `awaiting_approval` (PR #38).
Канонічні тексти для GitHub і Google Play — у
[RELEASE-0.1.2-DRAFT.md](RELEASE-0.1.2-DRAFT.md).

| ID | Що має отримати користувач | Стан | Що ще потрібно |
| --- | --- | --- | --- |
| S06 | Плашка автоматично проходить «Технічні роботи» → «Перезапуск сервера» → «Сервер онлайн» | Код злитий; API й host-скрипти розгорнуті; connected-test APK з чистої `main` пройшов усі три стани під час реального reboot 27.09 | Серверне приймання завершено; перед Play-релізом лишаються загальні release-перевірки |
| A06 | Несхвалена інсталяція не продовжує власне блокування через «Оновити стан»; вона показує ID для контрольованої звірки | Код #37/#38 злитий, Android CI зелений | Окремий production deployment #37, чистий APK/AAB 0.1.2, звірка ID, телефонний сценарій і явний дозвіл на публікацію |

## Реєстр змін

| ID | Що повинен отримати користувач | Код і перевірка | Що ще потрібно до телефона |
| --- | --- | --- | --- |
| R01 | Правдива плашка: онлайн, немає інтернету, сервер недоступний, дані застарілі | Android 0.1.1, ServerStatusTest; JVM і компіляція пройшли | APK із чистої main; перевірити переходи мережі, малий екран і великий шрифт |
| R02 | Жовта плашка підтверджених технічних робіт, точний плановий момент «Перезапуск сервера» та автоматичне повернення онлайн після нового boot | Android кешує `restarts_at`; `/status` не розкриває boot ID, але припиняє вікно після його зміни; реальний reboot показав усі три стани й новий boot ID | **Прийнято на production 27.09.2026**; повторний reboot не потрібен |
| R03 | Український щоденний звіт після 12:00, без щохвилинного шуму | Виправлено свіжість, невідомі значення, TTL і паралельні цикли; тести пройшли | Розгорнути сервер після окремого GO; перевірити реальну доставку на зареєстрований Admin, зокрема після офлайну |
| R04 | Історичний етап Admin до R12: одна підтверджена інсталяція, PIN і окреме 24-годинне блокування чужої інсталяції | Міграції 010–013 й API були розгорнуті після окремого GO; R12 додає нову глобальну політику | Не використовувати цей рядок як поточний опис блокування; актуальний контракт і приймання — у R12 |
| R05 | Налаштування, повна назва вкладки, нижній підпис розробника, версія на потрібних екранах | Перенесено зі старого main 0.1.1, збірка пройшла | Візуальна перевірка на телефоні; версія має збігатися з BuildConfig |
| R06 | Список головної не перекриває нижні панелі | Перенесені LazyColumn і нижні відступи | Перевірити довгий список, вузький екран, великий шрифт та одночасну плашку оновлення |
| R07 | Пропозиція оновити через Play і постійне нижнє нагадування | Реалізовано DOWNLOADED listener, кнопку completeUpdate, відновлення стану та повтор після помилки; [опис](PLAY-UPDATES.md) | Потрібна наскрізна перевірка через Play: завантаження, «Пізніше», повернення, встановлення, скасування та зникнення нагадування; сам JVM-тест не підтверджує встановлення |
| R08 | Український push про новий реліз, лише коли він доступний користувачу в Play | Android-обробник і [старий payload helper з трьома тестами](RELEASE-NOTICE-TRANSFER.md) перенесено | **Не готово:** sender і Play availability gate у старому helper не реалізовані; наскрізного й телефонного приймання немає. Масових push зараз немає |
| R09 | Правдивий текст про видалення даних через 90 днів | Текст в OnboardingScreen; production apply 0 із 0, щоденний таймер активний; `/privacy` опубліковано | Перевірити наступний запуск таймера й відображення тексту в фінальному APK |
| R10 | Повідомлення про майбутню платну Premium-підписку без старого блока «0.1.0 безкоштовна» | Текст присутній у перенесеному onboarding | Перечитати на телефоні весь екран, перевірити відсутність особистої пошти в цьому блоці |
| R11 | Повноекранний погодинний прогноз вибраного КПП до кінця дня за київським часом | Android UI/API, відбір київської дати та пошук максимуму; тестові сценарії перетину півночі взимку й улітку. Сервер лишається сезонним базисом; експериментальна корекція не прийнята | Android unit tests і debug assemble пройшли в локальному кандидатові. Повний серверний набір: 183 unit-тести пройшли, зокрема 3 тести прогнозу; SQL на реальній БД ще не перевірений. Перевірити сумісність із попередньою відповіддю API й реальну історію; телефонний сценарій ще не пройдено |

Для **всіх рядків R01–R11**: перевірка саме нової збірки на телефоні —
**не виконана**; публікація нових змін у Google Play — **не виконана**.
«Перенесено» не означає «виправлено всі старі питання». Повний перелік
старих гілок/PR та ops-матеріалів залишається в CONTROL-AUDIT.md.

## Порядок приймання

- [ ] Визначено склад релізу; кожен відкладений пункт явно погоджений власником.
- [ ] Усунуто відповідні блокери, включно з текстами privacy та Play Update.
- [ ] Перевірено чинність upload key і вимоги Play; ключі не потрапили в Git.
- [ ] Погоджено й виконано потрібні серверні зміни після backup та перевірок.
- [ ] Погоджені зміни злиті; збірка з чистого актуального main, без feature/preview-підміни.
- [ ] Збережено коміт, versionName/versionCode, SHA-256 та дату в dist/BUILD.txt.
- [ ] Після встановлення витягнуто base.apk і звірено SHA-256.
- [ ] На телефоні пройдено всі включені сценарії; дані та підписки збережені.
- [ ] Власник прийняв результат і український опис змін.
- [ ] Окремо дозволено публікацію; Play підтвердив доступність у потрібному треку.
- [ ] Лише після цього перевірено умови розсилання повідомлення про реліз.

Запис результату кожного сценарію: `ID | коміт | версія | SHA-256 | дата |
сценарій | результат | посилання на доказ`. Не записувати токени, PIN,
ключі підпису чи унікальні приватні ідентифікатори пристрою.

Серверний звіт не потребує нового APK для самого отримання `health` push,
але потребує серверного deployment і справного токена. Нова логіка плашки
потребує нового APK; R02 додатково потребує серверного сигналу. Саме тому
ці етапи не можна закрити однією позначкою «усе зелене».

## Уточнення після телефонної перевірки 24.09.2026

Уточнена вимога власника A04: у вкладці «Сервер» показувати кількість
усіх записів пристроїв, які ще зберігаються на сервері до очищення
після 90 днів неактивності, без обмеження останніми 24 годинами.
Показник агрегований і за уточненням власника відкритий усім; API не видає
ідентифікатори, токени чи інші записи пристроїв. Код API/Android уточнюється
після телефонного відгуку; CI, deployment endpoint і приймання на телефоні
ще окремі етапи.

U01–U04: додано меню налаштувань із жовтими рамками, сторінку «Про додаток»
з канонічними текстами 0.1.0/0.1.1, перехід до живої політики та вибірковий
показ посилання єЧерги. Опис 0.1.0 звірено з Play і GitHub. Код ще
потребує CI і візуального приймання на телефоні.

R11: нова правка змінює горизонт на наступні 24 години замість кінця дня. Формула не готова: на Чопі при вимірі 187 авто історичний прогноз дає 2–37. Випуск із твердженням про надійний AI-прогноз заблокований до перевірки моделі.
R01/моніторинг: прибрано рамку плашки, додано паралельне завантаження моніторингу, обмеження очікування й повтор після помилки.
Admin: production /api/admin/access повертає 404; зміна повідомлення не надає доступу. Потрібен окремий погоджений серверний етап.
Попередню main-збірку e6d768a (0.1.1/4) встановлено й перевірено SHA, запис у WORKLOG. Приймання всіх сценаріїв не завершено. Правки цієї гілки ще не встановлено; Play не опубліковано.

## Актуалізація 24.09.2026 після PR #13–#17

Наведені вище стани відображають ранні етапи. Поточний тестовий APK з чистої
`main` `08887ac` встановлено на телефон; витягнутий APK має той самий SHA-256,
що й файл збірки. Точні хеш, час і обсяг перевірок — у RELEASE-0.1.1-WORKLOG.md.

Admin-інсталяцію власника схвалено, успішний вхід він підтвердив. Після трьох
навмисних хибних спроб блокування до 25.09.2026 21:28 за Києвом очікуване.
Публічний `/api/active-devices` розгорнуто лише в API-контейнері після окремого
дозволу; HTTP 200 повернув 96 збережених пристроїв і `retention_days=90`.
Політику 90 днів опубліковано, а посилання в оновленому APK містить параметр
версії для обходу старого кешу. Телефонний огляд цих нових екранів ще триває.
Прогноз не має незалежного підтвердження точності, тест Play Update не проведено.
Фінальний AAB, GitHub tag/Release і Google Play 0.1.1 ще не опубліковані.

## R12 — Admin після перевстановлення за PIN (26.09.2026)

Чинну інсталяцію власника на production схвалено штатним механізмом. Після
введення PIN сервер підтвердив рівно один Admin-запис на цьому ID, наявний
FCM-токен, нуль хибних спроб і відсутність глобального блокування. Це
підтверджує поточний доступ, але не новий сценарій після перевстановлення.

| Етап | Стан | Критерій наступного кроку |
| --- | --- | --- |
| Код | Гілка `codex/admin-pin-rebind`: міграція 014, API, 30-денний спільний lock, Android-контракт і перевірка 4 ASCII цифр у PIN-полі | Злити лише після перевірок і review |
| CI | GitHub Actions 6/6 пройшли 26.09.2026 на `f3e11f0`: android, api, core, database з restore-репетицією, repository, watchdog | Перед merge звірити CI з фінальним кодовим комітом |
| Серверне розгортання | Міграцію 014 застосовано о 20:03 UTC; о 20:27 UTC розгорнуто окремий API-образ із трьома зміненими модулями. Health 200, Admin route 401 без автентифікації, роль БД `avelren_api`; реальний PIN-вхід на новій інсталяції ще не перевірено | Android-збірка з погодженого коміту й телефонний сценарій з реальним PIN без запису PIN у журнал |
| Android-збірка | Новий APK/AAB для R12 не створено | Чиста збірка з погодженого коміту, версія й SHA-256 |
| Телефон | PIN-only після перевстановлення не перевірено | Записати коміт, версію, SHA-256 APK, дату й результат сценарію без PIN або ID |
| Google Play | Не опубліковано | Окремий дозвіл і перевірка доступності |

Після перевстановлення зникає також інсталяційний ID, до якого прив'язані
підписки. Аудит 26.09.2026 виявив три старі активні підписки на КПП 17 без
FCM-токенів і нуль підписок на чинному Admin-ID. Відновлення Admin за PIN саме
по собі не переносить підписки; приймання на телефоні має окремо перевірити
наявність потрібних підписок і доставку push.

## Реальне відновлення backup — приймання 02.10.2026

Код exact main `857eb61e` відновив реальний backup із міграціями 001–014
локально та на окремому серверному стенді. Native schema verify/API smoke
успішні; [доказ і очищення](audits/RESTORE-REAL-BACKUP-2026-10-02.md).
Серверне приймання цього етапу — лише disposable rehearsal. Старі host
restore-файли не замінені, issue #41 ще відкрита; live adoption/повний restore
зі spool не виконані. Нового APK, телефонної перевірки й публікації Play немає.

## Restore runtime — серверне приймання 02.10.2026 о 11:29

Попередній блок описує перший стенд до встановлення. Тепер чотири host
restore-сценарії узгоджено з перевіреним main 857eb61e після окремого GO.
Повторний backup restore через фактично встановлені CLI/engine/verifier,
schema/API smoke, hashes/rollback backups та cleanup успішні.
[Доказ](audits/RESTORE-REAL-BACKUP-2026-10-02.md#встановлений-runtime--приймання-о-1129-за-києвом).
Критерії #41 виконано. Production restore зі spool лишається заблокованим;
adoption живої БД, APK/телефон/Play не прийняті цим етапом.


## R18 — Експериментальний моніторинг напливів (02.10.2026)

| Етап | Стан |
| --- | --- |
| Код | Реалізація в `codex/experimental-surge-monitor`: frozen модель, залежність PR #72, схема 016, optional gate, права, епізоди, worker, API та стійка FCM-доставка, Android API/local ACK, UI та голосовий сервіс, runtime й повний синтетичний сценарій; п’ять review дефектів виправлено; пакет установлення ще в роботі |
| Локальні перевірки | 339 unit, 53 database, 76 API, 23 surge integration, 164 Android JVM, офлайн UI на емуляторі, синтетичний restore та allowlist пройшли; не означає CI |
| CI | Не запускався для нової гілки |
| Сервер | Не розгорнуто; блокер: Timescale2.17.2 не підтримує015 (відтворено локально); потрібен окремий ручний upgrade БД і конкретний дозвіл на пакет/міграції/роль/служби та відкат |
| Android-збірка | Нового APK/AAB немає |
| Телефон | Голос, ACK, offline/reboot й екран не перевірено |
| GitHub Release | Опис та артефакти ще не готові; має передувати Play |
| Google Play | Не опубліковано |

99% precision і recall не підтверджені. Вимога до екрана — постійний напис
«Функція в розробці» реалізовано й перевірено в loading/error/scroll на емуляторі; телефон ще не перевірено. У реліз включаємо весь перевірений реєстр змін.

## Звірка кандидата 1.0.3 — 02.10.2026

PR #80: head `11f4f88` пройшов усі 8 CI checks, включно з БД (19 хв 9 с).
Наступна Android-правка завершує погоджений wait DTO/UI-контракт: відсутня
оцінка не показується як 0, count-only точки відображаються незалежно,
порожні count_points та null ETA не підміняються legacy значеннями.
Локальні JVM/compile/lint пройшли; новий коміт потребує свого CI.

Кандидат Android — 1.0.3 / versionCode 6. Play Console «Усі набори App Bundle»:
перевірено всі 5 завантажених артефактів, найвищий code 5 / 0.1.2.
Історію приміток доповнено канонічним текстом 1.0.3. Підписаний APK/AAB,
телефонне приймання, GitHub Release та Play ще не виконані.

Ручний серверний план готується: потрібні фактична копія БД, ізольоване
приймання upgrade та готовий immutable пакет із відкатом, потім окремий GO.
Не переносити припущення про Timescale у template1 із синтетичного стенда:
свіжий аудит виявив extension лише у avelren. ОС/Docker/reboot не змінюються.
R12 PIN після перевстановлення, плашка, доставка push і жіночий голос
мають свої сценарії на телефоні; лише новий екран не закриває весь реєстр.


Голос: погоджені короткі назви всіх 38 черг, зі збереженням порожніх вантажівок/товарів 1–24/менших вагових категорій. Див. docs/CHECKPOINT-SPEECH.md. Код Android і серверного тексту перевіряється окремо; це не розширення підтримки прогнозної моделі чи production-запис. CI/merge/Play не виконані.


02.10.2026, підготовка 1.0.3: власник погоджує опис разом з агентом; чернетка у dist/RELEASE-1.0.3-DRAFT.txt, текст коротких приміток у v1.0.3.uk.txt. Відкритий PR #80 має старий head 11f4f885 і 8 успішних checks; телефонний UI і нові голосові назви ще не інтегровані у цей head. Публічний /api/surge/checkpoints зараз HTTP 404, /api/status HTTP 200; реальний автоматичний прогноз на телефоні не прийнятий. До GitHub/Play потрібні узгоджений код/CI, конкретний production-пакет з окремим дозволом, підписаний APK/AAB і наскрізний телефонний сценарій. Опис ще не схвалений; реліз не опубліковано.

## Об’єднаний UI та реальні підписки — 02.10.2026

Походження й поведінка: [інтеграція 1.0.3](ANDROID-1.0.3-INTEGRATION.md).
Локально: 188 JVM-тестів, assembleDebug/lintDebug і 78 API-тестів успішні.
Ліміт 5 захищено також для паралельних запитів. UI працює через серверний
репозиторій; голос через гучність сповіщень, без перемикача «без голосу».
Версія кандидата 1.0.3 / 6. Новий код потребує окремого CI.
На production цей код ще не встановлено, новий APK на телефоні не прийнятий,
підписаний AAB/GitHub Release/Play не виконані. Опис редагує власник.

## R18 та1.0.3: фактичне серверне приймання — 03.10.2026

Докази й причина packaging failure: [серверний audit](SURGE-INSTALLED-MODEL-FIX-2026-10-03.md).

| Етап | Актуальний стан |
| --- | --- |
| Основний код | PR80 злитий у main aecbfa66; installed-model fix у новій гілці, ще не main |
| CI | Усі8 exact aecbfa66 SUCCESS; виправлення потребує свого CI |
| БД | Погоджений Timescale2.30.1, міграції015/016, backup/worker ACL прийняті |
| Збір/дані | Cold copy та encrypted backups перевірені; історія/агрегати/стиснення збережені; pending0, п'ять природних60s циклів без помилок |
| Прогноз | НЕ прийнято; SURGE_ENABLED=false, worker stopped через відсутній JSON у installed wheel |
| Recovery | API/collector/канал сповіщень ok; timersactive/enabled; власна плашка і plaintext backup прибрані |
| Android-збірка/телефон | Фінальні1.0.3 APK/AAB, FCM/голос/ACK/offline не прийняті |
| GitHub Release/Play | Не опубліковано; опис ще редагує власник |

Наступне: review/CI installed-model fix, чистий main image та окремий GO
на application-only пакет. Повторний DB upgrade не потрібен. Точність99%
не підтверджено. Cold rollback зберігається, після writers не застосовується.

## Уточнення 13.10: узгоджений backup PostgreSQL + SQLite

Уточнення 14.10: source-виправлення повертає перевірену стару політику rclone:
`--retries 3 --low-level-retries 10 --timeout 5m`. П'ять хвилин — ліміт
бездіяльності I/O, а не новий бюджет кожного виклику: спільний post-resume
deadline 900 секунд і пауза записувача 720+180 секунд незмінні. Журнал старого
backup підтвердив успіх 14.10 о03:23:29 UTC; окремий read-only checksum зі
старими параметрами пройшов за37,723с. Це не доводить, що лише retry-політика
спричинила попередній збій: доступність Drive-квоти між спробами змінювалася.
Source/контракти не замінюють CI, встановлення, нову off-host пару та restore.

[Source-кандидат і package prerequisites](audits/PAIRED-BACKUP-SOURCE-2026-10-13.md)
мають native helper, owned recovery, crypt manifest-last publication і paired
restore. Окремі acceptance gates: local source evidence → exact-head hosted
CI/review → merge → конкретний пакет/production GO → нова real off-host pair,
download/decrypt/hash/SQL+SQLite restore/drain та виміряні RPO/RTO. Source
daemon fixture не є installed production або real-pair proof; deployment,
Android build/phone/Play лишаються окремими етапами. Default sql-only збережено.

## Мінімальний legacy alert hotfix — 15.10.2026

Незавершений ETA-only runtime доповнено bounded collector overlay, щоб разом
виправити пропущений прямий перетин і не завершувати threshold/ETA alert до
ручного видалення. Старий writer та формат ACK збережені.
[Походження, exact image, локальні DB/restore/rollback докази та межі](audits/ETA-LEGACY-HOTFIX-2026-10-14.md).
[Новий source-контракт і TDD evidence](audits/LEGACY-ALERT-HOTFIX-SOURCE-2026-10-15.md).
Попередній image digest засвідчує лише ETA-only рецепт і не є кандидатом для
оновленого artifact. Для оновленого artifact зібрано exact candidate
`sha256:40219d6c8ceee5a862382dbb62fe3df06181a20488635d47c5a965512eda9a72`
із source `4503477f334c72ab05409bf241779592d2fe0bf1`; 68 installed files/config/base
layers звірено, змінені лише eta.py та collector.py. Exact-head CI успішний.
DB/restore/rollback, deployment, phone acceptance та публікація 1.0.4/Play
ще не підтверджені.
