# План реалізації публічної телеметрії ресурсів

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Чотири достовірні смужки CPU/RAM/Disk Memory Usage/Traffic Usage без опитування провайдера телефонами.

**Architecture:** Розширити наявний host snapshot і вузький public endpoint. Місячний трафік отримує незалежний погодинний серверний збирач із read-only доступом Hetzner; API читає його атомарний знімок. Кожен ресурс має власну свіжість.

**Tech Stack:** Python, Bash/systemd, FastAPI, Kotlin/Compose, pytest та offline Gradle; без нового ML чи великих залежностей.

**Spec:** `docs/superpowers/specs/2026-10-07-public-resource-telemetry-design.md`.

## Global Constraints

- RAM/disk застарілі після 300 секунд; traffic — після двох годин або невідповідності поточному підтвердженому розрахунковому періоду.
- Один запит при відкритті вкладки, наступні лише вручну. Автоопитування телефоном немає.
- Значення 20 ТБ не вшивати в код. Токен не потрапляє в Git, APK чи API.
- Гілку не зливати; production/timer/token не встановлювати без окремого GO.
- APK для телефона тільки з чистої main після окремого погодження інтеграції.
- Чужий untracked дизайн від 06.10 не включати в коміти.

## Review Focus

- Частково старий snapshot: CPU працює, нові ресурси недоступні (задача 2).
- Резерв ext4: used не дорівнює total−available (задача 1).
- Перехід місяця без нового знімка: старий traffic не видається за поточний (задача 3).
- Ручне оновлення без мережі: всі старі ресурси явно неоновлені (задача 4).
- Квота перевищена: число >100%, смужка повна червона, без переповнення (задачі 2–4).

## Задача 1: Точні обсяги host snapshot

**Files:** `ops/telemetry-snapshot.sh`, `services/backend/tests/snapshot/test_snapshot.py`, `docs/WATCHDOG-PROVENANCE.json`.

**Interfaces:** Нові system поля `memory_total_bytes`, `memory_used_bytes`, `disk_total_bytes`, `disk_used_bytes`; вимірювання датовані наявним `collected_at`. Legacy поля зберегти.

- [ ] RED: додати фікстуру MemTotal=4096 kB, MemAvailable=1024 kB; assert total=4194304, used=3145728. Для df total=1000, used=400, available=500 блоків assert used=409600, не 512000. Невалідні probes дають null.
- [ ] Запустити snapshot suite через штатний ізольований runner, підтвердити падіння саме нових assertions, не відсутність середовища.
- [ ] Додати точні поля без зміни timer, існуючих полів та CPU-вікна.
- [ ] GREEN: повторити snapshot suite, `bash -n ops/telemetry-snapshot.sh` і provenance-перевірку; зафіксувати результати й коміт.

## Задача 2: Ресурсний public API

**Files:** `services/backend/src/avelren/public_resources.py` (new), `telemetry.py`, `api.py` поруч із ним; `services/backend/tests/unit/test_public_resources.py` (new), `test_public_cpu.py`, `docs/API-PROVENANCE.json`.

**Interfaces:** `resource_status(used: object, total: object, measured_at: object, now: datetime, max_age_seconds: int, allow_overage: bool = False) -> dict` повертає used_bytes/total_bytes/measured_at/stale. `public_resource_status(now: datetime) -> dict` у telemetry зберігає CPU top-level контракт і додає memory/disk/traffic; кожен блок має тільки whitelist поля. api route переключити на цей метод.

- [ ] RED: assert valid 0/100%; age=300 свіжий, 301 stale; bool/negative/zero-total/used>total/future/huge integer → null, stale. Traffic allow_overage=true приймає 110/100. Snapshot CPU-only залишає CPU незмінним; секретні поля не проходять.
- [ ] Запустити `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_public_resources.py services/backend/tests/unit/test_public_cpu.py -q`; очікувати нові failures.
- [ ] Реалізувати чистий validator і читання знімків; CPU функцію не ламати. Traffic без перевіреного джерела спочатку недоступний. Обмежити JSON розмір; malformed/read errors не дають 500.
- [ ] GREEN: full backend unit, ruff, provenance, `bash scripts/test_database.sh api` тільки disposable; коміт.

## Задача 3: Незалежне джерело місячного трафіку

**Files:** new `services/backend/src/avelren/traffic_snapshot.py`, `services/backend/tests/unit/test_traffic_snapshot.py`, `ops/avelren-traffic.service`, `ops/avelren-traffic.timer`, `ops/traffic-unit-contract-test.py`, `docs/PUBLIC-RESOURCE-TELEMETRY.md`; telemetry traffic reader із задачі 2.

