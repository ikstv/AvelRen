# Контракт відсутньої оцінки очікування — план реалізації

> **Для виконавця:** обов'язкова навичка — superpowers:executing-plans для самостійного виконання в цьому чаті або superpowers:subagent-driven-development лише після вибору власником делегування. Кроки відмічаються чекбоксами. Цей план ще потребує перегляду власника перед кодом.

**Мета:** зберігати missing окремо від справжнього 0 та показувати кількісний прогноз незалежно від wait, без поломки старого APK.

**Архітектура:** одна додаткова ознака у observations, спільне правило читання оцінок, additive API та Android fallback. Чинні числові поля й legacy-проєкції зберігаються; історичні observations не переписуються. Міграція передує новим читачам/collector.

**Стек:** Python/Pydantic, psycopg, PostgreSQL 16/TimescaleDB, FastAPI, Kotlin/Compose/kotlinx.serialization, pytest, Gradle, Docker Compose.

**Специфікація:** [2026-09-30-wait-estimate-design.md](../specs/2026-09-30-wait-estimate-design.md), погоджена власником у чаті 30.09.2026. Пов'язано: [#70](https://github.com/ikstv/AvelRen-ORIGINAL/issues/70), legacy #111.

## Загальні обмеження

- Тільки collector; 60 секунд між початками циклів; кожен цикл записується; тести не опитують upstream.
- Стани: reported, missing, legacy_unknown. Missing зберігає технічний 0, але канонічна оцінка null.
- Reported приймає невід'ємний JSON integer, включно з 0; bool, дробове, рядок і від'ємне — parse-помилка.
- Legacy_unknown: позитивне число придатне з явною позначкою; 0 або від'ємне — канонічна оцінка null. Ніякого backfill.
- Позитивний paused wait зберігає чинну політику; paused із нульовим wait не дає ETA.
- Forecast: 12 тижнів; свіжий вимір не старший 3 хвилин; чинні readiness і MIN_NEIGHBORS; wait samples та calibration_samples різні.
- Старі поля зберігають типи; count_points=null/відсутній означає fallback, [] — новий контракт без точок.
- Застосовані міграції незмінні; migration pin, ролі БД, образи та production не змінювати без окремого GO.
- Українські документація/коміти; чужі зміни зберігати; APK лише з чистої main та pull-back SHA-256.

## Фокус review

1. У черзі є авто, але upstream дав справжній 0: нова ознака не повинна знову приховати його евристикою (задачі 1, 3).
2. Стара стиснена історія містить нулі/від'ємні значення: нові constraints не переписують або не відкидають legacy-рядки (задачі 2, 5).
3. Після відкату старий collector пише без статусу: default legacy_unknown, не reported; старий gate не повинен мовчки пропускати несумісність (задачі 2, 5).
4. Новий API дав [] count_points, але legacy points непорожній: Android не оживляє старий прогноз (задача 4).
5. Немає wait-слота, є кількісна модель; DST і stale anchor: count-only показується лише за власних gates та rolling 24h (задачі 3, 4).

## Підготовка виконання

- [ ] Прочитати AGENTS.md, CONTRIBUTING.md, INTEGRATION.md, MIGRATION.md, відповідний датований PRODUCTION-AUDIT і специфікацію.
- [ ] Створити або повторно використати чистий ізольований worktree за using-git-worktrees; не працювати поверх dirty checkout. Робоча гілка codex/wait-estimate-contract.
- [ ] Зафіксувати base SHA і список міграцій main. На перевіреному зрізі остання 014; якщо main змінився, перед новим SQL вибрати наступний номер і синхронно оновити згадки в плані/контракті.
- [ ] Використати тести зі штатних README та ізольований Docker; не копіювати production .env. Baseline-збої відокремити від нових.
- [ ] Звірити наявні HTTP-фікстури щодо типу wait_time: якщо strict typing відкидає вже відомий штатний формат, зупинитися для перегляду цього конкретного правила, не змінювати upstream.

