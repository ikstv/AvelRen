# Реєстр відкритих PR старого `AvelRen`

Дата звірки: **2026-09-28**. Це контрольний реєстр перед рішенням про
архівування старого репозиторію. Він не закриває старі PR автоматично.

Кожен відкритий PR має один результат: **перенесено**, **замінено новою
реалізацією**, **ще треба перенести** або **свідомо відкинуто з причиною**.
Стан `DIRTY` або `BEHIND` у GitHub означає лише, що legacy-гілку не можна
зливати як є; це не є оцінкою її ідеї.

| Старий PR | Статус | Доказ / межа | Наступна дія |
| --- | --- | --- | --- |
| [#190 — retention 90 днів](https://github.com/ikstv/AvelRen/pull/190) | **Замінено новою реалізацією** | В `ORIGINAL` є послідовна `012_device_retention`, worker з dry-run/apply та тести; це прийнято в PR #11. Старий `011_device_retention` не можна переносити: номер уже зайнятий, а applied migrations не редагуються. | Звірити staging/production adoption окремим явним GO; старий PR не merge. |
| [#188 — daily status і telemetry](https://github.com/ikstv/AvelRen/pull/188) | **Замінено новою реалізацією** | `ORIGINAL` уже має watchdog/telemetry transfer (PR #3/#7) і тести `daily_status`. Legacy diff не відтворює повністю production watchdog та повертає політику термінових push, яку не слід вмикати механічно. | Окремо перенести лише погоджену production-семантику після staging/restore; не merge старий PR. |
| [#185 — held-out forecast evaluation](https://github.com/ikstv/AvelRen/pull/185) | **Замінено новою реалізацією** | `services/backend/src/avelren/forecast.py:evaluate` навчається на попередній історії й оцінює останні сім днів окремо; `test_forecast_bounds.py` перевіряє розділення training/validation та повні години. MAE=0 збережено через `is not None`. Код присутній у main `ae4fc9c`. | Не переносити повторно; решту семантики відсутнього wait_time з issue #111 перевіряти окремо. |
| [#184 — Premium copy](https://github.com/ikstv/AvelRen/pull/184) | **Свідомо відкинуто** | Premium-функції не затверджені як продуктова політика. Інші зміни цього stacked PR замінені retention та поточним UI. | Не переносити текст до окремого продуктового рішення. |
| [#183 — legacy retention](https://github.com/ikstv/AvelRen/pull/183) | **Замінено новою реалізацією** | Див. PR #190: `ORIGINAL` має нову migration `012`, окремий worker і тести. | Не merge старий PR. |
| [#173 — generated STATE.md](https://github.com/ikstv/AvelRen/pull/173) | **Свідомо відкинуто** | Це автоматично згенерований знімок старого репозиторію, не джерело актуального стану міграції. | Залишити як історичний запис. |
| [#143 — Compose image updates](https://github.com/ikstv/AvelRen/pull/143) | **Ще треба перенести** | Залежності треба брати з актуального registry та перевіряти на current Compose/restore contract, а не переносити старі pins. | Окремий dependency-update PR після compatibility test. |
| [#140 — GitHub Actions updates](https://github.com/ikstv/AvelRen/pull/140) | **Ще треба перенести** | Новий CI має іншу структуру; старий workflow diff не придатний для прямого merge. | Окремо перевірити актуальні версії Actions і оновити current workflows. |
| [#138 — Python image](https://github.com/ikstv/AvelRen/pull/138) | **Ще треба перенести** | Старий Dockerfile і образи відрізняються від `ORIGINAL`; перевірки PR застаріли. | Окремий image-update PR з rebuild, tests і CVE review. |
| [#137 — server-status badge](https://github.com/ikstv/AvelRen/pull/137) | **Замінено новою реалізацією** | Контракт плашки реалізовано й прийнято через `ORIGINAL` PR #19, #20 та #46–#49: technical works → restart → online перевірено на телефоні під час реального reboot. | Старий PR не merge. |
| [#123 — правила актуальності сигналу](https://github.com/ikstv/AvelRen/pull/123) | **Замінено новою реалізацією** | Принцип «перевіряти світ, а не старе твердження» застосовано в `CROSS-SOURCE-AUDIT`, `PRODUCTION-AUDIT` та release evidence. | Старий документ не переносити окремо. |

## Висновок

З 11 відкритих legacy PR: 6 замінені новими реалізаціями, 2 свідомо
відкинуті, 3 залишаються окремими контрольованими задачами. Отже старий
`AvelRen` ще не можна видаляти: залишаються три звірки залежностей
(#143 Compose images, #140 Actions, #138 Python image), а production migration,
backup/restore та ролі БД мають власні критерії приймання.
Попередня позначка #185 як неперенесеного була застарілою; її виправлено
за кодом, а не лише за підсумковим лічильником. Єдиний список залишків —
[MIGRATION-REMAINING.md](MIGRATION-REMAINING.md).

Пов’язані документи: [реєстр legacy Issues](LEGACY-ISSUE-REGISTER.md),
[аудит server drift](CONTROL-AUDIT.md) і [матриця production restore](PRODUCTION-RESTORE-GAP-MATRIX.md).
