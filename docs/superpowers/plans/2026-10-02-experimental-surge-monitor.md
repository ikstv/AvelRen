# Експериментальний прогноз напливів: план реалізації

> Для виконавця: обов'язкова навичка `superpowers:executing-plans`.
> Реалізація власноруч у цій сесії, як раніше обрав власник;
> один незалежний огляд усієї гілки після перевірок.

**Мета:** увімкнений експериментальний прогноз і фактичний моніторинг
кількох КПП, із голосом, ACK та написом «Функція в розробці».

**Архітектура:** окремий worker читає збережені спостереження й керує
епізодами. API керує підписками; notifier доставляє стійкі спроби FCM.
Android відображає стан, підтверджує локально та озвучує через короткий
foreground service. Collector не залежить від цього модуля.

**Технології:** чинні Python/FastAPI/psycopg, PostgreSQL/TimescaleDB,
FCM, Kotlin/Compose/WorkManager/TextToSpeech; нових ML-залежностей немає.

**Специфікація:**
[погоджений дизайн](../specs/2026-10-02-experimental-surge-monitor-design.md).
Власник погодив дизайн 02.10.2026. Власник дозволив почати реалізацію та додати всі готові зміни до релізу 02.10.2026.

## Загальні обмеження

- Прогноз — експериментальний; 99% за обома показниками не підтверджено.
- Фактичний поріг: чисте +20 авто за п'ять хвилин, не валові реєстрації.
- Прогноз: 1–24 години, раз на годину, лише ID 1/6/17/29.
- Frozen SHA-256: `331320e05c62ec027744dab387ba40c859a9c1070821afc3910f4358bb3b90bb`.
- Поріг балу: `0.8789563370805348`; відсоток імовірності не показується.
- Свіжість: до трьох хвилин; минулі 60 хв без gap >90s;
  минулі 120/240 хв із coverage >=95%, gap <=300s; endpoint tolerance 30s.
- Прогноз expires через 65 хв без придатного оновлення; факт — через
  30 хв без qualifying-вікна. Втрата свіжості закриває подію.
- Нагадування через 300 секунд до ACK/expiry; дубль attempt_id не озвучується.
- Напис «Функція в розробці» видимий внизу екрана в усіх станах.
- Точні голосові фрази дизайну; кнопки «Прослухати приклад» немає.
- Лише collector опитує єЧергу, раз на 60 секунд, із незмінним Device ID.
- Міграції незмінні; 015 зайнята PR #72, нова міграція — 016.
- Production pin і перехід прав БД не змінюються побічно.
- Кожний production-запис — лише після конкретного дозволу власника.
- APK для власника — із чистої актуальної main; коміт/версія/SHA-256
  та сценарій телефона фіксуються окремо від CI.
- Порядок власника: опис та GitHub Release, потім Google Play Console.
  Названа ціль — 1.0.3; на GitHub є окрема чернетка 0.1.3.
  Перед зміною номера звірити відповідь власника на review плану.

## Особлива увага під час огляду

1. Старий APK і повторна реєстрація: новий push не запускає legacy
   threshold; capability передається і при створенні, і при оновленні токена.
2. Втрачена відповідь FCM після прийняття: повтор використовує той самий
   attempt_id; наступне заплановане нагадування має новий ID.
3. ACK без мережі, kill/reboot телефона: локальна відмітка стійка,
   пізній push не повертає голос; серверний ACK повторюється.
4. Одночасний факт і прогноз, DST та replay: прогноз не виникає під час
   активного факту; час абсолютний, старі спостереження не озвучуються.
5. Блокування каналу, звичайний FCM і відсутність uk-TTS: немає обходу
   системних обмежень, завислого service або пізнього озвучення.

Кожний пункт має конкретні перевірки в задачах нижче.

## Структура файлів

Backend, від кореня `services/backend/src/avelren/`:

- `surge_model.py` — чисті ознаки та frozen inference.
- `models/surge_24h_v1.json` — параметри, версія й походження.
- `surge_events.py` — чисті переходи епізодів і строки актуальності.
- `surge_store.py` — транзакції станів, підписок і доставка/ACK.
- `surge_worker.py` — планування хвилинних та годинних операцій.
- `surge_api.py` — нові маршрути; `surge_schemas.py` — DTO.
- `surge_delivery.py` — нові FCM-спроби, підключення до notifier.
- `surge_text.py` — українські фрази й форми назв КПП.

Android, від кореня `apps/android/app/src/main/java/ua/avelren/app/`:

- `data/SurgeApi.kt`, `data/SurgeRepository.kt` — DTO й стан екрана.
- `ui/SurgeMonitorScreen.kt`, `ui/SurgePresentation.kt` — окремий екран.
- `notify/SurgeDeliveryPolicy.kt`, `notify/SurgeLocalStore.kt` —
  дедуплікація, expiry та стійкий локальний ACK.
- `notify/SurgeAckWorker.kt`, `notify/SurgeVoiceService.kt` —
  доставка ACK і життєвий цикл озвучення.

Зміни в існуючих файлах обмежені підключенням цих компонентів.
Дослідні дані `dist/*.json.gz` у Git не переносити.

## Task 1: Чиста модель й якість вхідних даних

**Файли:** нові `surge_model.py`, `models/surge_24h_v1.json`;
`services/backend/tests/unit/test_surge_model.py`,
`services/backend/tests/unit/fixtures/surge_model_cases.json`.

**Інтерфейси:**
`Observation(time: datetime, vehicles: int, paused: bool)`;
`SurgePrediction(issued_at: datetime, window_start: datetime,
window_end: datetime, score: float | None, reason: str | None,
model_version: str)`;
`predict_surge(checkpoint_id: int, observations: Sequence[Observation],
issued_at: datetime) -> SurgePrediction`;
`detect_growth(observations: Sequence[Observation], issued_at: datetime)
-> int | None` повертає придатний п'ятихвилинний приріст.

- [ ] Написати RED тести: golden score збігається з frozen runner до
  `1e-10`; +19 не тригерить, +20 тригерить; tolerance 31s відхиляється;
  gap 91s відхиляється; майбутній запис не входить в ознаки; stale >3min
  й unsupported КПП повертають reason, не score=0. Golden-фікстура
  синтетична, з незалежно розрахованим очікуваним score.
- [ ] Запустити `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_surge_model.py -q`;
  очікувати RED через відсутній модуль/функцію.
- [ ] Перенести тільки frozen параметри з перевіркою SHA, реалізувати
  арифметику стандартною бібліотекою, часові межі й валідацію.
  Не переносити fit, SciPy або приватні навчальні записи.
- [ ] Повторити тести — PASS; перевірити uk/DST, count=0, paused=true,
  рівно 95% coverage й збій checksum ресурсу.
- [ ] Коміт: `feat: додати експериментальну модель напливу`.

## Task 2: Схема, права й optional feature gate

**Файли:** `db/migrations/016_surge_monitor.sql`;
`schema_verify.py`, `schema_gate.py`, `migrate.py`;
`services/backend/tests/database/test_surge_schema.py`,
`test_permissions.py`, `test_migrations.py`;
`ops/restore-verify.sh`, restore allowlist/contract тести.

**Інтерфейс БД:** шість таблиць дизайну. Підписка унікальна за
`(device_id, checkpoint_id)`, містить forecast_enabled/fact_enabled.
Прогноз унікальний за `(checkpoint_id, issued_at, model_version)`.
Одна активна подія за `(checkpoint_id, kind)`; alert унікальний за
`(event_id, device_id)`; attempt — за `(alert_id, ordinal)`.
Стан worker містить останню годину прогнозу й оброблений observation.
`devices.notification_capabilities text[] NOT NULL DEFAULT '{}'`.
Runtime-роль `avelren_surge` без superuser/DDL, пароль не в міграції.
`assert_surge_schema(conn: AsyncConnection) -> None` перевіряє optional
feature 016 перед першою операцією модуля.

