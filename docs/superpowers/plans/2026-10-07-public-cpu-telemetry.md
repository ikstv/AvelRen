# План реалізації публічної CPU-телеметрії

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Показувати виміряний CPU у загальнодоступному екрані «Сервер» з ручним оновленням.

**Architecture:** Host snapshot вимірює CPU незалежно від телефонів. Вузький GET читає готовий JSON. Android отримує дані лише при відкритті вкладки та натиску «Оновити».

**Tech Stack:** Bash/awk, Python/FastAPI, Kotlin/Compose; без нових залежностей.

**Spec:** [Погоджений дизайн](../specs/2026-10-07-public-cpu-telemetry-design.md).

## Global Constraints

- CPU 0–100 або null; freshness 300 секунд, майбутній timestamp недовірений.
- sample_seconds=1; guest не додається до total вдруге; idle/iowait не busy.
- ROAD SIGN #0E7A4E → #F5C400 → #D5382C; статичне слабке світіння.
- Запит при відкритті та ручне оновлення; кнопка 48dp, без polling/retry.
- Застосовані міграції, єЧерга, collector, приватні admin endpoints незмінні.
- APK лише з чистої main; deployment, Play і офіційний пакет поза цим планом.

## Review Focus

- Некоректний JSON верхнього рівня або system: endpoint відповідає недоступністю, не падає; Task 2.
- CPU рівно 0, bool/NaN/Infinity: нуль є валідним, решта не є числом CPU; Task 2/3.
- Probe після вимірювання триває довше хвилини: дата CPU не підміняється кінцем probe; Task 1/2.
- Повторний швидкий натиск і вихід з екрана: немає паралельних запитів чи поглинання cancellation; Task 3.
- Великий шрифт/довгий текст помилки: час, кнопка й статус доступні без обрізання; Task 3 + телефонне приймання.

### Task 1: CPU у штатному host snapshot

**Files:** `ops/telemetry-snapshot.sh`, `services/backend/tests/snapshot/test_snapshot.py`,
`services/backend/src/avelren/watchdog.py`, `docs/WATCHDOG-PROVENANCE.json`.

**Interfaces:** Produces system.cpu_percent, system.cpu_measured_at, system.cpu_sample_seconds.
Спільний collected_at та решта полів не змінюють значення. CPU probe читає
агрегований /proc/stat двічі; тестовий шлях AVELREN_CPU_STAT дозволяє FIFO-фікстуру.

- [ ] Написати тести повного справжнього snapshot у чинному ізольованому harness.
  FIFO-фікстура подає два рядки cpu без sleep гонок: перше й друге відкриття
  отримують відповідні рядки. Вхід (user,nice,system,idle,iowait,irq,softirq,steal)
  100,0,100,800,0,0,0,0 → 130,0,120,850,0,0,0,0 дає 50.0;
  idle +100 дає 0.0; user +100 дає 100.0; iowait +100 дає 0.0.
  Окремо guest дублювання, нечисловий рядок, від’ємні дельти та total=0 → null.
  Перевірити UTC cpu_measured_at перед завершенням повільного mocked probe.
- [ ] Запустити `bash scripts/test_database.sh watchdog`: побачити падіння нових CPU assertions.
- [ ] Додати мінімальний awk-розрахунок у snapshot, 1-second інтервал і окремий
  timestamp завершення CPU probe; невдалий CPU probe не скасовує весь знімок.
  Синхронізувати EXPECTED_SNAPSHOT_SHA watchdog та походження змінених файлів.
- [ ] Повторити watchdog suite, повний backend unit suite, ruff, provenance і bash -n.
- [ ] Зафіксувати коміт українською разом із записом readiness; без встановлення скрипта на сервер.

### Task 2: Вузький публічний GET

**Files:** `services/backend/src/avelren/telemetry.py`, `services/backend/src/avelren/api.py`,
new `services/backend/tests/unit/test_public_cpu.py`, `docs/API-PROVENANCE.json`,
`docs/WATCHDOG-PROVENANCE.json`.

