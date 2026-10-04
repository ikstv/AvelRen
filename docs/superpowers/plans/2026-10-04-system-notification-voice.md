# План реалізації системного голосу зростання черги

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Озвучувати події до п'яти КПП початковим голосом через системні сповіщення у фоні й із погашеним екраном.

**Architecture:** Локальний TTS заздалегідь готує WAV; вузький provider відкриває готові файли системі. Коротка foreground service послідовно оновлює видимі повідомлення зі звуком, зберігаючи dedup, expiry, ACK та cancel.

**Tech Stack:** Kotlin, Android SDK, TextToSpeech, NotificationManager, content provider, coroutines, чинні JUnit4 та Gradle. Нових бібліотек немає.

**Spec:** [Погоджена специфікація](../specs/2026-10-04-system-notification-voice-design.md), схвалена власником 04.10.2026 після PR #87, commit `8af9cc162764ca5f9ace260775ae67fb6e8095e6`.

## Global Constraints

- Максимум — п'ять КПП; чинна черга — 10 свіжих спроб, без disk replay.
- Голос `uk-UA-language`, pitch 1.0, rate 0.88, чинний локальний український fallback.
- Фрази — чинний `CheckpointSpeech`; «наплив», voice-off і «Прослухати приклад» не додаються.
- WAV до 15 секунд; між фразами — тривалість попередньої плюс 1 секунда.
- `USAGE_NOTIFICATION` / `CONTENT_TYPE_SPEECH`; гучність не змінюється.
- `shortService` на API 34+, власний deadline 160 секунд, START_NOT_STICKY, без boot.
- Сервер, модель, collector, API/БД не змінюються. Новий production FCM QA потребує окремого конкретного дозволу.
- Прототип не зливається цілком. Телефонний кандидат — з чистої main після відповідного CI, із SHA-256 readback.

## Review Focus

- Перевстановлення або втрата WAV: видиме резервне сповіщення, чесний voice_not_ready, без пізнього replay — Tasks 2/4.
- Вимкнений старий канал або змінений системний звук: новий канал не обходить рішення користувача — Task 3.
- ACK між тихим показом і звуковим оновленням: повідомлення й голос не відновлюються — Tasks 4/5.
- Нові FCM біля deadline чи завершення служби: bounded shutdown і чинний серверний повтор, без зависання — Tasks 4/5.
- Оновлена назва/категорія КПП під час підготовки: метадані відповідають файлу, жодного неповного WAV — Task 2.

## Файли і відповідальність

Відносні шляхи нижче — від кореня репозиторію. Скорочення:
`N = apps/android/app/src/main/java/ua/avelren/app/notify`,
`T = apps/android/app/src/test/java/ua/avelren/app/notify`.
Ці значення використовуються як точні префікси шляхів у задачах.

- `N/SurgeVoiceAssets.kt`: підготовка TTS, приватний реєстр і атомарні файли.
- `N/VoiceAssetPolicy.kt`: ключі ресурсів, допустимі URI-шляхи й WAV validation без Android.
- `N/SurgeVoiceProvider.kt`: read-only доступ до готових файлів.
- `N/SurgeVoiceChannels.kt`: сталі канали та перевірка системних налаштувань.
- `N/SurgeVoiceSchedule.kt`: deadline і час наступної фрази без Android.
- `N/SurgeVoiceService.kt`: коротка послідовність звукових повідомлень.
- `N/SurgeVoiceDelivery.kt`: узгоджений тихий показ і постановка прийнятої спроби в чергу.
- `N/Notifications.kt`: первинний/звуковий показ того самого повідомлення.
- `N/AvelRenMessagingService.kt`, `N/AckReceiver.kt`, `N/NotificationReconciler.kt`: інтеграція чинної доставки й відміни.
- `apps/android/app/src/main/java/ua/avelren/app/ui/ForecastOverviewScreen.kt`,
  `apps/android/app/src/main/java/ua/avelren/app/AvelRenApp.kt`: підготовка при виборі/foreground.