- [ ] Написати RED тести uniqueness/FK/check constraints, ролей,
  backup SELECT для всіх таблиць/sequence та повторного migrate.
  Відсутність 016 не зупиняє старий API/collector/notifier при disabled;
  surge endpoint відповідає 503, worker відмовляється стартувати.
- [ ] Запустити ізольований `bash scripts/test_database.sh` — RED.
  Docker-проєкт і БД тимчасові, без production volumes/.env/source calls.
- [ ] Перед реалізацією 016 завершити звірку залежності 015 із PR #72:
  прийнятий код і перевірки мають увійти в узгоджену основу гілки.
  Не створювати штучну 015, не пропускати прогалину в migrate і не
  перетягувати незавершений merge із чужого worktree.
- [ ] Додати 016, явні grants worker/API/notifier/backup, capability,
  kind у cancel-outbox й physical contract як optional migration.
  Синхронізувати migration/restore allowlist і disposable role bootstrap.
  Не міняти застосовану 010 чи загальний мінімум schema для collector.
- [ ] Повторити suite — PASS; restore синтетичної схеми 016 штатними
  hooks відновлює нові таблиці й права. Міграційний порядок із 015
  перевірити після інтеграції PR #72; відсутній 015 — явний deployment
  блокер, а не дозвіл скопіювати його без походження.
- [ ] Коміт: `feat: додати схему та права моніторингу напливів`.

## Task 3: Епізоди, транзакції й worker

**Файли:** `surge_events.py`, `surge_store.py`, `surge_worker.py`,
`config.py`; unit `test_surge_events.py`, `test_surge_worker.py`;
database `test_surge_pipeline.py`.

**Інтерфейси:** `SurgeState`, `SurgeDecision` — dataclasses;
`advance_state(state: SurgeState, prediction: SurgePrediction | None,
growth: int | None, observed_at: datetime, now: datetime) -> SurgeDecision`;
`process_checkpoint(conn: AsyncConnection, checkpoint_id: int,
now: datetime) -> None`; `run_cycle(now: datetime) -> int`.
`SURGE_ENABLED` за замовчуванням false; цикл worker — 60s;
DB statement timeout 5s, один цикл через advisory lock.

- [ ] RED: одне вікно/година при retry; перезапуск не дублює event;
  вище порога продовжує епізод; нижче закриває; 65min timeout;
  факт блокує новий прогноз; після факту rearm лише нижче порога;
  повторні фактичні вікна <=30min утворюють один епізод;
  stale закриває pending; старий replay не створює новий push.
- [ ] Unit-команди з новими двома файлами — RED; disposable pipeline — RED.
- [ ] Реалізувати чисті переходи та їх транзакційне збереження.
  Pending alerts створюються тільки для активних підписок із capability;
  expiry + cancel-outbox записуються разом. Disabled закриває свої
  pending; observations ніколи не змінюються.
- [ ] Ті самі перевірки — PASS; дві одночасні worker-транзакції не
  дублюють результат. Збій КПП не скасовує успішні незалежні КПП.
  Прогноз зберігається з issued_at до майбутнього результату.
- [ ] Коміт: `feat: додати епізоди й worker напливів`.

## Task 4: API, capability та підписки

**Файли:** `surge_api.py`, `surge_schemas.py`, `api.py`,
`schemas.py`, `subscriptions_api.py`, `cancels.py`;
database/api `test_surge_api.py`, `test_auth.py`.

**Контракт:** endpoints дизайну; PUT-підписка має
`{forecast_enabled: bool, fact_enabled: bool}`. DTO прогнозу містить
`checkpoint_id`, `status`, `reason`, `issued_at`, `window_start`,
`window_end`, `expires_at`, `model_version`, `experimental: true`;
DTO активної події — `kind`, `surge_alert_id`, `event_id`, `body`,
`expires_at`, `growth_5m`. Status: disabled/unavailable/no_signal/risk/started.
`notification_capabilities: ["surge_v1"]` додається до створення
пристрою й authenticated update_token; старий клієнт зберігає default [].
`/active-alerts` має окремі списки surge_forecast/surge_started.

