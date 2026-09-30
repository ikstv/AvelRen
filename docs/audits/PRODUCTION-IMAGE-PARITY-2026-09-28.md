# Звірка production-образів і джерел — 28 вересня 2026

## Походження та межі перенесення

Український переклад аудиту з приватного `ikstv/AvelRen-ops`,
PR [#1](https://github.com/ikstv/AvelRen-ops/pull/1), коміт
[`a952262420a3ba629db4f8c27befdd2e1ee6b2cb`](https://github.com/ikstv/AvelRen-ops/commit/a952262420a3ba629db4f8c27befdd2e1ee6b2cb).
Оригінальний шлях:
[`docs/audits/PRODUCTION-IMAGE-PARITY-2026-09-28.md`](https://github.com/ikstv/AvelRen-ops/blob/a952262420a3ba629db4f8c27befdd2e1ee6b2cb/docs/audits/PRODUCTION-IMAGE-PARITY-2026-09-28.md).
SHA-256 оригінального файла:
`d8e3aadd1dc75a76312cac7b5118415189b0586e741a65fb1cffc3209ce14401`.

Перенесено 30.09.2026 зі збереженням зафіксованих image IDs, revision labels,
комітів, шляхів і висновків. Переклад не є побайтовою копією оригіналу.
Це історичні докази стану 28.09, а не нова серверна перевірка 30.09.
Поточні залишки ведуться в [єдиному списку](../MIGRATION-REMAINING.md).

**Вікно огляду:** 28.09.2026, 15:34–15:45 UTC.

**Метод:** SSH лише для читання, метадані Docker і Git, один read-only запит
до `schema_migrations`. Не читали значення змінних середовища, журнали
застосунку чи рядки прикладних таблиць БД. Файли, образи, контейнери, служби
та об'єкти БД на production не змінювалися.

## Результат огляду

Хост відповідав; усі шість очікуваних контейнерів працювали. Контейнер БД
мав стан `healthy`; у кожного перевіреного контейнера лічильник перезапусків
дорівнював `0`. Це не повна функціональна перевірка: API, collector,
notifier, watchdog і Caddy не мають Docker healthcheck.

Production не є точним розгортанням образів із Compose-контракту
`AvelRen-ORIGINAL` зазначеної нижче бази. Він використовує старий checkout
`/opt/avelren` і локальні Compose overrides. Кілька запущених образів мають
revision labels із комітами, які є предками `AvelRen-ORIGINAL/main`, але це
окремі локальні збірки. Їхню тотожність CI candidate не доведено.
Образ collector не вдалося прив'язати до коміту або перевірити через його
старий image ID; змінний тег уже вказував на інший образ.

## Зафіксований стан хоста та схеми

- Хост: `avelren-Helsinki`; час спостереження `2026-09-28T15:34:36Z`.
- Uptime близько 20 годин; load average `0.06 / 0.10 / 0.09`.
- Кореневий диск: 26% зайнято, 9.3 GiB із 38 GiB; доступна RAM 2.9 GiB;
  використаний swap — 0.
- Контейнери: `avelren-api-1`, `avelren-watchdog-1`, `avelren-notifier-1`,
  `avelren-collector-1`, `avelren-caddy-1`, `avelren-db-1`; усі `running`,
  лічильники перезапусків `0`; стан БД `healthy`.
- Остання позначка застосованої схеми: `014_admin_pin_rebind`, така сама,
  як остання міграція перевіреного дерева `AvelRen-ORIGINAL`.

## Запущені образи та змінні теги

«Image ID запущеного контейнера» — ідентифікатор образу, з якого контейнер
створено, а не ID самого контейнера. «Image ID за тегом» — образ, на який
локальний тег указував під час огляду.

| Сервіс | Образ / тег запущеного контейнера | Image ID запущеного контейнера | Доказ походження | Image ID за тегом / результат |
| --- | --- | --- | --- | --- |
| API | `avelren-api:restart-badge-ae3302b` | `sha256:a5854182ec1d6acb983b39c59992c42cc0d08120e8ea1feca33935076acd445e` | OCI revision label `ae3302b1669add39a630cb4d4391838b97cd8a59`; коміт є предком перевіреного `AvelRen-ORIGINAL/main` | Той самий ID |
| Watchdog | `avelren-watchdog:daily-report-523eb92` | `sha256:a9ac9259374ceb3e9e29e856ea0909e0041646a2406b51a5b9981d42c1b9bd1d` | OCI revision label `523eb92b5282b056a6e4b5de241494e2dd58118e`; коміт є предком перевіреного `AvelRen-ORIGINAL/main` | Той самий ID |
| Notifier | `avelren-api:release-candidate-df7b42a` | `sha256:b71cc0b0ff30fc7d99a9a9822c5b61544d11ef3fadb3b03ebdf74c9f75a7bd60` | OCI revision label `df7b42a5af1b0c099242ffaf1632f364662c5ab1`; коміт є предком перевіреного `AvelRen-ORIGINAL/main` | Той самий ID |
| Collector | `avelren-app:latest` | `sha256:f52aad81baee447a5949df5d9371231ec62b7f1c095cba78cc3bfc3c633f568e` | Немає OCI revision label і `AVELREN_GIT_SHA` у середовищі контейнера. Контейнер створено `2026-09-06T09:46:00Z`. `docker image inspect` не знаходить цей image ID. Походження не підтверджено. | Тег указує на `sha256:978ec2d927b71b24eeac235742678b12c804f9d06f5b1e21d6254efc0e74f921`, створений `2026-09-22T17:16:39Z`; це інший образ |
| Caddy | `caddy:2.9.1-alpine` | `sha256:b4e3952384eb9524a887633ce65c752dd7c71314d2c2acf98cd5c715aaa534f0` | Digest pin старого Compose відповідає запущеному образу | Той самий ID; digest pin |
| БД | `timescale/timescaledb:2.17.2-pg16` | `sha256:4e459e217f00cbb09920c34d245501e63427e6767a495de57ce76823ff280f12` | Digest pin старого Compose відповідає запущеному образу; БД `healthy` | Той самий ID; digest pin |

Три revision labels застосункових образів окремо зіставили через GitHub із
`AvelRen-ORIGINAL/main`: кожен указаний коміт був його предком. Це доводить
наявність записаної revision у Git-історії, але не побайтову тотожність
окремо зібраного production-образу CI candidate чи відповідність його SBOM.

## Compose, checkout і міграційний pin

- Перелік фактичних Compose images прочитали через
  `docker compose config --images` із `/opt/avelren`, зі збереженням
  автоматичного підхоплення overrides. Розгорнуті значення змінних не виводили.
- API, collector, watchdog і Caddy використовують
  `/opt/avelren/docker-compose.yml` разом із
  `/opt/avelren/docker-compose.override.yml`.
- Notifier додатково використовує
  `/var/lib/avelren-release-check-20260924/deploy-013.yml`.
- Серверний checkout: гілка `main`,
  `HEAD=81e5b047f8f18c42ca46a59f86495f71d0681af0`.
  Його `deploy/PROD_PIN` містить
  `87cbac095c5e96f390ea475c2a9101bba3954267`.
- Перевірений GitHub main старого репозиторію:
  `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27`; його tracked `deploy/PROD_PIN`
  містить `254fd17b2b814d10c5455b9d0b5da823370253e6`.
  Отже, pin у старому GitHub main не описує pin робочого хоста.
- Перевірена база `AvelRen-ORIGINAL/main`:
  `01e467c0dcf711067c6b0afa831652e4b305060b`. Її Compose pin-ить TimescaleDB
  `2.30.1-pg16@sha256:f495f2bc…` та Caddy
  `2.11.4-alpine@sha256:6aeddd44…`; production залишався на `2.17.2` та
  `2.9.1`. Це source-кандидати, а не дозвіл оновлювати БД або proxy.
- У перевіреному дереві `AvelRen-ORIGINAL` немає `deploy/PROD_PIN`.
  Сервер ще не переведений на checkout цього репозиторію із зафіксованою
  deployment-ідентичністю.
- `git status` у `/opt/avelren` показав дев'ять записів: чотири змінені
  tracked-файли (`app/src/avelren/watchdog.py`, `deploy/restore-engine.lib.sh`,
  `deploy/static/privacy-policy.html`, `deploy/telemetry-snapshot.sh`) і п'ять
  untracked backup-файлів. Їхній вміст не читали й не змінювали.

## Висновки та передумови наступних дій

1. `avelren-app:latest` не описує працюючий образ collector: контейнер
   зберігає ID `f52…`, а тег указує на `978…`. Старий image object недоступний
   для огляду. Перед restart/recreate потрібні перевірене походження коду
   та спосіб відновлення.
2. Походження collector лишається непідтвердженим. Потрібно відновити запис
   збірки або незмінну ідентичність артефакту з deployment records/backups.
   Поточний тег і дата створення контейнера не визначають його коміт.
3. Застосункові образи не мають спільної незмінної release-ідентичності:
   API, watchdog, notifier і collector не є одним образом, вибраним через
   єдину tracked Compose-збірку. Майбутні deployment-докази мають містити
   точні image IDs.
4. Production використовує стару Compose-модель. До планування переходу
   на `AvelRen-ORIGINAL` потрібно звірити host overrides, додатковий файл
   notifier, dirty checkout і старий `PROD_PIN`.
5. Pins TimescaleDB та Caddy відрізняються. Upgrade потребує окремої
   recovery-репетиції, плану відкату й явного дозволу на конкретну
   production-операцію за [AGENTS.md](../../AGENTS.md).
6. Candidate SBOM із CI `AvelRen-ORIGINAL` не засвідчує жоден наведений
   live image ID. Перед exact-build promotion потрібно пов'язати SBOM
   із незмінною ідентичністю саме того образу, який буде запущено.

## Наступна перевірка лише читанням

- Встановити походження образу collector за незмінними записами збірки
  та deployment; одного live tag недостатньо.
- Інвентаризувати й розглянути дев'ять записів dirty checkout перед
  підготовкою deployment, зі збереженням backup-файлів.
- Звірити фактичні Compose-файли та production pin з приватними
  deployment records і цільовим переходом на `AvelRen-ORIGINAL`.

Під час вихідного огляду не виконували production-зміни, restart, image pull,
image prune чи очищення репозиторію. Саме перенесення цього документа
не є перевіркою поточного стану сервера або дозволом на deployment.