- `apps/android/app/src/main/java/ua/avelren/app/ui/SurgePresentation.kt`: короткі причини відсутності голосу.
- `apps/android/app/src/main/AndroidManifest.xml`, overlays preview/connectedTest/pushQa:
  provider і FGS тип без тестових компонентів у release.
- `apps/android/app/src/pushQa/java/ua/avelren/app/PushQaActivity.kt`,
  preview/connectedTest `VoiceProbeActivity.kt`: QA підготовки й доставки.
- `docs/ANDROID-PROVENANCE.json`, `docs/RELEASE-READINESS.md`, аудит:
  походження коду та окремі етапи приймання.

## Task 1: Докази звукового оновлення, cancel і shortService

**Files:** тимчасова гілка `codex/notification-voice-spike`; preview probe файли
з коміту `188ffee683b2aa0b58027526aa173f0c92f63da5`; локальні результати
`dist/notification-voice-spike-20261004/`. Продуктових файлів немає.

**Interfaces:** споживає готові forecast.wav/fact.wav і чинні channel URI.
Вихід — receipt для silent→sound того самого tag/ID, cancel, послідовності
та запуску FGS; pass/fail з відповідями власника, без припущення чутності з логів.

- [ ] Зафіксувати вихідний APK/commit та розширити throwaway probe окремими режимами: тихий показ→звук, cancel під час фрази, п'ять фраз поспіль, shortService після згортання. Не додавати мережу/Firebase.
- [ ] Зібрати чистий коміт прототипу штатним preview режимом; hash APK і readback установленого файла мають збігтись. Зберегти робочий пакет телефона.
- [ ] Виконати режими по одному: у першому — одна фраза без другого повідомлення, у cancel — перерване звучання, у sequence — п'ять повних фраз без взаємного обрізання, у shortService — правильний тип, власне завершення, відсутній ANR.
- [ ] Якщо будь-який режим fail, зафіксувати результат і скоригувати специфікацію до продуктового коду. Синхронізацію CANCEL/ACK не називати готовою без phone evidence.
- [ ] Закомітити лише аудит висновків у робочу гілку; код probe лишається throwaway. Для всіх наступних задач потрібен PASS цього gate.

## Task 2: Готові голосові ресурси і read-only provider

**Files:** create `N/VoiceAssetPolicy.kt`, `N/SurgeVoiceAssets.kt`,
`N/SurgeVoiceProvider.kt`; tests `T/VoiceAssetPolicyTest.kt`;
modify main manifest, provenance.

**Interfaces:**
- `data class VoiceSoundKey(val checkpointId: Int, val kind: String)`.
- `data class WavInfo(val durationMs: Long)`;
  `VoiceAssetPolicy.inspectWav(bytes: ByteArray): WavInfo?`;
  `VoiceAssetPolicy.parsePath(path: String): VoiceSoundKey?`.
- `data class PreparedVoice(val key: VoiceSoundKey, val text: String, val voiceName: String, val sha256: String, val durationMs: Long)`.
- `sealed interface VoicePreparation` з `Ready(val voices: List<PreparedVoice>)` та `Failure(val reason: String)`.
- `SurgeVoiceAssets(context).prepare(checkpointId: Int, title: String): VoicePreparation` — suspend;
  `ready(key: VoiceSoundKey): PreparedVoice?`; `soundUri(key: VoiceSoundKey): Uri`;
  `openReady(key: VoiceSoundKey): ParcelFileDescriptor?`.

- [ ] Написати failing `VoiceAssetPolicyTest`: валідний PCM WAV має правильну тривалість; truncated/data bounds/порожній PCM/понад 15 с відхиляються. `parsePath` приймає лише `/v1/17/surge_forecast.wav`, відхиляє traversal, інші kind, cp≤0 й зайві сегменти.