## Задача 1: парсинг та спільна семантика

**Файли:** створити services/backend/src/avelren/wait_estimate.py і tests/unit/test_wait_estimate.py; змінити services/backend/src/avelren/models.py, tests/unit/test_echerha.py. Далі шляхи tests відносно services/backend.

**Інтерфейси:**

- WorkloadItem.wait_time: int | None = Field(default=None, strict=True, ge=0).
- WorkloadItem.wait_time_status: read-only property str; None → missing, число → reported. Вхідне стороннє поле статусу не має підміняти цю властивість.
- usable_wait_seconds(seconds: int, status: str | None) -> int | None: reported невід'ємне → число; legacy_unknown/внутрішній NULL позитивне → число; решта → None; невідомий текстовий статус → None.
- measured_wait(at: datetime, seconds: int, status: str | None, is_paused: bool) -> dict: внутрішній NULL нормалізується в публічний legacy_unknown; seconds за usable_wait_seconds; ETA null при непридатній оцінці або paused/0.

- [ ] Написати параметризовані test_workload_preserves_missing_and_zero та test_workload_rejects_invalid_wait. Assertions: omitted/null → (None, missing); 0 → (0, reported); 3600 → (3600, reported); True/1.5/"3600"/-1 → ValidationError.
- [ ] Додати test_wait_read_policy: usable_wait_seconds(0,"reported")==0; (0,"missing")==None; (0,"legacy_unknown")==None; (3600,"legacy_unknown")==3600; (-1,"legacy_unknown")==None.
- [ ] Додати test_measured_wait_eta: reported0/nonpaused → at; reported0/paused → None; missing → None; reported3600/paused → at+3600s. Зафіксувати, що vehicles не є аргументом.
- [ ] Запустити python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_wait_estimate.py -q. Очікується змістовний FAIL до реалізації, не помилка середовища.
- [ ] Реалізувати мінімальні модель/функції. Через MockTransport test_fetch_missing_wait_keeps_response перевірити, що null/omitted не відхиляють увесь цикл, а некоректний тип записує FetchResult.error з parse і response=None.
- [ ] Повторити тести та весь unit suite; потрібні 0 failures. Оновити CORE-PROVENANCE лише штатним способом, зберігаючи source SHA та історію.
- [ ] Коміт: «fix: розрізняти відсутню оцінку та нуль у моделі джерела».

## Задача 2: міграція та збереження

Уточнення власника 30.09.2026: upgrade rehearsal застосовує 001–014
на 2.17.2; після перевіреного image/extension upgrade до 2.30.1 — 015.
Fingerprint історичних п'яти полів і журнал 001–014 мають лишитися
незмінними; новий статус перевіряється окремо. Обидва backup/restore
етапи зберігаються. Production upgrade потребує окремого GO.

**Файли:** створити db/migrations/015_wait_time_status.sql (лише якщо 015 досі вільна), tests/database/test_wait_time_status.py; змінити db.py, schema_verify.py, відповідні tests/database/test_migrations.py, test_permissions.py, test_pipeline.py, docs/DB-PROVENANCE.json та CORE-PROVENANCE.json.

**Інтерфейси:** observations.wait_time_status nullable text, ADD без DEFAULT;
SET DEFAULT 'legacy_unknown' тільки для майбутніх INSERT. Історичний NULL
нормалізується як legacy_unknown у SQL/helper, не переписується.
INSERT записує (time, checkpoint_id, wait_time_seconds, vehicles_in_queue,
is_paused, wait_time_status); відсутній source wait мапиться на 0/missing.
insert_observations зберігає сигнатуру й кількість рядків.

