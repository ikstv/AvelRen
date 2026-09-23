# Перелік для перенесення серверної частини

Уже перенесено collector, notifier та спільні залежності,
разом із трьома незмінними наборами unit-тестів. Точне відображення шляхів
і SHA-256 — у [CORE-PROVENANCE.json](CORE-PROVENANCE.json), інструкції —
у [README серверного ядра](../services/backend/README.md). Решта цього
документа описує план блоків, а не дозвіл на розгортання.
Також додано [БД](../db/README.md) та [API/Admin](API-TRANSFER.md).
Перевірені серверні копії [watchdog і snapshot](WATCHDOG-TRANSFER.md)
перенесено окремим блоком; відомі недоліки не оголошені виправленими.
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

Станом на 2026-09-23, PR #2 злитий у `main` комітом
`9dddad1403fcddabb01c5d3a4ed72e617538851f`. На його перевіреному head
успішними були core та database. На production collector і notifier
збігаються з `CORE-PROVENANCE.json`; у журналі БД лише міграції 001–009,
їхні хеші збігаються з `DB-PROVENANCE.json`. Міграції 010 і 011 не
застосовані.

Після злиття PR #2 гілку PR #3 синхронізовано з `main` merge-комітом
`43c27c82bd47b763aa72bb507fca41e1343138a7`. На цьому кодовому head усі
чотири GitHub Actions успішні (API/Admin, core, database,
watchdog/telemetry). Подальший commit `1c311dc3b451b1dcf2ad9c4a796d7dca4c0f7fa7`
оновив документацію результатів; він не змінював код.

Read-only порівняння фактичних production-файлів і кандидата PR #3 завершено
23 вересня 2026 року. Production API SHA-256:
`48c0839dd57ac8a67194843dd1da3875e9f5a9a6a66dd2007f9835562d1466a8`;
кандидат API:
`67c4db7a7cd5f53a489e241acdd9a442dcdd9553d633befc3fcc101615af2d72`.
Обробники маршрутів збігаються; кандидат додає імпорт і реєстрацію
`admin_access_router`.

Production watchdog SHA-256:
`85bd832bec5bd71d4c301f5fc73d2364966e52fd0641c3b64f5548b4050dee2d`;
кандидат watchdog:
`7736727fdeb4c6c29985baf6f3d72fbbb4cb534d4200b1930e2b0fd0d983c1e4`.
Цикл, основні перевірки, відновлення та доставка звіту зберігають поточну
політику: лише щоденний звіт, без миттєвих FCM про інцидент або відновлення.
Кандидат додає advisory lock, перевірки свіжості/цілісності snapshot і
звіту, а також параметри доставки, щоб новий щоденний звіт замінював
застарілий у черзі. SHA-256 production telemetry snapshot
(`577aa6c1b213174f2ef1a6211a5047a96aeed36f188cdd00cffa0f37ad731966`)
збігається з `EXPECTED_SNAPSHOT_SHA` кандидата.

PR #188 (`fix/prod-observability-cleanup`) перевірено окремо: його старі
миттєві FCM сповіщення про проблеми/відновлення не перенесені. Детальний
опис файлів і контрольні суми — в [аудиті production](PRODUCTION-AUDIT.md).
PR #3 залишається draft і не злитий; цей огляд не змінював production.

Production checkout лишається на `81e5b047f8f18c42ca46a59f86495f71d0681af0`.
Дві змінені tracked-версії (watchdog.py та telemetry-snapshot.sh) і три
резервні файли збережені; перелік наведено в `PRODUCTION-AUDIT.md`. У цій
синхронізації production не змінювався, міграції та SQL-записи не виконувалися.
Backup/restore та повні експлуатаційні процедури ще не перенесені.