- [ ] RED: інший device отримує 404/403 і не ACK-ає чужий alert;
  PUT retry не дублює; DELETE закриває pending і cancel атомарно;
  непідтриманий forecast відхиляється; factual subscription допускається
  для наявного КПП; disabled/без 016 не виконує запити відсутніх таблиць.
- [ ] Запустити API-перевірки штатного disposable database suite — RED.
- [ ] Підключити router і чинну `_device` auth/rate limit; реалізувати
  маршрути та capability для нового/наявного пристрою. ACK ідемпотентний;
  нова підписка бачить лише актуальний епізод із його expires_at.
- [ ] API-suite — PASS; legacy реєстрація, token ownership,
  `/forecast`, threshold/eta/active-alerts залишаються сумісними.
- [ ] Коміт: `feat: додати API експериментального моніторингу`.

## Task 5: Надійні спроби FCM й cancel

**Файли:** `surge_delivery.py`, `surge_text.py`, `notifier.py`,
`fcm.py`, `cancels.py`; unit `test_surge_delivery.py`, `test_fcm.py`;
database `test_surge_delivery.py`.

**Інтерфейси:**
`reserve_attempt(conn: AsyncConnection, alert_id: int, now: datetime)
-> dict | None`; `send_due(client: httpx.AsyncClient, now: datetime) -> int`;
`surge_body(kind: str, checkpoint_id: int, title: str) -> str`.
Payload: `type`, `surge_alert_id`, `attempt_id`, `expires_at`,
`checkpoint_id`, `title`, `body`, `experimental`; legacy alert_id відсутній.

- [ ] RED: reserve до FCM; retry після timeout/commit crash має той
  самий attempt_id; через 300s після прийняття новий ordinal;
  dead token вимикається; expired/ACK не відправляється; cancel після
  гонки supersedes normal із тим самим collapse key. Точні фрази Чопа.
- [ ] Нові unit та disposable delivery тести — RED.
- [ ] Додати незалежну фазу send_due без блокування legacy доставок
  на помилці surge. Перевіряти активність перед send; TTL не перевищує
  expiry та 360s. Підключити обидва нові kind у cancel/reconciliation.
- [ ] Тести — PASS; old-device capability не отримує surge; regression
  threshold/eta без змін їхніх повторів і ACK.
- [ ] Коміт: `feat: додати доставку й повтори сповіщень напливів`.

## Task 6: Android API й стійкий локальний ACK

**Файли:** нові `data/SurgeApi.kt`, `SurgeRepository.kt`,
`notify/SurgeLocalStore.kt`, `SurgeDeliveryPolicy.kt`, `SurgeAckWorker.kt`;
існуючі `data/Api.kt`, `AvelRenApp.kt`, `notify/AckReceiver.kt`,
`Notifications.kt`, `AlertReconciliation.kt`, `NotificationReconciler.kt`.
Тести: `SurgeContractTest.kt`, `SurgeDeliveryPolicyTest.kt`,
`SurgeAckPersistenceTest.kt` у відповідних `src/test/.../data|notify`.

**Інтерфейси:** `SurgeApi.snapshot(checkpointId: Int)`,
`subscriptions(creds)`, `setSubscription(creds, checkpointId, forecast, fact)`,
`ack(creds, alertId: Long)`; `SurgeLocalStore.acknowledge(alertId: Long)`,
`isAcknowledged(alertId)`, `claimAttempt(alertId: Long, attemptId: Long): Boolean`;
`SurgeDeliveryPolicy.shouldPresent(payload: SurgePayload, now: Instant): Boolean`.
Kind codes для Notifications: forecast=4, started=5; full key у extras.

