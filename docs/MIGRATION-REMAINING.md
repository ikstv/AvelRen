# Залишки перенесення

Звірка 28.09.2026 після merge PR [#66](https://github.com/ikstv/AvelRen-ORIGINAL/pull/66),
main `c20ab3e0896bf0cbf2dbf985bb5dcc26796e2947`; repository і source-SBOM CI успішні.
Це поточний контрольний список; датовані старі аудити зберігають історичний зміст.
У цьому кроці сервер і телефон повторно не перевірялися.

## Уже є в новому репозиторії

- Серверне ядро, API/Admin, Android, міграції, runtime Compose та телеметрія.
- Retention 90 днів, виправлення MAE=0, оцінювання прогнозу на окремих семи днях.
- Backup, ізольований Timescale restore, manual production restore orchestrator
  із перевірками та зупинкою процедури при невідповідності передумов.
- PR #53: шість успішних CI checks для `f52f68e`; локально 200 backend unit,
  22 database tests, Android unit/compile та ізольований restore rehearsal.

## Відкриті роботи

| Блок | Конкретний результат для закриття |
| --- | --- |
| Supply-chain CI legacy #140 / issue #23 | Source SBOM у main; Python lock completeness перевіряється (PR #65/#66). Окремий candidate image job збирає app з перевірюваного SHA та сканує його, TimescaleDB і Caddy за digest; результат — 30-денні CycloneDX artifacts, без push/deploy. Це не доказ, що локально перебудований production image ідентичний CI candidate. Перед exact-image deployment потрібен окремий handoff immutable image/digest. CodeQL для приватного user-owned repo має ліцензійний блокер; інші залишки issue #23 вести окремо. |
| Forecast legacy #111 / ORIGINAL [#70](https://github.com/ikstv/AvelRen-ORIGINAL/issues/70) | Аудит семантики виконано 30.09.2026. [Специфікація сумісного контракту](superpowers/specs/2026-09-30-wait-estimate-design.md) підготовлена для перегляду: missing/0/legacy_unknown, незалежний кількісний прогноз та старий APK. Реалізація, CI, deployment і приймання ще не виконані. Held-out evaluation вже є; повторний перенос не потрібний. |
| Сповіщення про реліз, R08 | Завершити серверний release_notice, перевірку доступності в Play та наскрізне приймання доставки. |
| Старі issues #19/#23/#25/#26 | По пунктах звірити FCM ownership/delete-installation, supply-chain вимоги, privacy та release/recovery runbooks; реалізувати або явно відкласти прийняті залишки. |
| Ops і recovery | Завершити звірку актуальних runbooks, доступів/key escrow, матеріалів Play та унікальних серверних змін із новим кодом. Наявність архіву не доводить відновлення. |
| Приймання на сервері та телефоні | За погодженими операціями зняти свіжі докази runtime/ролей/міграцій, перевірити реальний backup лише в ізольованій БД, сумісність APK↔API та спосіб відкату. Злиття #53 цього не виконує. |
| Закриття міграції | Звірити гілки без PR, теги, releases, issues та унікальні файли обох джерел. Після приймання — окреме рішення про архівування чи видалення. |

## Контроль інвентаризації

GitHub: AvelRen має 11 відкритих PR і 8 відкритих issues;
AvelRen-ops — 0 відкритих PR та 0 відкритих issues.
За [реєстром PR](LEGACY-PR-REGISTER.md): 8 замінені, 2 відкинуті з причиною,
1 потребує перенесення supply-chain CI. Це не загальний лічильник усіх
залишків: issues, приймання й фінальна інвентаризація ведуться окремо.
Issue #195 закрита 26.09.2026.
Відсутність відкритих питань у ops не означає завершеного перенесення файлів.

Звірку трьох dependency PR завершено в [LEGACY-DEPENDENCY-AUDIT.md](LEGACY-DEPENDENCY-AUDIT.md):
source-оновлення образів прийняті. Legacy #140 оновлює pins у старих CI workflow;
SBOM адаптацію та CodeQL ліцензійний блокер зафіксовано в
[дизайні supply-chain CI](SUPPLY-CHAIN-CI-DESIGN-2026-09-28.md).
Повний scope issue #23 ширший за #140.
PR [#56](https://github.com/ikstv/AvelRen-ORIGINAL/pull/56) злитий 28.09.2026
у main `08a16a254e25b67ce590475957380e66062de10d`. Фінальний head `e6e5586`
має 5/5 успішних CI checks. Python pins узгоджено, CVE baseline review
зафіксовано, NNP/cap_drop п'яти Python-служб та Compose-регресії прийнято.
Локальні unit/DB/API/watchdog/snapshot/restore перевірки пройшли.
[Докази та залишкові ризики](PYTHON-BASE-UPDATE-2026-09-28.md).
Legacy #138 закрито саме як пункт source-перенесення, не як production
deployment чи усунення всіх CVE. Старі репозиторії та їх PR не змінювалися.
Caddy 2.11.4 та виправлення IP-заголовка злиті PR #58 у main `64511b8`;
4/4 CI merge-коміту успішні. [Докази](CADDY-UPDATE-2026-09-28.md).
[Ізольована TimescaleDB upgrade-репетиція](TIMESCALE-UPGRADE-2026-09-28.md)
злита PR #59 (main `dc2b83e`, 4/4 CI успішні). Три pins 2.30.1 для
Compose/DB/restore прийняті PR #60 (main `ee31a7b`, 4/4 CI успішні).
#143 завершено як source-пункт; сам старий GitHub PR лишився відкритим.
Production deployment — окремий етап.
Серверні операції мають окремі дозволи за AGENTS.md.
