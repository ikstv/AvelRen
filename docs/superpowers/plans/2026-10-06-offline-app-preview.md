# План реалізації офлайн-копії AvelRen

> **Для виконавця:** використовувати superpowers:executing-plans, послідовно в цій сесії.

**Мета:** спільна продуктова навігація та екран прогнозу в ізольованому тестовому APK.

**Архітектура:** передавати клієнти даних у спільні Compose-екрани.
Продуктові адаптери делегують чинним API й installation, preview-адаптери
живуть тільки в src/preview. UI не дублюється.

**Стек:** Kotlin, Compose, coroutines, JVM tests, Gradle/JDK17/SDK36.

**Дизайн:** [погоджена специфікація](../specs/2026-10-06-offline-app-preview-design.md).

## Загальні обмеження

- ua.avelren.app.preview, «AvelRen — тест»; без INTERNET/Firebase/production ACK.
- Продуктові API, реєстрація, polling і дизайн не змінюють поведінки.
- APK на телефон лише після інтеграції в чистий main, з SHA readback.
- Production й офіційна інсталяція недоторкані; секрети не потрібні.
- Документація й описи комітів українською.

## Фокус перевірки

- Вихід/повернення в екран не скидає локальний вибір; перевірка в задачі 2.
- Офлайн помилка не знищує попередні налаштування; перевірка в задачі 2.
- ACK не запускає server worker у preview; перевірка в задачі 1.
- Шостий КПП не додається; перевірка в задачі 2.
- Великий шрифт не приховує кнопки й нижню позначку; огляд у задачі 3.

## Задача 1: Ін'єкція клієнтів без зміни продуктового UI

**Файли:** створити data/AppScreenClient.kt, data/ProductionAppScreenClient.kt;
змінити ui/AvelRenScreen.kt, ui/ForecastOverviewScreen.kt;
створити test/.../data/AppScreenClientTest.kt.

**Інтерфейс AppScreenClient:** suspend workload(): List<Api.Workload>;
serverStatus(): PublicServerStatus; history(Int): Api.History;
forecast(Int): Api.Forecast; monitors(): Pair<List<Api.Subscription>, List<Api.EtaTarget>>;
subscribe(Int, Int): Unit; unsubscribe(Long): Unit;
createEtaTarget(Int, String): Unit; deleteEtaTarget(Long): Unit.
ProductionAppScreenClient приймає InstallationRepository та делегати API;
monitors отримує обидва списки в одному authenticatedCall, як чинний код.

AvelRenScreen приймає необов'язкові AppScreenClient, SurgeMonitorClient,
AdminAccessClient та callback enqueueSurgeAck: (Long) -> Unit.
Продуктові залежності створюються ліниво тільки за відсутності ін'єкції.
ForecastScreen отримує suspend loadForecast: (Int) -> Api.Forecast.
ForecastOverviewScreen використовує переданий ACK callback; стандартний
продуктовий callback лишає чинний SurgeAckWorker, preview передає no-op.
Стани реєстрації й credential gates лишаються продуктовими; preview
користується явно переданим локальним станом, не вигаданими credentials.

- [ ] RED: адаптер передає правильні ID/threshold/time; monitors публікує
  обидва результати разом, cancellation виходить назовні. Preview ACK
  викликає лише переданий callback і локально блокує потрібну подію.
- [ ] Запустити тести й підтвердити відсутню реалізацію/очікуваний FAIL.
- [ ] Реалізувати інтерфейс і замінити тільки прямі виклики даних;
  не переписувати Compose-верстку чи auth/recovery.
- [ ] GREEN: повний JVM suite, compileDebugKotlin; перевірити продуктову
  обробку помилок, 401 й cancellation. Оновити provenance змінених файлів.
- [ ] Коміт: «refactor: відокремити дані спільних екранів».

## Задача 2: Локальна модель й перемикач сценаріїв

**Файли:** src/preview/.../PreviewActivity.kt; створити
src/preview/.../PreviewAppClient.kt і PreviewScenario.kt;
test/.../preview/PreviewAppClientTest.kt. Налаштувати preview-only test source
у build.gradle.kts, якщо чинний source set не включає ці класи.

**Інтерфейси:** enum PreviewScenario { EMPTY, FORECAST, FACT, OFFLINE,
FIVE_CHECKPOINTS, FORECAST_UNAVAILABLE }; PreviewAppClient реалізує
AppScreenClient і SurgeMonitorClient, зберігає вибір/події в пам'яті;
setScenario(PreviewScenario): Unit замінює сценарій з явним reset.
Клієнт створюється один раз на activity, а не при кожній навігації.
Годинник передається як () -> Instant; expiry відносний до нього.

- [ ] RED: EMPTY без підписок; FIVE_CHECKPOINTS рівно 5, шостий відхиляється;
  FORECAST/FACT мають правильні kind; OFFLINE кидає локальну помилку без
  втрати вибору; remove видаляє тільки потрібний ID; reset відновлює fixture.
- [ ] Підтвердити FAIL, реалізувати локальну модель без HTTP клієнта.
- [ ] PreviewActivity відкриває спільний AvelRenScreen; debug-only панель
  перемикає сценарії й явно позначає тест. Admin/Play операції не удають успіху.
  Локальний ACK не планує WorkManager; перемикання не озвучує події.
- [ ] GREEN: повний JVM suite, preview lint/assemble та manifest перевірка:
  INTERNET і Firebase init/messaging відсутні, package окремий;
  release не містить preview панелі, fixture чи тестового launcher.
- [ ] Коміт: «feat: додати локальні сценарії тестового додатка».

## Задача 3: Приймання й доставка кандидата

**Файли:** apps/android/README.md, docs/ANDROID-PROVENANCE.json,
docs/RELEASE-READINESS.md; новий датований UI audit; локальний dist/BUILD.txt.

- [ ] Запустити з apps/android: gradlew.bat -PavelrenUiPreview=true
  :app:testDebugUnitTest :app:lintDebug :app:assembleDebug --no-daemon --max-workers=2.
  Перевірити provenance/CI guards штатними scripts.
- [ ] Review змін, PR з обмеженнями; дочекатися CI точного head.
- [ ] Після інтеграції зібрати preview з чистого main, записати commit/SHA/date.
- [ ] Встановити поруч із Play-додатком; pull base.apk і звірити SHA.
- [ ] На телефоні перевірити всі сценарії, головну/моніторинг/налаштування,
  Back, прокручування, великий шрифт. Перевірити відсутність network permission
  і server ACK workers; результати записати окремими PASS/FAIL.
- [ ] Позначити готовність тільки фактично прийнятих сценаріїв. GitHub/Play
  release не входять до цього кроку.

## Межа виконання

Власник обрав виконання агентом у поточній сесії. Перед реалізацією
перевіряє цей план; за виявлення нового auth/API контракту зупинити відповідний
блок і уточнити дизайн. Не підміняти відсутні телефонні докази JVM PASS.