- [ ] RED: DTO unknown/optional fields; локальний ACK і seen-attempt
  переживають створення нового store після kill; duplicate claim false;
  ACK не можна зняти пізнім push; expiry не показує/не озвучує;
  different kinds з однаковим числовим ID не перекриваються.
- [ ] Із `apps/android`: `./gradlew.bat -PavelrenUiPreview=true :app:testDebugUnitTest :app:compileDebugKotlin --no-daemon --max-workers=2`
  — RED у нових тестах, без Firebase секретів.
- [ ] Реалізувати окремі DTO/repository, preferences-стійкий ACK
  і attempt ledger; персистентний WorkManager ACK із network constraint,
  backoff і чинним auth recovery. При локальному ACK відразу cancel
  notification/voice; pending ACK видаляється тільки після серверного успіху.
  Новий клієнт передає capability і при token refresh.
- [ ] Gradle-тести/compile — PASS; повтор після reboot зберігає ACK;
  reconcile не відновлює підтверджену подію. Старі ACK paths перевірені.
- [ ] Коміт: `feat: додати Android контракт і стійкі підтвердження напливів`.

## Task 7: Екран кількох КПП і постійна нижня позначка

**Файли:** нові `ui/SurgeMonitorScreen.kt`, `SurgePresentation.kt`;
`ui/AvelRenScreen.kt`, `res/values/strings.xml`;
`src/test/.../data/SurgePresentationTest.kt`.

**Інтерфейс:**
`SurgeMonitorScreen(repository: SurgeRepository, onBack: () -> Unit)`;
presentation переводить DTO і локальний стан у зрозумілі українські картки.
Compose `Scaffold(bottomBar = DevelopmentFooter)` закріплює
«Функція в розробці» над systemBars; список має відповідні inset/padding.

- [ ] RED presentation: дві окремі події, broad window із датами Kyiv,
  no_signal != «напливу немає», unavailable/unsupported/stale,
  enabled voice без notification permission не виглядає справним.
- [ ] Gradle testDebugUnitTest — RED.
- [ ] Підключити екран до третьої плитки; multi-select КПП, явно
  ввімкнути/вимкнути subscription, два типи й voice toggle. Loading,
  error, offline та empty не приховують footer. Чинний count forecast
  відкривається як окремий блок. Кнопки прикладу голосу немає.
- [ ] Gradle PASS; в емуляторі через UI tree/screenshots перевірити
  footer у loading/error/long-scroll і великий шрифт, два вибрані КПП,
  disabled forecast для unsupported, back navigation і permission action.
- [ ] Коміт: `feat: додати екран експериментального моніторингу КПП`.

## Task 8: Голос і фоновий життєвий цикл

**Файли:** нові `notify/SurgeVoiceService.kt`, `SurgeVoicePolicy.kt`;
`AvelRenMessagingService.kt`, `Notifications.kt`, `AndroidManifest.xml`;
`src/test/.../notify/SurgeVoicePolicyTest.kt`.

**Інтерфейс:**
`SurgeVoicePolicy.canStart(payload: SurgePayload, now: Instant,
pushPriority: Int, isForeground: Boolean, voiceEnabled: Boolean,
channelAllowed: Boolean): Boolean`;
`SurgeVoiceService.enqueue(context: Context, payload: SurgePayload)`;
`stopAlert(context: Context, alertId: Long)`.

- [ ] RED: normal priority в background не стартує FGS; high priority
  допускає перевірку startup; duplicate/ACK/expiry/channel block вимикають
  голос. TTS init fail, немає uk голосу, audio-focus refusal — завершення
  без exception і без пізнього replay. Bounded черга: максимум 10
  актуальних utterance, кожен до 30s із перевіркою ACK перед start.
