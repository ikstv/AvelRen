# Реєстр Issues старого `AvelRen`

Це контрольний реєстр перед можливим архівуванням або видаленням старих
репозиторіїв. Він не закриває і не переносить GitHub Issues автоматично.
Кожна відкрита Issue старого `ikstv/AvelRen` мусить мати один із статусів:
**перенесено**, **частково перенесено**, **замінено**, **ще потрібно
перенести** або **операційне спостереження**.

Зріз GitHub: **2026-09-25**. Відкриті Issues: 9 у `AvelRen`, 0 у
`AvelRen-ops`, 0 у `AvelRen-ORIGINAL` на час звірки. Закриті Issues старого
репозиторію лишаються історичним доказом; повторно розглядати їх потрібно
лише коли нова зміна торкається їхнього контракту.

| Стара Issue | Статус | Доказ / межа | Явне наступне рішення |
| --- | --- | --- | --- |
| [#196 — maintenance перед reboot/deploy](https://github.com/ikstv/AvelRen/issues/196) | **Частково перенесено** | Source-only publisher/reboot runtime злитий у ORIGINAL PR #20; Android restart state — PR #19. Production deployment і телефонне приймання не виконувались. | Тримати стару Issue відкритою до окремого deployment та телефонного тесту. |
| [#195 — порожній watchdog alert channel](https://github.com/ikstv/AvelRen/issues/195) | **Операційне спостереження** | Це стан живого каналу, а не пропущений файл міграції. На час перевірки Admin-пристрій був очікувано заблокований, тому live FCM token відсутній. | Не переносити як код; перевірити після розблокування пристрою та окремого дозволу на production. |
| [#111 — forecast/ETA і нуль як відсутнє значення](https://github.com/ikstv/AvelRen/issues/111) | **Ще потрібно перенести** | Старий PR #185 містить окрему forecast-роботу, але його не можна переносити цілком; MAE=0/null вже відомий як окремий дефект. | Провести пофункціональну звірку forecast/ETA та прийняти semantic fix до вказаного Issue дедлайну 2026-10-29. |
| [#110 — два ПК, доступи й синхронізація](https://github.com/ikstv/AvelRen/issues/110) | **Замінено** | Це історична операційна нотатка зі застарілими комітами й командами. Нові зміни працюють через окремі GitHub PR та чисті гілки. | Зберегти як історію; перед видаленням старого репозиторію перенести лише актуальні правила доступу в приватну ops-документацію. |
| [#26 — загальний production hardening audit](https://github.com/ikstv/AvelRen/issues/26) | **Частково перенесено** | Його підпункти розкладені між CI, backup/restore, privacy, ролями БД та release readiness; один старий Issue не є доказом готовності. | Не закривати пакетно: звірити кожен підпункт із #15, #19, #23, #25 і поточними тестами. |
| [#25 — privacy, retention, release runbooks](https://github.com/ikstv/AvelRen/issues/25) | **Частково перенесено** | Політика 90 днів без email-ведення, `/privacy` і release readiness уже є в ORIGINAL. Key escrow, повні runbooks і фінальне release-приймання не завершені. | Доробляти лише прийняті залишки; не закривати, доки evidence/recovery/release checklist не звірені. |
| [#23 — reproducible builds і supply chain](https://github.com/ikstv/AvelRen/issues/23) | **Частково перенесено** | В ORIGINAL є pinned Actions/images, provenance та CI-контракти, але Issue перелічує ширший набір: locks, SBOM, dependency/container audits тощо. | Створити окремий checklist порівняння вимог Issue з поточним CI, після чого прийняти або відкласти кожен пункт. |
| [#19 — FCM ownership і retention інсталяцій](https://github.com/ikstv/AvelRen/issues/19) | **Частково перенесено** | 90-денне очищення реалізоване; proof-of-possession, delete-installation flow та повний ownership design окремо не прийняті. | Не вважати retention тотожним ownership; потрібен окремий design gate. |
| [#15 — розділення PostgreSQL runtime roles](https://github.com/ikstv/AvelRen/issues/15) | **Частково перенесено** | Міграції й negative privilege/restore-контракти є в ORIGINAL, але production залишався на 001–009 і legacy-superuser. | До production transition потрібні staging/restore перевірка й окремий явний GO; не застосовувати міграції лише через наявність файлів. |

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

Пов'язані артефакти: [контрольний аудит](CONTROL-AUDIT.md),
[матриця production restore](PRODUCTION-RESTORE-GAP-MATRIX.md) та
[release readiness](RELEASE-READINESS.md).