**Interfaces:** `normalize_provider_traffic(server: dict, measured_at: datetime, billing_month: str) -> dict`; `write_atomic_snapshot(path: Path, payload: dict) -> None`; CLI `python -m avelren.traffic_snapshot`. Narrow snapshot містить used_bytes/total_bytes/measured_at/billing_month, без identity/secrets. CLI credentials із захищеного EnvironmentFile, provider API тільки server GET, fixed HTTPS origin.

- [ ] Read-only gate: офіційними джерелами підтвердити nullable outgoing_traffic/included_traffic і часові межі billing period. Без такого доказу реалізувати лише disabled/unavailable шлях; не винаходити UTC-місяць і не підміняти boot counters. Потребу токена зафіксувати без plaintext.
- [ ] RED: provider missing/null/invalid → unavailable; 110% валідно; зміна періоду → stale; 429/5xx/timeout зберігають попередній файл/час; атомарний write не залишає partial JSON; token/ID/IP відсутні в результаті та error logs.
- [ ] Запустити `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_traffic_snapshot.py -q`, зафіксувати RED.
- [ ] Реалізувати один fetch з timeout=15s, без retries; timer OnUnitActiveSec=1h, API не запускає збирач. Знімок у чинному read-only telemetry mount. У service заборонити записи поза telemetry directory, токен не монтувати в API.
- [ ] GREEN: unit, статичний systemd contract, public whitelist regression; документувати налаштування та rollback без виконання production; коміт. Заблокований provider gate не блокує RAM/disk.

## Задача 4: Чотири смужки Android

**Files:** `apps/android/app/src/main/java/ua/avelren/app/data/Api.kt`, `ui/ServerStatusContent.kt`, `ui/ServerStatusPresentation.kt`, `apps/android/app/src/preview/java/ua/avelren/app/PreviewActivity.kt`, відповідні `src/test/.../ServerStatusPresentationTest.kt`; new `ui/ResourceStatusPresentation.kt` і його test; `docs/ANDROID-PROVENANCE.json`, `docs/RELEASE-READINESS.md`.

**Interfaces:** nullable DTO `ServerResourceStatus(used_bytes: Long?, total_bytes: Long?, measured_at: String?, stale: Boolean = true, billing_month: String? = null)`; ServerCpuStatus додає nullable memory/disk/traffic з default=null. `resourceStatusPresentation(status: Api.ServerResourceStatus?, now: Instant, maxAgeSeconds: Long, traffic: Boolean = false)` повертає amountLabel/percent/fillFraction/timeLabel/unavailable. Fill clamp 0..1, percent не clamp для traffic.

- [ ] RED: CPU-only JSON сумісний; 0% видимий; RAM/disk binary ГіБ, traffic decimal ГБ/ТБ; null/stale/malformed timestamps нейтральні; 110% → fill=1; помилка refresh робить всі блоки неоновленими, cancellation і single-flight збережені.
- [ ] Запустити offline `:app:testDebugUnitTest` із `-PavelrenUiPreview=true`, підтвердити нові failing assertions.
- [ ] Реалізувати спільну смужку з чинними ROAD SIGN кольорами; підписи CPU/RAM/Disk Memory Usage/Traffic Usage. Обсяг переноситься при великому шрифті; власний час кожного ресурсу, traffic month. Spinner мінімум 400ms і haptics зберегти. Локальна expiry не виконує мережевих запитів.
- [ ] Додати явно тестові preview fixtures fresh/partial/stale/over-quota без live provider requests.
- [ ] GREEN: offline `:app:testDebugUnitTest :app:compileDebugKotlin :app:lintDebug`, provenance/verify_android; реєстр відокремлює code/CI/deploy/APK/phone/Play; коміт.

## Задача 5: Передача без злиття

- [ ] Self-review всієї гілки, один незалежний read-only review згідно requesting-code-review.
- [ ] Повторити пов’язані suite та `git diff --check`, переконатися у відсутності секретів/чужого файла.
- [ ] Push звичайним способом, відкрити draft PR, прикріпити до чату, звірити CI точного head. Зафіксувати реальні failures, не видавати пропущене за PASS.
- [ ] Зупинитися: не merge, не production, не APK. Надати власнику PR, перевірки та окремі рішення для provider credentials і встановлення на телефон.

## Приймання плану

Погоджений раніше спосіб — native: агент реалізує сам у цьому чаті,
після реалізації один незалежний review. Перед кодом власник підтверджує
цей письмовий план. Provider period/access перевіряється першим read-only
кроком; непідтверджені поля залишаються недоступними, решта задач триває.