- [ ] Gradle unit — RED.
- [ ] Реалізувати короткий FGS mediaPlayback із permissions і foreground
  notification; TTS uk-UA, локальний voice preference, audio focus.
  Спершу текст, потім optional voice; ACK/cancel перериває конкретний
  utterance. Service завершується після черги, init timeout 10s,
  загальний watchdog 60s; onDestroy release TTS/audio focus.
- [ ] Unit/compile/lint — PASS; в емуляторі перевірити background,
  екран заблокований, FGS startup rejection, queued cancel, reboot.
  На телефоні окремо перевірити український жіночий голос і repeat 5min.
- [ ] Коміт: `feat: додати голосові повідомлення напливів`.

## Task 9: Runtime, перевірки гілки й пакет установлення

**Файли:** `docker-compose.yml`, `.env.example`,
`ops/compose.surge-test.yml`, `ops/surge-integration-test.sh`,
`ops/surge-runtime-contract-test.py`, `.github/workflows/database.yml`,
`docs/SURGE-MONITOR.md`, `docs/RELEASE-READINESS.md`.

**Інтерфейс runtime:** service `surge_worker`, entrypoint
`python -m avelren.surge_worker`; без Firebase/upstream credentials,
з окремим обмеженим DATABASE_URL, без host ports/production volumes
у disposable suite. Worker у профілі `surge`, глобальний flag false
до погодженого deploy. Статус модуля показує останній цикл/помилку
та model_version, а не фіктивний «99%».

- [ ] RED: static Compose contract доводить відсутність залежності
  collector від нового worker, explicit profile/role, kill switch;
  disposable suite проходить fixture→prediction/fact→FCM stub→ACK→cancel,
  restart/idempotency і синтетичний backup/restore нових таблиць.
- [ ] Реалізувати runtime/config/CI із чинними образами-кандидатами;
  не міняти pins Timescale/Caddy/OS/Docker та collector mount.
- [ ] Перевірити backend unit/ruff/provenance, disposable DB/API,
  `bash ops/surge-integration-test.sh`, штатний restore rehearsal,
  Android unit/compile/lint; зафіксувати точний commit і кожний результат.
  Відсутній або нерелевантний CI не позначати успішним.
- [ ] Один незалежний review всієї гілки: data leakage, ACL/ownership,
  feature gate, FCM crash races, local ACK і TTS фон. Виправити доведені
  дефекти та повторити лише пов'язані перевірки.
- [ ] PR із українським описом, spec/plan/release status; прикріпити PR
  до чату. Інтегрувати після перевірок, зберегти походження PR #72/015
  і дослідного frozen manifest. Чужі worktree-зміни не переносити мовчки.
- [ ] Зняти свіжий read-only production preflight: Compose overrides,
  pin/фізична схема/grants, активні immutable images, installed files,
  backup й runtime. Підготувати `dist/surge-deploy/INSTALLATION-PLAN.md`
  з точними образами/файлами/міграціями/діями та відкатом. Окремо
  погодити необхідний порядок 015/016 й worker DB credentials;
  перехід прав БД не маскувати під ввімкнення функції.
- [ ] Запитати дозвіл власника саме на готовий пакет. До нього —
  жодних production write/migrate/recreate. Після GO перевірити
  фактичну схему, свіжий prediction/fact, notifier і cancel, колектор
  60s, видимий контейнеру вміст і наступний backup. При невдачі —
  погоджений відкат, без destructive down migration.
- [ ] З чистої актуальної main зібрати підписаний APK із новим
  versionCode, записати commit/version/SHA-256; перевірити на телефоні
  два КПП, прогноз/факт, голос, repeat 5min, offline «Зрозуміло»,
  late duplicate/expiry, reconnect/reboot. До доказу результату
  не ставити «перевірено на телефоні». Публікації — задача 10.

## Task 10: Опис, GitHub Release, потім Google Play Console