```kotlin
assertEquals(VoiceSoundKey(17, "surge_forecast"), VoiceAssetPolicy.parsePath("/v1/17/surge_forecast.wav"))
assertNull(VoiceAssetPolicy.parsePath("/v1/../surge_forecast.wav"))
assertNull(VoiceAssetPolicy.inspectWav(byteArrayOf(1, 2, 3)))
```

- [ ] Запустити `gradlew.bat -PavelrenUiPreview=true :app:testDebugUnitTest --tests '*VoiceAssetPolicyTest' --no-daemon --max-workers=2`; очікується FAIL через відсутній компонент.
- [ ] Реалізувати інтерфейси: приватні files/surge-voice/v1, trusted manifest, atomic replace, перевірка SHA/тексту/параметрів перед reuse. Mutex з повторною перевіркою ready усередині запобігає подвійній підготовці. TTS init timeout 10 с, synthesis до 30 с на фразу, shutdown у finally. Cancellation не записує ready і не ховає exception.
- [ ] Provider: exact authority `${applicationId}.surgevoice`, тільки готові ключі, лише mode=r, без query/fragment, audio/wav; query повертає лише OpenableColumns. insert/update/delete відхиляються. URI grant увімкнений, exported=false.
- [ ] Запустити focused tests і compile/lint; phone probe перевіряє відсутній файл, повторну підготовку після зміни категорії та відсутність готового запису після abort. Оновити provenance й commit.

## Task 3: Сталі канали з повагою до системних налаштувань

**Files:** create `N/SurgeVoiceChannels.kt`, `T/SurgeVoiceChannelsPolicyTest.kt`;
modify `N/Notifications.kt`; update provenance.

**Interfaces:**
- `data class VoiceChannelState(val visible: Boolean, val voiceAllowed: Boolean, val problem: String?)`.
- `SurgeVoiceChannels.ensure(context: Context, voice: PreparedVoice, title: String): String` повертає channel ID.
- `SurgeVoiceChannels.state(context: Context, voice: PreparedVoice): VoiceChannelState`.
- `SurgeVoiceChannelPolicy.evaluate(appAllowed: Boolean, legacyImportance: Int, legacySoundPresent: Boolean, voiceImportance: Int, voiceSoundPresent: Boolean, soundMatches: Boolean): VoiceChannelState` — pure function.

- [ ] Написати failing policy tests: app block/NONE не озвучується; legacy LOW або null sound забороняє новий голос; конкретний LOW/null sound теж; змінений sound позначається voice_sound_changed і не перезаписується.

```kotlin
assertFalse(SurgeVoiceChannelPolicy.evaluate(true, 2, true, 4, true, true).voiceAllowed)
assertFalse(SurgeVoiceChannelPolicy.evaluate(true, 4, false, 4, true, true).voiceAllowed)
assertEquals("voice_sound_changed", SurgeVoiceChannelPolicy.evaluate(true, 4, true, 4, true, false).problem)
```

- [ ] Запустити focused Gradle tests; очікується FAIL до реалізації.
- [ ] Реалізувати exact IDs v1/cp/kind, HIGH, USAGE_NOTIFICATION/SPEECH, URI із Task 2. Не видаляти й не перестворювати канал для повторів чи повторного вибору. `state` читає фактичні налаштування; виклик ensure не доводить чутність.
- [ ] Повторити focused tests; на окремому QA пакеті вимкнути старий/новий канал і перевірити відмову, потім повернути лише QA налаштування. Compile/lint/provenance та commit.

## Task 4: Послідовне озвучення і скасування

**Files:** create `N/SurgeVoiceSchedule.kt`, `N/SurgeVoiceDelivery.kt`,
`T/SurgeVoiceScheduleTest.kt`; modify `N/SurgeVoiceService.kt`,
`N/SurgeVoicePolicy.kt`, `T/SurgeVoicePolicyTest.kt`, `N/Notifications.kt`,
`N/AvelRenMessagingService.kt`, manifests main/preview/connectedTest; provenance.

