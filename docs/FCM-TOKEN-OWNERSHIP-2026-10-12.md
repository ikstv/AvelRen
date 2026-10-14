# Власність FCM-токена — 12.10.2026

## Уточнення статусу — 14.10.2026

Source злитий у [PR #123](https://github.com/ikstv/AvelRen-ORIGINAL/pull/123), main 4ee4b1bd911fec5b78ae908ae593a8d81ac3cfa8. Подальший main CI 38287247895 успішний для всіх 11 jobs, включно з Android. Серверна частина увійшла до [розгортання API/notifier 12.10](audits/API-NOTIFIER-DEPLOYMENT-2026-10-12.md). Новий APK/version/SHA-256, конфлікт і відновлення на телефоні, доставка push та Play цим не прийняті. Нижчі очікування source review/CI/merge збережені як перебіг підготовки, а не поточні блокери.

## Контракт і межі

Інтегрований source кандидат `codex/fcm-token-ownership-20261012` перевіряється
від `f1cfde859a9d25a45962c6addf5f2af1e66029c1`. Серверні зміни:
`b538d03`, додаткові ownership-регресії `a9a84ac`; Android durable storage
`5f3c739`, coordinator `7816d09` / scheduling fix `d159fb2`, runtime wiring
`43ea0a5`. Незалежні task reviews завершені; scoped re-review після виправлень,
exact-head hosted CI, свіжий candidate SBOM і злиття цієї гілки ще попереду.
Гілка також містить погоджені planning docs та reviewed security update
urllib3 `162669e` (оригінальний independently reviewed `215dea4`).

Whole-branch review head `3d1358ae33ef7ff452469220937912ca15281a31`
виявив R1–R3 і minor M1. Єдина Android fix wave — source commit
`5ab29ea4a49dfed1075cd2e935c5db1f7fe2233a`; scoped re-review ще очікується.
Наведені нижче попередні backend результати не перезапускалися, оскільки
server source цієї хвилі не змінювався.

POST вільного токена повертає 201 та нові credentials; зайнятого — 409
`detail.code=fcm_token_conflict` без нової installation та зміни власника.
PUT спочатку перевіряє credentials; власний/вільний токен приймає з 200,
чужий відхиляє typed 409. UNIQUE(fcm_token) лишається остаточною гарантією БД.
Збережені devices, capabilities, subscriptions, ETA/surge та Admin не переносяться
за токеном. 401 означає іншу проблему: credentials більше не чинні.

Android обробляє лише coded 409 як token conflict. Valid credentials при PUT409
зберігають ту саму identity; після втрати secret нова registration не відкриває
старі subscriptions або Admin. Один durable incident допускає лише одну
завершену automatic rotation через чинні Firebase deleteToken()/getToken().
Повторний conflict стає conflict_blocked; кнопка повтору зберігає бюджет.
Canonical SDK token, generation/phase CAS, acknowledged encrypted preferences,
enqueue-before-HTTP та worker без self-REPLACE захищають від stale callbacks,
паралельного recovery, offline/restart і втраченої POST-відповіді. Push status
видимий окремо від Ready. Corrupt/failed storage зупиняє небезпечне продовження.
Це не гарантія distributed exactly-once або доставки Firebase.

## Приймання source

Команди й повні результати локального Task 5 збережені в ignored SDD report
`.superpowers/sdd/2026-10-12-fcm-token-ownership/task-5-report.md`.
Backend unit: 669 passed, 2 warnings; full API PostgreSQL: 104 passed,
2 warnings; default DB — 190 passed (включно з 14 notifier regressions). Runtime Linux / Python 3.14.7, pytest 9.1.1, усі 35 lock pins
звірені; urllib3 фактично 2.8.0. Read-only offline unit image:
`sha256:877960721eebfe36ccd3f9b213da958026bb45a4f07fae1455430d46e50a106f`.
API/default DB images будуються штатним hash-locked runner; їх фактичні pins
перевіряються окремо. Реальні API-role/PG тести включають concurrent claims,
повторні parallel PUT одного owner, lock timeout/auth race та успішний запит
після conflict savepoint; populated ETA/surge graph збережений.

Попередній Android head `3d1358a`: JVM — 293 tests, 0 failures, 0 errors; compile успішний. JVM перевіряє durable recreation усіх phases, lost response, budget,
credential commits, cancellation та repository/worker wiring; Ktor transport
перевіряє старий success contract POST201/PUT200 і новий typed409 одним кодом.
Це synthetic MockEngine/JVM приймання, не APK проти live legacy сервера.
Production Firebase adapter компілюється з unchanged BOM33.7.0 / messaging24.1.0.
JDK17.0.19.10, SDK36, existing Gradle cache; lint: 0 errors, 40 warnings,
6 hints. Новий FcmRecoveryStore.kt:50 має style warning UseKtx; explicit editor/commit
збережений за acknowledged-write contract, автоматичний apply неприйнятний.
SDK XML v3/v4 compatibility warning лишається; dependency deprecations
та Timescale circular-FK pg_dump warning відомі. Dump success не доводить restore.
Оригінальні provenance hashes й попередні revision notes збережені; Android
manifest оновлює лише фактично змінені успадковані файли. Нові recovery файли
мають власне походження у commits/spec/plan цієї зміни.

### Android після whole-branch findings — точний source head

На `5ab29ea4a49dfed1075cd2e935c5db1f7fe2233a` виконано:
`gradlew.bat -PavelrenUiPreview=true :app:testDebugUnitTest :app:compileDebugKotlin :app:lintDebug --no-daemon --max-workers=2`
з `apps/android`, existing JDK17/SDK36/Gradle cache. Exit0, BUILD SUCCESSFUL
за 2m; **301 JVM tests, 0 failures, 0 errors**; Kotlin compile і lint успішні.
Lint report: **0 errors, 40 warnings, 6 hints**. Output не називається pristine;
SDK XML/Locale та UseKtx baseline лишається disclosed. Синхронний
acknowledged commit у FcmRecoveryStore не замінено на apply.

Same canonical callback під час replacement POST тепер зберігає весь active
record, credentials і Ready; coalescing використовує process-local active
snapshot, не durable phase як доказ scheduling. Після failed/cancelled
enqueue або restart потрібне свіже acknowledgement. Production scheduler
передає `APPEND_OR_REPLACE` до enqueueUniqueWork: genuinely new token отримує
successor без скасування active worker. Obsolete terminal HTTP response
повертає Retry, щоб не завершити successor chain помилкою. Worker не enqueue
самого себе; мережеві constraints і exponential backoff збережені.

Реальний process foreground observer відновлює лише наявний pending incident;
Failed enqueue не переходить до HTTP. Startup/resume читає canonical SDK token
для conflict_blocked: новий Z синхронізується з тим самим incident/budget1,
незмінний Y не викликає HTTP/delete/enqueue. Вісім нових JVM regressions
перевіряють repository/observer/worker і production scheduler enqueue port,
включно з replacement POST barrier, справді новим candidate, cancellation
і scheduling acknowledgement. Android WorkManager SQLite/Firebase runtime
цим JVM контрактним тестом не запускаються.

Terminal 400/403/422/unrelated409 показує typed Rejected:
«Не вдалося синхронізувати сповіщення. Спробуйте ще раз.» з кнопкою
«Спробувати ще раз». У тому самому процесі unchanged callback/resume/worker
інертні; manual retry зберігає incident/budget і не запускає rotation.
Recovery format не розширювався: recreation може зробити одну нову terminal
спробу. Повторні foreground entries для неактивного pending можуть додати
дешевий redundant successor, який після clear завершиться NothingPending.

Оновлено рівно чотири inherited Android provenance records; original SHA-256
і весь previous revision/history збережено. `scripts/verify_android.py`
підтвердив 64 records/assets. Повні RED/GREEN/final logs, точний source SHA,
docs-only evidence head і перевірка однакових Android source/test/provenance
bytes записані у ignored
`.superpowers/sdd/2026-10-12-fcm-token-ownership/final-fix-report.md`.
Це локальне source приймання; scoped re-review, exact-head hosted CI/SBOM,
merge, deployment, APK/version/hash, телефон і Play лишаються окремими gates.

## Послідовність до релізу

1. Завершити whole-branch review, exact-head CI/SBOM і перевірене злиття.
2. Перед окремим operational GO свіжо звірити schema/migration pin, активні
   images, backups/restore readiness і прийнятий rollback. Окремо перевірити
   PostgreSQL parameter/error logging: application redaction не доводить
   відсутність secret/token у server logs.
3. Розгорнути API першим за окремим дозволом, із підтвердженням фактичного
   коду й поведінки. Не додавати insecure takeover fallback для старого APK.
4. З чистої погодженої main підготувати APK, записати commit/version/SHA-256,
   перевірити на телефоні reinstall/lost-secret, restored credentials, offline,
   restart і push status. Старий APK може не відновити token conflict до update;
   потрібен доступний канал оновлення, який не покладається на push.
5. Окремо прийняти Play publication і delivery. Чинний 0.1.3 залишається
   неопублікованим до телефонного/Play gates; готовність коду не закриває їх.

Notifier PR #122 вже MERGED у main `ad9e92a6` після 7 успішних PR checks;
main push run не спостерігався. Це окремий source факт, не deployment proof.
Maintenance six-task plan і CI aggregate gate plan погоджені, але ще не
реалізовані. CI-gate не додавався до Task 5. Production, live FCM/єЧерга,
APK install та Play publication під час цього приймання не виконувалися.

## Уточнення provenance після hosted CI — 12.10.2026

Android run `38265779833` для PR #123 відхилив provenance DeviceStore.kt.
Звірка всіх 64 targets з exact Git blobs `6ff70be` знайшла рівно два
розбіжні revision hashes: DeviceStore.kt та FcmTokenRetryTest.kt. Локальні
bytes мали відповідно 168 та 1 CRLF; Git blobs — LF відповідно до
`.gitattributes`. Після CRLF→LF bytes повністю збігаються; source behavior,
тести та locks у Git не змінені. Revision SHA-256 виправлено на canonical
Git bytes, помилкові worktree hashes та попередню історію збережено у `previous`.
Алгоритм verifier лишається строгим і незмінним. Clean Git archive відтворив
RED mismatch до repair; fresh archive нового commit має пройти всі provenance
checks. Локальний попередній GREEN перевіряв worktree, тому сам по собі не
довів сумісність із LF checkout hosted CI. Новий exact-head CI та source/SBOM
приймання ще потрібні; deployment/APK/phone/Play цим repair не прийняті.