**Файли:** `apps/android/app/build.gradle.kts`,
`apps/android/app/src/main/assets/release-notes/v1.0.3.uk.txt`,
`docs/RELEASE-1.0.3.md`, `docs/RELEASE-READINESS.md`;
локальні секретні збіркові записи `dist/BUILD.txt` не комітити.
Назви release-notes й документа використовують погоджений номер:
якщо власник уточнює 0.1.3, це `v0.1.3.uk.txt` / `RELEASE-0.1.3.md`.

**Інтерфейс релізу:** один versionName, один main commit, один комплект
підписаних APK/AAB із зафіксованими SHA-256. На GitHub tag
`v1.0.3` і назва `AvelRen 1.0.3` для названої власником версії;
після уточнення 0.1.3 використовується вже наявна чернетка v0.1.3.
Ні опубліковані теги, ні secure-backup release не змінюються.

- [ ] Після review зафіксувати погоджений versionName. Через read-only
  Play Console звірити максимальний використаний versionCode у всіх
  треках; новий код — max+1. Перевірити чинний upload certificate та
  актуальні вимоги Play. Паролі брати за SECRETS-RECOVERY.md.
- [ ] Підготувати український опис тільки фактично інтегрованих змін.
  Спільний короткий текст для застосунку, GitHub і Play містить
  експериментальний прогноз, моніторинг кількох КПП, окремий факт,
  голос/повтори й «Функція в розробці». Він не обіцяє 99% або точну
  годину напливу. Звірити весь RELEASE-READINESS, старі блокери та
  scope чернетки 0.1.3; незавершені зміни не заявляти виконаними.
- [ ] Перевірити довжину короткого тексту за чинним лімітом Play,
  збіг номера в Gradle/assets/описі, і читання release notes на телефоні.
  Спочатку зберегти й показати reviewable опис; чернетка не означає реліз.
- [ ] Після завершення задачі 9 з чистої main зібрати перевірені
  `:app:assembleRelease :app:bundleRelease` для того самого коміту.
  Зафіксувати manifest versionName/versionCode, підпис, SHA-256
  APK/AAB, CI й результати телефона. При зміні коду комплект перебудувати
  та повторити пов'язані перевірки до будь-якої публікації.
- [ ] Підготувати GitHub Release на точному main commit із погодженим
  tag, описом і перевіреними APK/AAB. Якщо існує відповідна чернетка,
  оновити її, а не створювати дублікат. Публікація тільки готового
  комплекту; запитати конкретне фінальне схвалення, якщо його немає.
- [ ] Після публікації перевірити реальний GitHub Release, tag commit,
  assets і SHA-256. Лише успішний `gh` exit не завершує цей пункт.
- [ ] Лише після перевіреного GitHub Release завантажити той самий
  AAB у погоджений трек Google Play Console, перенести узгоджені notes,
  перевірити попередження Console, versionCode та склад змін.
  Трек і rollout-параметри показати власнику для конкретного схвалення
  перед поданням, якщо вони ще не погоджені.
- [ ] Результати «завантажено», «подано на review», «опубліковано» та
  «доступно користувачу» записати окремо. Google review не підміняти
  успішним upload. Не надсилати release push до підтвердженої
  доступності відповідному користувачу в Play.

## Перед початком виконання

- [ ] Після review плану застосувати using-git-worktrees: придатного
  чистого feature worktree серед наявних немає (PR #72 у merge із
  чужими змінами), тому створити окремий `codex/experimental-surge-monitor`
  від звіреної main через native worktree tool.
- [ ] Перенести лише погоджені spec/plan й потрібний frozen ресурс;
  зберегти окремо поточні research docs та сторонні локальні зміни.
- [ ] Зафіксувати baseline перевірки. Наявні відомі збої PR #72
  не оголошувати результатом нової функції та не обходити перед deploy.

## Критерій завершення

Код/CI, серверне ввімкнення та APK/телефон мають окремі докази.
Експериментальна функція працює для вибраних КПП у погоджених
сценаріях, позначка розвитку завжди видима, ACK зупиняє голос,
collector зберігає контракт. Це завершення експериментального
ввімкнення, а не підтвердження досягнення 99%.
