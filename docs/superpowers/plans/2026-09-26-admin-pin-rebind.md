# Admin-вхід за PIN після перевстановлення — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Нова інсталяція входить до Admin за чинним PIN, переносить єдине право на себе; три спільні помилки блокують вхід на 30 днів.

**Architecture:** Міграція 014 додає вузьку SECURITY DEFINER функцію атомарного перенесення. API перевіряє PIN і спільний lock під транзакційним блокуванням, Android відображає вже наявні стани ready/authorized/blocked.

**Tech Stack:** PostgreSQL/TimescaleDB, Python/FastAPI/psycopg/pytest, Kotlin/Compose/JUnit, Docker Compose.

**Spec:** docs/superpowers/specs/2026-09-26-admin-pin-rebind-design.md

## Global Constraints

- Не редагувати застосовані міграції 001–013; додати 014.
- Чинний PIN має рівно чотири ASCII цифри і hash scrypt-v1.
- Три неправильні спроби сумарно для всіх інсталяцій; lock рівно 30 днів від третьої.
- Перенесення тільки на автентифіковану інсталяцію з FCM-токеном; максимум один Admin.
- Немає прямого UPDATE approval/is_admin для API-ролі, секретів у Git або PIN у логах.
- Тести не звертаються до єЧерги; production deployment тільки після окремого дозволу.

## Review Focus

- Кандидат втратив FCM-токен перед правильним PIN: право не переноситься; тест у Task 2.
- Два паралельні правильні PIN на різних інсталяціях: не виникають два Admin; тест у Task 2.
- Третя помилка й правильний PIN майже одночасно: row lock зберігає визначений порядок; тест у Task 3.
- API-код 014 запущено на схемі 013: нова інсталяція не отримує PIN-вхід; тест у Task 3.
- Старий 24-годинний блок конкретного пристрою: правильний PIN не обходить його; тест у Task 3.

---

### Task 1: Тривалість спільного блокування

**Files:** Modify `services/backend/src/avelren/admin_pin.py`; test `services/backend/tests/unit/test_admin_pin.py`.

**Interfaces:** `evaluate_attempt(failures: int, locked_until: datetime | None, now: datetime, matches: bool) -> Attempt`; `LOCK_DURATION = timedelta(days=30)`.

- [ ] Додати failing tests: третя помилка дає `now + timedelta(days=30)`; повтор і правильний PIN до дедлайну повертають незмінний `blocked`; після дедлайну лічильник знову починається з першої помилки.
- [ ] Запустити `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_admin_pin.py -q`; очікувати FAIL на 24-годинному строку.
- [ ] Змінити тільки `LOCK_DURATION` у `admin_pin.py`; повторити команду до PASS.
- [ ] Коміт `fix(admin): блокувати PIN-вхід на 30 днів`.

### Task 2: Атомарне перенесення права в БД

**Files:** Create `db/migrations/014_admin_pin_rebind.sql`; modify `services/backend/src/avelren/schema_verify.py`; test `services/backend/tests/database/test_migrations.py`, `services/backend/tests/database/test_permissions.py`, `services/backend/tests/database/api/test_admin.py`.

**Interfaces:** `public.activate_admin_after_pin(candidate uuid) RETURNS void`. Викликає тільки API після `verify_pin`; функція сама перевіряє глобальний lock, `devices.admin_blocked_until`, наявність FCM і переносить `approved_device_id` та `is_admin` в одній транзакції. `014_admin_pin_rebind` належить до `FEATURE_MIGRATIONS`.

- [ ] Додати failing DB tests: функція відсутня на 013; після 014 має owner=migrator, SECURITY DEFINER, безпечний search_path, EXECUTE лише API; API не має прямого UPDATE. Backup читає всі таблиці. Без FCM/під чинним lock відмова без змін. Два конкурентні перенесення лишають одного Admin.
- [ ] Запустити `bash scripts/test_database.sh`; очікувати FAIL нових тестів.
- [ ] Додати 014 і contract у `schema_verify.py`; перевірити `verify_contract` на префіксі 013 та повній 014.
- [ ] Повторити `bash scripts/test_database.sh`; очікувати PASS.
- [ ] Коміт `feat(db): додати атомарне перенесення Admin після PIN`.

### Task 3: API входу без попереднього схвалення

**Files:** Modify `services/backend/src/avelren/admin_access_api.py`; test `services/backend/tests/database/api/test_admin.py`, `services/backend/tests/database/api/test_production_009.py`.

**Interfaces:** `access(device_id: str, pin: str | None = None) -> AccessOut` лишається незмінним; GET повертає `ready` для нової інсталяції з FCM на 014, POST викликає `activate_admin_after_pin` лише після успішного `verify_pin`.

- [ ] Додати failing API tests: GET нового ID не змінює БД; неправильний PIN збільшує спільний failures; третя помилка блокує всіх на 30 днів; правильний переносить право/FCM-адресата; конкуренція третьої помилки й правильного PIN серіалізується; чинний installation lock не обходиться; схема 013 з новим API лишається fail-closed.
- [ ] Запустити `bash scripts/test_database.sh`; очікувати FAIL нових тестів.
- [ ] Оновити `access` із збереженням `_device`, row lock і станів відповіді; не виводити PIN або credentials у логи.
- [ ] Повторити `bash scripts/test_database.sh` та `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q`; очікувати PASS.
- [ ] Коміт `feat(api): дозволити повернення Admin за PIN`.

### Task 4: Android-контракт і реєстр приймання

**Files:** Modify `apps/android/app/src/test/java/ua/avelren/app/data/AdminAccessTest.kt`, `docs/RELEASE-READINESS.md`; inspect `apps/android/app/src/main/java/ua/avelren/app/ui/AdministrationScreen.kt`.

**Interfaces:** Наявний UI показує PIN для відповіді `ready`; API повертає `ready` новій інсталяції після 014. Нових Android credentials або сховища PIN немає.

- [ ] Звірити, що наявний `AdministrationScreen.kt` уже показує PIN для `ready` і `blocked` із серверним строком; змінювати UI лише якщо це не так.
- [ ] Додати до `AdminAccessTest.kt` перевірку відповіді `ready` для нового ID та чинного POST з PIN тільки в тілі запиту.
- [ ] Запустити з `apps/android`: `bash gradlew -PavelrenUiPreview=true :app:testDebugUnitTest :app:compileDebugKotlin --no-daemon --max-workers=2`; очікувати PASS.
- [ ] Оновити RELEASE-READINESS з окремими станами код, CI, deploy, APK, телефон, Play; не позначати телефон як перевірений до фактичного сценарію.
- [ ] Запустити `python scripts/verify_android.py`; коміт `test(android): зафіксувати PIN-вхід нової інсталяції`.
### Task 5: Інтеграційна звірка гілки

**Files:** За потреби лише тести/документація названих задач.

**Interfaces:** Результат задач 1–4 на точному head гілки.

- [ ] Запустити unit, database, Android та repository scope/provenance перевірки для змінених шляхів; зафіксувати точні результати.
- [ ] Перевірити `git diff --check`, `git status`, міграцію 014 і відсутність секретів у diff.
- [ ] Підготувати PR з ризиком 30-денного глобального блокування і планом production rollback; не розгортати без окремого GO.