**Interfaces:**
- `SurgeVoiceSchedule(startElapsedMs: Long)`; `canStart(nowElapsedMs: Long, durationMs: Long): Boolean`;
  `reserve(nowElapsedMs: Long, durationMs: Long): Long` повертає час після WAV+1000 ms.
- `Notifications.showSurge(context: Context, payload: SurgePayload, voice: PreparedVoice?, silent: Boolean): Boolean` — posted чи refused.
- `SurgeVoiceDelivery.present(context: Context, payload: SurgePayload, allowVoice: Boolean)` — лише вже claimed attempt; показ і enqueue на main thread.
- Чинні `SurgeVoiceService.enqueue` та `stopAlert` зберігають сигнатури; claimAttempt залишається в MessagingService.

- [ ] Написати failing schedule tests: друга фраза не стартує до завершення WAV+1000 ms; запуск, що перевищить 160000 ms deadline, відхиляється; нове повідомлення не продовжує deadline. Доповнити queue tests: cancel до черги, факт прибирає лише прогноз свого КПП, expired та blocked entries не стартують.

```kotlin
val schedule = SurgeVoiceSchedule(0)
assertEquals(4000L, schedule.reserve(0, 3000))
assertFalse(schedule.canStart(3999, 3000))
assertTrue(schedule.canStart(4000, 3000))
assertFalse(schedule.canStart(150001, 10000))
```

- [ ] Запустити focused tests, підтвердити RED тільки нових вимог.
- [ ] Реалізувати тихий первинний показ, потім звукове оновлення того самого tag/ID й незмінних extras/ACK PendingIntent. Missing ready → чинний загальний канал + voice_not_ready. allowVoice=false → без enqueue. Звукове оновлення не синтезує payload.body.
- [ ] Переробити службу: старт foreground до роботи, API34+ SHORT_SERVICE, старі API — тип NONE; монотонний clock для розкладу, Instant для expiry, recheck250 ms, власний deadline160 s та onTimeout. При ACK/cancel/expiry скасувати поточне повідомлення і таймер; callback старої фрази не завершує нову. Queue overflow/deadline/start refusal лишають видимий alert і явну причину. При кожному notify перевірити local block до/після, не відновлювати ACK повідомлення.
- [ ] Прибрати delivery TTS.speak/audio focus і непотрібний MEDIA_PLAYBACK permission; змінити overlays, що самостійно оголошують старий тип. Service finish прибирає лише службове повідомлення, не активні alerts.
- [ ] GREEN focused tests, повний Android JVM/compile/lint/provenance. Phone QA із Task 1 повторити для робочого компонента, включно ACK до старту й під час звуку, forecast→fact, п'ять КПП, queue overflow та deadline. Закомітити завершений компонент.

## Task 5: Підготовка при виборі КПП і коректні стани екрана

**Files:** modify `ForecastOverviewScreen.kt`, `AvelRenApp.kt`,
`ui/SurgePresentation.kt`, `N/AckReceiver.kt`, `N/NotificationReconciler.kt`;
create `N/SurgeVoicePreparationCoordinator.kt`,
`T/SurgeVoicePreparationCoordinatorTest.kt`; update provenance.

**Interfaces:** `SurgeVoicePreparationCoordinator(prepare: suspend (Int, String) -> VoicePreparation)`;
`enable(checkpointId: Int, title: String, save: suspend () -> Unit): VoicePreparation`;
save викликається лише після Ready. Повторна підготовка на foreground через
Task 2 для чинних subscriptions; її scope має завершуватись/скасовуватись за lifecycle.

- [ ] Failing tests: Failure → saveCount=0; Ready → saveCount=1; cancellation → saveCount=0 та CancellationException назовні; save failure не позначається успішною підпискою.

```kotlin
var saves = 0
val coordinator = SurgeVoicePreparationCoordinator { _, _ -> VoicePreparation.Failure("uk_unavailable") }
assertEquals(VoicePreparation.Failure("uk_unavailable"), coordinator.enable(17, "Чоп") { saves++ })
assertEquals(0, saves)
```