- [ ] Написати test_status_migration_preserves_compressed_legacy: окрема синтетична БД зі схемою до 015, compressed chunk із wait 0/3600/-1. Після міграції старі поля незмінні; фізичні статуси NULL без atthasmissing, канонічні legacy_unknown. Не застосовувати SQL до production.
- [ ] Написати test_status_checks_and_old_insert: INSERT без статусу дає legacy_unknown; missing із seconds!=0 та reported із seconds<0 відхиляються; невідомий статус відхиляється; reported0 та legacy_unknown/-1 дозволені.
- [ ] Запустити bash scripts/test_database.sh database; зафіксувати FAIL нових assertions, не існуючих baseline-перевірок.
- [ ] Додати тільки нову міграцію: CHECK дозволених статусів, missing/0 і reported/nonnegative. Не змінювати continuous aggregate 001, compression policy або retention. Оновити version-annotated schema contract, щоб новий runtime відмовляв без потрібної колонки.
- [ ] В insert_observations зберегти кожен вимір і явний статус; test_missing_wait_pipeline_keeps_count_and_run перевіряє vehicles=80, seconds=0, status=missing, успішний collector_runs та unchanged primary/derived transaction policy.
- [ ] Повторити database suite. Перевірити backup SELECT/pg_dump, old insert, повторне застосування й незмінні checksum 001–014. Якщо DDL не працює на compressed chunks — STOP, повернути специфікацію на перегляд; не декомпресувати історію як прихований workaround.
- [ ] Коміт: «fix: зберігати статус оцінки в спостереженнях».

## Задача 3: API, ETA та незалежні точки прогнозу

**Файли:** змінити api.py, eta.py, forecast.py, tests/unit/test_forecast_bounds.py; створити tests/database/api/test_wait_estimate_contract.py; розширити tests/database/api/test_forecast_history.py та tests/unit/test_forecast_quality.py; provenance API/CORE і docs/forecast.md.

**Інтерфейси:** workload.wait_estimate=measured_wait(...); raw history додає wait_time_status/wait_estimate_seconds; hourly додає count_hours і wait_hours. forecast додає count_points, зберігає legacy points та їх числові поля. Нових upstream-запитів немає.

- [ ] Написати test_workload_additive_contract: для missing/legacy0 новий seconds і ETA null, старий wait_time_seconds int; reported0/nonpaused/vehicles80 дає seconds0 та новий ETA=at, legacy entry_eta лишається null; paused3600 зберігає обидва чинні правила.
- [ ] Написати test_history_separates_count_and_wait_samples: в одному слоти 4 записи reported0, missing0, legacy0, legacy3600. count samples=4; wait samples=2, avg_wait_seconds=1800; raw містить усі 4. Legacy points зберігає старі ключі й типи.
- [ ] Написати test_count_points_without_wait_slot: достатня кількісна історія/свіжий anchor і жодної придатної wait-історії → count_points непорожній, кожен wait_estimate=None, points=[].
- [ ] Додати stale/collecting/недостатні MIN_NEIGHBORS → count_points=[], fresh_measurement_required за чинним правилом; reported0 придатний wait-слот не втрачається; samples wait і calibration_samples count перевіряються окремо.
- [ ] Запустити bash scripts/test_database.sh api і unit forecast tests; зафіксувати очікувані FAIL.
- [ ] Реалізувати SQL-проєкції статусу для нових wait-читаючих шляхів. Кількісні агрегати й predict_counts не фільтрувати wait-умовою. Legacy API JSON проєкцію відокремити; не підставляти фальшиві wait0 у старі forecast points.
- [ ] Оновити ETA alerts через спільне правило: missing не спрацьовує, reported0/nonpaused може, paused0 не може; не використовувати прогноз як measurement.
- [ ] Оновити seasonal evaluate на придатні wait-дані, явно залишивши method=seasonal_naive. Test heldout7days, 12week bound, MAE0 та leakage; backtest кількісної моделі не називати seasonal MAE.
- [ ] Повторити api/unit suites; EXPLAIN (ANALYZE, BUFFERS) на синтетичній 12-тижневій історії зафіксувати до/після і перевірити statement timeout. Production SELECT/EXPLAIN окремо, якщо буде потрібний аудит.
- [ ] Коміт: «fix: відокремити кількісний прогноз від оцінки очікування».

