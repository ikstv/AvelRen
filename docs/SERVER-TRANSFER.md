# Перелік для перенесення серверної частини

Перший блок уже перенесено: collector, notifier та спільні залежності,
разом із трьома незмінними наборами unit-тестів. Точне відображення шляхів
і SHA-256 — у [CORE-PROVENANCE.json](CORE-PROVENANCE.json), інструкції —
у [README серверного ядра](../services/backend/README.md). Решта цього
документа описує план наступних блоків, а не дозвіл на розгортання.
Повний [перелік файлів із SHA-256](SERVER-FILES.csv) обчислено з Git blobs
коміту `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` репозиторію
`ikstv/AvelRen`. Він відтворюваний незалежно від переносу рядків Windows.
Це зафіксована база аудиту, а не твердження про найновіший GitHub main.

## Джерела

| Джерело | Як використовуємо |
| --- | --- |
| AvelRen, коміт `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` | Базові файли й тести, пофайловий перелік у CSV |
| AvelRen-ops, коміт `5be9da8b433813a664b4d4e21a0a92bae91c56a0` | INTEGRATION.md, deploy/*.md, docs/restore*.md, disaster-recovery.md; переклад і актуалізація процедур |
| Production checkout `81e5b047f8f18c42ca46a59f86495f71d0681af0` з ручними змінами | Доказ фактичної поведінки за PRODUCTION-AUDIT.md, не готова версія для копіювання |
| Локальна робоча папка | Зберегти незавершені зміни, розібрати окремо; не використовувати як базову версію |

CSV містить контрольні суми вихідних файлів Git. Колонка production_match
навмисно не стверджує нової звірки з сервером: попередні результати й їхня
дата наведені в [аудиті](PRODUCTION-AUDIT.md). Перед перенесенням production
варіантів потрібне отримання точного вмісту та повторна перевірка SHA-256.

## Рішення за компонентами

| Файли від кореня старого репозиторію | Рішення і перевірки |
| --- | --- |
| app/src/avelren/{collector,echerha,config,models,db}.py | Зберегти поведінку єЧерги; test_echerha, test_collector_config, test_db_timeout, перевірка запису циклів із підміною HTTP |
| app/src/avelren/{alerts,cancels,eta,fcm,notifier,limits}.py | Перенести залежності разом; відповідні tests/test_*.py, без реальних push |
| app/src/avelren/{api,subscriptions_api,schemas,ratelimit}.py | Узгодити залежність від нового Admin та схеми; API/auth/resource-bounds тести |
| app/src/avelren/watchdog.py, deploy/telemetry-snapshot.sh | Об'єднати main, #188 та останні production-зміни; тести звіту, помилок доставки, часу Києва та повторних запусків |
| app/src/avelren/admin_*.py, release_notice.py | Окремий блок із 011_admin_access, admin_tests та unit_tests; production ще не містить цієї функціональності |
| app/src/avelren/{migrate,schema_gate,schema_verify}.py, db/ | Узгодити фактичну схему 009, застосовані хеші та порядок наступних міграцій; adoption/schema/privilege тести |
| app/src/avelren/forecast.py | Зберегти базову модель; виправлення MAE та #185 виділити після перенесення, не підміняти вимірювання прогнозом |
| app/src/avelren/restore_*.py, deploy/restore*, deploy/backup* | Перенести з контрактами, перевірити на окремому Compose-проєкті без production volumes |
| app/Dockerfile*, pyproject.toml, requirements.lock, docker-compose*.yml | Єдина відтворювана збірка спільного Python-пакета; нові шляхи перевірити в ізольованому середовищі |
| deploy/Caddyfile, deploy/PROD_PIN, systemd units | Історичні конфігурації, потрібна звірка ефективного стану; pin не копіювати як нову істину |
| .github/, scripts/ | Адаптувати до нової структури й залежностей; зберегти потрібні перевірки БД та restore |

Для першого кроку з кодом зберігаємо спільний пакет `avelren` в
`services/backend/`. Collector, notifier, API і watchdog не розриваємо
на окремі пакети: вони мають спільні залежності й Docker-образ.
Міграції залишаються в `db/`, експлуатаційні сценарії — в `ops/`.
Переміщення вимагає перевірки COPY, mounts, шляхів тестів і CI.

## Варіанти, які не можна загубити

- Production watchdog: останній записаний SHA-256
  `85bd832bec5bd71d4c301f5fc73d2364966e52fd0641c3b64f5548b4050dee2d`.
- Production telemetry: останній записаний SHA-256
  `577aa6c1b213174f2ef1a6211a5047a96aeed36f188cdd00cffa0f37ad731966`.
- Локальні зміни migrate.py, schema_verify.py, watchdog.py, трьох тестів,
  postgres-adoption-bootstrap-topology-test.sh, postgres-ownership.lib.sh,
  restore-engine.lib.sh та 011_daily_admin_reports.sql залишаються окремою
  альтернативою, не прийнятою реалізацією.
- Чотири варіанти 011 і перетини PR описані в AUDIT.md. Застосовані
  міграції не редагувати; невпроваджені варіанти не зливати автоматично.

## Межа готовності — контрольна звірка 23 вересня 2026 року

Collector/notifier і міграції 001–011 перенесено до гілки codex/server-core-db
у PR #2. Походження та SHA-256 файлів записані у provenance-маніфестах.
PR #2 ще не злитий; main поки містить документацію й інструменти доступу.

Production checkout лишився на 81e5b047f8f18c42ca46a59f86495f71d0681af0.
Production collector і notifier збігаються з CORE-PROVENANCE.json. БД має
лише 001–009; усі дев'ять SHA-256 збігаються з DB-PROVENANCE.json. Міграції
010 і 011 присутні в гілці для ізольованої перевірки, але не застосовані
на production.

Production watchdog має SHA-256
85bd832bec5bd71d4c301f5fc73d2364966e52fd0641c3b64f5548b4050dee2d.
Кандидат watchdog у PR #3 має інший SHA-256
7736727fdeb4c6c29985baf6f3d72fbbb4cb534d4200b1930e2b0fd0d983c1e4.
Production API має SHA-256 48c0839dd57ac8a67194843dd1da3875e9f5a9a6a66dd2007f9835562d1466a8;
API у PR #3 — 67c4db7a7cd5f53a489e241acdd9a442dcdd9553d633befc3fcc101615af2d72.
Перед злиттям PR #3 потрібно звірити ці зміни з production і збереженими
варіантами PR #188. Після окремої перевірки та злиття PR #2 оновити основу
PR #3 та розв'язати його конфлікти.

CI на commit f6a3eed2fee80466edcbe815d385b5f942663982: core і database
успішні. У тестовому сценарії вимкнено Timescale telemetry лише в
ізольованому контейнері: фоновий telemetry worker інколи заважав прибрати
тимчасову БД. Локальний Docker-прогін дав 15 passed; database job GitHub
також успішний.

Під час читання на сервері всі шість контейнерів були запущені, PostgreSQL
мав стан healthy. У production checkout лишаються дві змінені tracked-версії
(watchdog.py, telemetry-snapshot.sh) і три невідстежувані резервні файли;
їх збережено. Перелік є в PRODUCTION-AUDIT.md.

Ця звірка не виконувала розгортань чи SQL-записів. Вона не дозволяє
застосовувати міграції, прибирати локальні файли або змінювати production.
Наступний маленький крок — окремо завершити перевірку й злиття PR #2;
потім узгодити PR #3 з фактичним watchdog/API сервера.