- [ ] Запустити RED, реалізувати coordinator і підключити його перед setSubscription для увімкнення активного відстеження. Вимкнення/видалення не чекає TTS. На foreground отримати каталог/subscriptions через чинний repository і відновити WAV; паралельний refresh використовує deduplicated prepare. ENABLE_PUSH=false не створює production installation.
- [ ] Залишити статус «Відстежується», наявну кнопку видалення з підтвердженням, max5, теми й верхній опис. Додати короткі voice_not_ready/voice_sound_changed/queue/deadline причини до чинного рядка проблеми. ACK/cancel/reconcile використовують ті самі service hooks і durable ACK worker.
- [ ] GREEN tests, compile/lint; QA: додавання при відсутньому українському TTS, cancel підготовки, відновлення наявних підписок після втрати файлів. Commit із provenance/readiness.

## Task 6: CI, кандидат на телефоні та справжній FCM

**Files:** modify QA Activity/probes зі списку файлів, `scripts/verify_push_qa.py`,
`docs/ANDROID-PROVENANCE.json`, `docs/RELEASE-READINESS.md`; create
`docs/audits/ANDROID-SYSTEM-VOICE-PHONE-2026-10-04.md` для фактичного сценарію.
Локальні FCM plan/ledger/receipts — `dist/phone-system-voice-qa/`, без секретів у Git.

**Interfaces:** QA default Application, окремий package pushqa, без API registration,
server ACK чи production subscriptions. Використовує ті самі assets/provider/service
й локальний ACK. Private token передається лише SSH stdin, ніколи command/log.

- [ ] Оновити QA preparation для погоджених CP IDs/назв до показу readiness; token-ready не означає voice-ready. Debug-only receiver використовує чинний parsing/claim/delivery для локальних сценаріїв; release його не містить.
- [ ] Повний прогін із JDK17/SDK36: `gradlew.bat -PavelrenUiPreview=true :app:testDebugUnitTest :app:lintDebug :app:assembleDebug --no-daemon --max-workers=2`; штатні scripts verify_android/verify_ci_scopes/verify_core_provenance. Push QA fixture compile/manifest: за чинним README і verify_push_qa.py; fixture APK не встановлювати.
- [ ] Переглянути всю гілку за requesting-code-review; виправити actionable findings, push PR, дочекатись усіх відповідних CI точного head. Злити після приймання коду; зібрати QA APK з чистої main й звірити установлене SHA-256.
- [ ] Підготувати конкретний FCM TEST-PLAN: новий QA client, максимум 8 target-only high-priority data messages, TTL120, bounded ledger, stop-on-fail і cleanup. До зовнішніх записів отримати новий явний дозвіл за AGENTS.md. Робочу БД/реєстрацію не змінювати.
- [ ] Матриця справжнього FCM: фон, duplicate, факт після прогнозу, ACK/наступний повтор, locked, кілька КПП. Media0 перевіряти Android API; власник підтверджує чутність. Будь-який непідтверджений сценарій лишити неприйнятим.
- [ ] Cleanup лише створених QA package/client; перевірити фактичну відсутність/DELETED. Записати commit/version/SHA/date/results у readiness. Публікація GitHub1.0.3 і Play — після повного реєстру й погодженого власником опису, окремими діями.

## Виконання і межа готовності

Власник раніше обрав виконання агентом у цій сесії; цей спосіб зберігаємо.
План потребує review перед кодом. Компоненти залежать від єдиних assets і
notification identity, тому реалізація послідовна. Окремий review всієї
гілки проводиться перед інтеграцією; probe gate не замінює product phone QA.

Результат цього плану — перевірений Android-кандидат і чесні записи приймання.
Якщо FCM/OEM або media0 перевірка не пройшла, релізна готовність голосу
лишається відкритою, а наступне виправлення спирається на збережений receipt.