## Задача 4: Android DTO і показ

**Файли:** змінити apps/android/app/src/main/java/ua/avelren/app/data/Api.kt, ForecastPresentation.kt, ui/AvelRenScreen.kt; створити data/WaitPresentation.kt; створити src/test/java/ua/avelren/app/data/WaitEstimateContractTest.kt і WaitPresentationTest.kt, розширити ForecastPresentationTest.kt. Оновити docs/ANDROID-PROVENANCE.json.

**Інтерфейси:** Api.WaitEstimate(status: String, seconds: Int?, entry_eta: String?); Api.ForecastWaitEstimate(seconds_low: Int, seconds_expected: Int, seconds_high: Int, samples: Int); Api.CountForecastPoint(time: String, vehicles_low: Int, vehicles_expected: Int, vehicles_high: Int, calibration_samples: Int, wait_estimate: ForecastWaitEstimate?).
У Api.Forecast: count_points: List<CountForecastPoint>? = null.
Нові workload поля nullable з default=null; legacy DTO незмінні.
Api.CountHistoryHour(time, avg_vehicles: Double, samples: Int) та Api.WaitHistoryHour(time, avg_wait_seconds: Double, max_wait_seconds: Int, samples: Int), обидва масиви History nullable за аналогічним правилом fallback.

ForecastPresentation.displayPoints(forecast: Api.Forecast) -> List<Api.CountForecastPoint>: повернути count_points, якщо не null; інакше адаптувати points, без твердження про нову калібрацію (для адаптера calibration_samples=0 як відсутність нового доказу, UI не називає його фактичним числом сусідів).
Нові функції next24CountHours(points: List<Api.CountForecastPoint>, now: Instant): List<Api.CountForecastPoint> та countPeak(points: List<Api.CountForecastPoint>): Api.CountForecastPoint? зберігають чинні часові/peak правила; старі helpers лишаються для legacy tests.
WaitPresentation.label(estimate: Api.WaitEstimate?): String?: null повертає null для legacy UI fallback; missing/legacy0 повертають текст відсутності; reported0 повертає текст нуля; позитивне число форматується в дні/год/хв, legacy_unknown має підпис «За історичними даними». Невідомий майбутній status показує відсутність підтвердженої оцінки, а не reported; додати це до testWaitLabels.

- [ ] Написати testNewAndLegacyJsonDecode: старий JSON без нових полів декодується; новий з missing/null декодується; зафіксована стара DTO з ignoreUnknownKeys декодує новий JSON.
- [ ] Написати testEmptyCountPointsDoesNotFallback: count_points=[] та непорожній points → displayPoints порожній; count_points=null → legacy fallback.
- [ ] Написати testWaitLabels: missing або legacy0 → «Оцінка очікування відсутня»; reported0 → «0 хв очікування»; legacy3600 має «За історичними даними»; відсутній новий об'єкт → чинний legacy UI.
- [ ] Розширити ForecastPresentationTest: count-only, winter/summer midnight, DST, malformed timestamp, дублі й peak. Зберегти rolling 24 elapsed hours.
- [ ] Запустити з apps/android: bash gradlew -PavelrenUiPreview=true :app:testDebugUnitTest :app:compileDebugKotlin --no-daemon --max-workers=2; до реалізації очікуються нові FAIL/відсутні нові DTO. На Windows використовувати .\gradlew.bat.
- [ ] Реалізувати DTO, pure presentation helpers і використання в UI. Новий ETA лише з wait_estimate; null нового ETA не заміняти legacy entry_eta. ROAD SIGN/інші екрани не переробляти.
- [ ] Повторити тести/компіляцію. Це не APK/телефон/Play.
- [ ] Коміт: «fix: показувати відсутню оцінку та незалежний прогноз авто».

## Задача 5: backup/restore, відкат та готовність

