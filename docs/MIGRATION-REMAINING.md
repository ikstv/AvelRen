# Залишки перенесення

Звірка 28.09.2026 після merge PR [#52](https://github.com/ikstv/AvelRen-ORIGINAL/pull/52)
і [#53](https://github.com/ikstv/AvelRen-ORIGINAL/pull/53), main `ae4fc9c`.
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
| Залежності legacy #143/#140 | Python (#138) замінено в PR #56. Залишилися Caddy, окремий TimescaleDB upgrade rehearsal і supply-chain CI. Старі pins не копіювати автоматично. |
| Forecast issue #111 | Звірити семантику відсутнього wait_time та критерії якості. Held-out evaluation вже реалізовано; повторний перенос не потрібний. |
| Сповіщення про реліз, R08 | Завершити серверний release_notice, перевірку доступності в Play та наскрізне приймання доставки. |
| Старі issues #19/#23/#25/#26 | По пунктах звірити FCM ownership/delete-installation, supply-chain вимоги, privacy та release/recovery runbooks; реалізувати або явно відкласти прийняті залишки. |
| Ops і recovery | Завершити звірку актуальних runbooks, доступів/key escrow, матеріалів Play та унікальних серверних змін із новим кодом. Наявність архіву не доводить відновлення. |
| Приймання на сервері та телефоні | За погодженими операціями зняти свіжі докази runtime/ролей/міграцій, перевірити реальний backup лише в ізольованій БД, сумісність APK↔API та спосіб відкату. Злиття #53 цього не виконує. |
| Закриття міграції | Звірити гілки без PR, теги, releases, issues та унікальні файли обох джерел. Після приймання — окреме рішення про архівування чи видалення. |

## Контроль інвентаризації

GitHub: AvelRen має 11 відкритих PR і 8 відкритих issues;
AvelRen-ops — 0 відкритих PR та 0 відкритих issues.
За [реєстром PR](LEGACY-PR-REGISTER.md): 7 замінені, 2 відкинуті з причиною,
2 потребують завершення залежностей. Issue #195 закрита 26.09.2026.
Відсутність відкритих питань у ops не означає завершеного перенесення файлів.

Звірку трьох dependency PR завершено в [LEGACY-DEPENDENCY-AUDIT.md](LEGACY-DEPENDENCY-AUDIT.md):
оновлення образів ще потрібні, а #140 стосується відсутніх SBOM/CodeQL jobs.
PR [#56](https://github.com/ikstv/AvelRen-ORIGINAL/pull/56) злитий 28.09.2026
у main `08a16a254e25b67ce590475957380e66062de10d`. Фінальний head `e6e5586`
має 5/5 успішних CI checks. Python pins узгоджено, CVE baseline review
зафіксовано, NNP/cap_drop п'яти Python-служб та Compose-регресії прийнято.
Локальні unit/DB/API/watchdog/snapshot/restore перевірки пройшли.
[Докази та залишкові ризики](PYTHON-BASE-UPDATE-2026-09-28.md).
Legacy #138 закрито саме як пункт source-перенесення, не як production
deployment чи усунення всіх CVE. Старі репозиторії та їх PR не змінювалися.
У гілці `codex/caddy-image-refresh` підготовлено Caddy 2.11.4 та виправлення
втрати IP-заголовка; локальні validate/routing пройшли на старому й новому
образах. [Докази](CADDY-UPDATE-2026-09-28.md). До приймання потрібні CI і merge.
Після цього — окрема TimescaleDB upgrade-репетиція; #143 поки не закрито.
Серверні операції мають окремі дозволи за AGENTS.md.
