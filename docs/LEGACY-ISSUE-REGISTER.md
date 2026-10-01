# Реєстр Issues старого `AvelRen`

Це контрольний реєстр перед можливим архівуванням або видаленням старих
репозиторіїв. Він не закриває і не переносить GitHub Issues автоматично.
Кожна відкрита Issue старого `ikstv/AvelRen` мусить мати один із статусів:
**перенесено**, **частково перенесено**, **замінено**, **ще потрібно
перенести** або **операційне спостереження**.

Зріз джерел GitHub: **2026-09-28**. Відкриті Issues: 8 у `AvelRen`, 0 у
`AvelRen-ops`. Issue #195 закрита 26.09.2026; її рядок нижче зберігає історичне
спостереження. Поточні залишки — у [MIGRATION-REMAINING.md](MIGRATION-REMAINING.md).
Закриті Issues старого
репозиторію лишаються історичним доказом; повторно розглядати їх потрібно
лише коли нова зміна торкається їхнього контракту.

| Стара Issue | Статус | Доказ / межа | Явне наступне рішення |
| --- | --- | --- | --- |
| [#196 — maintenance перед reboot/deploy](https://github.com/ikstv/AvelRen/issues/196) | **Перенесено** | `ORIGINAL` PR #19/#20/#46–#49: technical works → restart → online підтверджено на телефоні під час контрольного production reboot 2026-09-27. | Стару Issue можна закрити окремим рішенням власника; автоматично не закривати. |
| [#195 — порожній watchdog alert channel](https://github.com/ikstv/AvelRen/issues/195) | **Операційне спостереження** | Це стан живого каналу, а не пропущений файл міграції. На час перевірки Admin-пристрій був очікувано заблокований, тому live FCM token відсутній. | Не переносити як код; перевірити після розблокування пристрою та окремого дозволу на production. |
| [#111 — forecast/ETA і нуль як відсутнє значення](https://github.com/ikstv/AvelRen/issues/111) | **Частково перенесено** | MAE=0/null виправлено; held-out evaluation реалізовано в `forecast.py:evaluate` та перевірено `test_forecast_bounds.py`. Семантика відсутнього `wait_time` потребує окремого приймання. | Провести пофункціональну звірку forecast/ETA до вказаного Issue дедлайну 2026-10-29. |
| [#110 — два ПК, доступи й синхронізація](https://github.com/ikstv/AvelRen/issues/110) | **Замінено** | Це історична операційна нотатка зі застарілими комітами й командами. Нові зміни працюють через окремі GitHub PR та чисті гілки. | Зберегти як історію; перед видаленням старого репозиторію перенести лише актуальні правила доступу в приватну ops-документацію. |
| [#26 — загальний production hardening audit](https://github.com/ikstv/AvelRen/issues/26) | **Частково перенесено** | Його підпункти розкладені між CI, backup/restore, privacy, ролями БД та release readiness; один старий Issue не є доказом готовності. | Не закривати пакетно: звірити кожен підпункт із #15, #19, #23, #25 і поточними тестами. |
| [#25 — privacy, retention, release runbooks](https://github.com/ikstv/AvelRen/issues/25) | **Частково перенесено** | [Датований запис](../ops/static/README.md) і R09 фіксують публікацію політики 90 днів без email-запиту, перший apply 0/0 та активний тоді таймер; `SECRETS-RECOVERY.md` містить резерв доступів. Це не доказ видалення реальних старих записів або наступного запуску. Окремого `docs/release-signing.md`, на який посилається Android Gradle, у дереві немає. | Звірити data inventory, explicit deletion/ownership (#19), access logs, підпис/release та recovery runbooks із чинними файлами й production evidence; не закривати всю issue за фактом публікації `/privacy`. |
| [#23 — reproducible builds і supply chain](https://github.com/ikstv/AvelRen/issues/23) | **Частково перенесено** | [Пунктова звірка](SUPPLY-CHAIN-CI-DESIGN-2026-09-28.md): Python/Gradle locks, digest/SHA pins, SBOM і cleanup тестового стеку є; Gradle artifact checksums, Dependabot і регулярні vulnerability audits відсутні. CodeQL має окремий ліцензійний блокер. | Окремо вирішити залишки; не вважати SBOM перевіркою CVE чи candidate image доказом production-образу. |
| [#19 — FCM ownership і retention інсталяцій](https://github.com/ikstv/AvelRen/issues/19) | **Частково перенесено** | У ORIGINAL є 90-денне очищення неактивних інсталяцій (`012_device_retention.sql`, `device_retention.py`) і захист AUTH-1: реєстрація з відомим FCM-токеном створює нові `device_id`/секрет, а не видає чужі (`test_auth.py`). Очищення за `last_seen` не доводить володіння токеном і не є явним видаленням інсталяції; маршруту `DELETE /devices` у `subscriptions_api.py` немає. | Окремо узгодити proof-of-possession, delete-installation/Android cleanup та долю підписок і сповіщень; не переносити підписки лише за збігом FCM-токена. До прийняття дизайну Issue лишається відкритою. |
| [#15 — розділення PostgreSQL runtime roles](https://github.com/ikstv/AvelRen/issues/15) | **Частково перенесено** | Міграції й negative privilege/restore-контракти є в ORIGINAL. За [датованим аудитом](PRODUCTION-AUDIT.md) 26–27.09 production-журнал уже мав 001–014, а API працював під `avelren_api`; старі superuser-ролі та активний migration pin залишалися, повний перехід прав не завершено. Це не свіжа звірка всіх runtime-ролей і прав. | Перенести або замінити старі adoption-сценарії з forward/inverse rollback і тестами, перевірити в ізоляції, потім окремо погодити production transition; не запускати його лише через наявність міграцій. |

## Як реєстр захищає від пропусків

1. Перед перенесенням функції зі старого PR звіряти пов’язані відкриті Issues,
   а не тільки diff PR.
2. Після merge в ORIGINAL оновлювати рядок доказом: PR, тест або свідоме
   рішення, а не припущенням «мабуть уже є».
3. Перед рішенням про старі репозиторії вимагати для кожного рядка один із
   фінальних статусів: перенесено, замінено, ще потрібно перенести або
   свідомо відкинуто з причиною.
4. Операційні Issues не маскувати під кодові: вони закриваються лише
   актуальним production evidence, не копіюванням тексту в Git.

Пов’язані артефакти: [реєстр legacy PR](LEGACY-PR-REGISTER.md), [контрольний аудит](CONTROL-AUDIT.md),
[матриця production restore](PRODUCTION-RESTORE-GAP-MATRIX.md) та
[release readiness](RELEASE-READINESS.md).