**Interfaces:** `telemetry.public_cpu_status(now: datetime) -> dict` споживає поля Task 1.
`GET /server/status` у FastAPI app (зовнішній /api/server/status) викликає read rate gate
та повертає JSONResponse із Cache-Control: no-store. Відповідь рівно
cpu_percent, measured_at, sample_seconds, stale; немає БД чи subprocess.

- [ ] Написати fixture-тести: now=2026-10-07T12:00:00Z, вимірювання
  11:59:00Z/cpu=0/sample=1 → 0, той самий timestamp, 1, false.
  Age=300 валідний; 301, future, timestamp без zone, missing/null/non-object →
  cpu=null/stale=true. CPU bool/NaN/Infinity/<0/>100 відхиляються.
  Snapshot із секретоподібними додатковими полями дає лише чотири дозволені ключі.
  ASGI-тест без lifespan реальної БД перевіряє GET без admin credentials,
  no-store та відсутність звернень до БД/host probe (забороняючі doubles).
- [ ] Запустити `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q`;
  підтвердити падіння нових tests до реалізації.
- [ ] Реалізувати нормалізацію знімка і endpoint; додавати/перейменовувати admin telemetry не потрібно.
- [ ] Повторити повний unit suite, ruff, provenance, контрактні API suites через
  `bash scripts/test_database.sh api` у тимчасовому Docker-проєкті без production volumes.
- [ ] Зафіксувати коміт і обмеження старого сервера (404), без deployment.

### Task 3: Публічний екран CPU

**Files:** `apps/android/app/src/main/java/ua/avelren/app/data/Api.kt`,
`apps/android/app/src/main/java/ua/avelren/app/ui/AdministrationScreen.kt`,
new `apps/android/app/src/main/java/ua/avelren/app/ui/ServerStatusContent.kt`,
new `apps/android/app/src/main/java/ua/avelren/app/ui/ServerStatusPresentation.kt`,
`apps/android/app/src/preview/java/ua/avelren/app/PreviewActivity.kt`,
new `apps/android/app/src/test/java/ua/avelren/app/ui/ServerStatusPresentationTest.kt`,
`docs/ANDROID-PROVENANCE.json`, `docs/RELEASE-READINESS.md`.

**Interfaces:** `Api.ServerCpuStatus(cpu_percent: Double?, measured_at: String?,
sample_seconds: Int?, stale: Boolean = true)`;
`Api.serverCpuStatus(): ServerCpuStatus` викликає GET /server/status.
`AdminServerClient.serverCpuStatus(): Api.ServerCpuStatus` замінює UI-виклик
activeDevices; legacy Api.activeDevices endpoint лишається для сумісності.
`serverStatusPresentation(status, now: Instant)` визначає довіру/дату/значення;
UI використовує саме його, без мережі у formatter.

- [ ] Написати тести parsing/presentation з literal fixtures 0/50/100/null/404,
  stale/time rollover Kyiv; 0% не губиться, age>300/future не виглядають свіжими.
  Для request state використати ін’єктований реальний coroutine state holder,
  якщо він потрібен UI: два конкурентні refresh дають один запит, cancellation
  перевикидається, помилка позначає попередні дані неоновленими.
- [ ] Запустити preview testDebugUnitTest: побачити нові failing assertions.
- [ ] Реалізувати окремий ServerStatusContent, статичний gradient і світіння,
  label «Стан сервера», час поруч із 48dp «Оновити» у FlowRow.
  Замість активних пристроїв показувати CPU. Меню/заголовок «Для адміна»;
  public вкладка та Admin auth залишаються незалежними. LaunchedEffect лише
  початковий, без циклу/retry; font scale не обмежувати. Preview synthetic 37%.
- [ ] Повні offline JVM/compile/lint, verify_android, provenance та незалежний review.
- [ ] GitHub PR, зелений точний CI, погоджена інтеграція. Clean-main APK,
  сигнал перед install, readback, телефонні 100/130/200% в обох темах,
  0/50/100/null/stale/error через preview fixtures. Фіксувати фактичні результати.

## Приймання плану

Спосіб виконання: native (агент реалізує кроки сам, один незалежний review
повної гілки); зберігає раніше обрану власником модель роботи.
Перед реалізацією власник переглядає та погоджує цей план.