**Файли:** розширити ops/restore-integration-test.sh, services/backend/tests/database/test_wait_time_status.py, tests/unit/test_schema_gate.py; створити ops/wait-estimate-rollback-contract-test.sh; змінити scripts/verify_ci_scopes.py і відповідні workflows лише якщо нові шляхи не охоплені. Оновити docs/RELEASE-READINESS.md, MIGRATION-REMAINING.md, forecast.md та новий docs/WAIT-ESTIMATE-DEPLOYMENT-GATE.md.

**Інтерфейси:** один ізольований restore/rollback gate, який перевіряє schema journal, status values, ownership і API; жодних production volumes, інсталяційних токенів або upstream.
Новий rollback скрипт бере старі модулі з зафіксованого base SHA цієї гілки, не latest; базовий SHA записується до скрипта під час задачі. Перевірка реальних production образів залишається окремою перед deployment.

- [ ] Написати restore assertions для reported0, missing0, legacy0/3600 у compressed chunk: після dump/restore значення та кількість незмінні, backup-роль read-only, Timescale pre/post hooks і cleanup після помилки працюють.
- [ ] Написати rollback assertions: старий insert без статусу працює; виконати старий schema gate/schema verifier та legacy API smoke на новій схемі. Окремо newest-code/old-schema відхиляється до корисної роботи. Якщо old-schema verifier відхиляє додану колонку, скрипт повертає nonzero і документує, що rollback образів заблокований; не послаблювати gate.
- [ ] Написати offline encrypted-artifact check для синтетичного dump: encrypt/decrypt через ізольований локальний rclone crypt remote з одноразовими ключами поза Git, потім SHA-256/restore. Ні Drive, ні production rclone.conf не використовуються. Це доповнення штатного restore test, не доказ реального cloud backup.
- [ ] Запустити тести до зміни restore assertions/fixture; зафіксувати відсутній новий контракт як FAIL, потім внести мінімальні зміни.
- [ ] Прогнати unit/Ruff, bash scripts/test_database.sh database, api, watchdog; bash ops/restore-integration-test.sh; bash ops/wait-estimate-rollback-contract-test.sh; python scripts/verify_core_provenance.py; python scripts/verify_android.py; python scripts/verify_ci_scopes.py.
- [ ] Запустити повний Android unit/compile та GitHub CI на точному head; review дифу проти специфікації, секретів, migration checksums, provenance. Докази — команди, SHA, counts/results; не заміняти їх словом «зелено».
- [ ] У DEPLOYMENT-GATE записати порядок: свіжа read-only звірка активних образів/Timescale/ролей/pin/override → успішна ізольована репетиція актуальних версій → погоджені schema/runtime зміни → окремий GO → міграція → нові сервіси → health і нові 60s cycles → приймання.
- [ ] Відкат: до COMMIT міграції — штатний transaction rollback; після міграції — лише доведений старий runtime над additive схемою, без DROP колонки або стирання журналу. Якщо gate/DDL не пройшов, deployment не пропонувати; backup restore потребує окремого погодження як відновлення, не автоматичний крок.
- [ ] Оновити реєстри: код/CI окремо; server, clean-main APK, pull-back SHA, телефон і Play лишити невиконаними до їх власних доказів.
- [ ] Коміт: «test: перевірити restore та сумісність відкату wait-контракту».

## Вихідні умови

Після задач 1–5 PR реалізації може бути готовий до review/merge, але
production не змінюється автоматично. Старі #70/#111 не закривати лише
через план або unit CI; критерії фактичного приймання ведуться окремо.
Перший виконуваний маленький крок після погодження плану — задача 1.

## Самоперевірка плану

Coverage: parsing/invalid cycle → 1; DDL/status/persistence → 2;
history/ETA/forecast/quality → 3; compatibility/UI/DST → 4;
compressed restore/encryption/rollback/CI/provenance/readiness → 5.
Немає припущення, що compressed DDL, production-версія або старий
runtime rollback вже перевірені. Ці блокери мають право зупинити
реалізацію для корекції специфікації.
