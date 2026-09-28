# Звірка трьох legacy PR залежностей

**Актуалізація:** Python source-залишок #138 замінено після merge ORIGINAL
[#56](https://github.com/ikstv/AvelRen-ORIGINAL/pull/56), main `08a16a2`.
Фінальний head `e6e5586`: 5/5 CI checks; [аудит](PYTHON-BASE-UPDATE-2026-09-28.md).
Нижче — первинний зріз до цього оновлення. #143/#140 лишаються відкритими
задачами перенесення. Caddy прийнято PR #58 (main `64511b8`, 4/4 CI).
Для TimescaleDB підготовлюється [окрема репетиція](TIMESCALE-UPGRADE-2026-09-28.md)
без зміни production pin; її успіх не закриває deployment або весь #143.

28.09.2026. База ORIGINAL: `c4ce7b9e36e0500e09f00574c19305dde9b08013`.
Перевірено diff та точні head-коміти старих PR, поточні файли нового
репозиторію, доступність запропонованих image manifests і Actions commits.
Залежності та production у цьому документальному кроці не змінювались.

## Результат по кожному PR

| Джерело та head | Фактичний залишок в ORIGINAL | Рішення |
| --- | --- | --- |
| [#138](https://github.com/ikstv/AvelRen/pull/138), `8bd73748bc796d50416f7dbc532250749e6ddf13` | Python `3.14-slim` досі закріплено на `ce407646…`; PR пропонує `cad9a2c…`. Обидва місця: `services/backend/Dockerfile`, `ops/Dockerfile.database-test`. | Підготувати окреме узгоджене оновлення обох Dockerfile, rebuild та backend/DB/API/watchdog/restore перевірки. Перевірити вразливості кандидата. |
| [#143](https://github.com/ikstv/AvelRen/pull/143), `ea467895bd8270b17cfea443671ab3e094b8ed04` | TimescaleDB `2.17.2-pg16` → `2.30.1-pg16`; Caddy `2.9.1-alpine` → `2.11.3-alpine` ще не враховані. | Розділити Caddy і TimescaleDB. Для Caddy потрібні validate та перевірка маршрутизації. Для TimescaleDB — DB/ACL/API/restore і окрема перевірка переходу зі старої версії на нову. Чистий init нової БД не доводить можливості оновлення наявної. |
| [#140](https://github.com/ikstv/AvelRen/pull/140), `d9268902aac7631d8542daab0650190b42ef1727` | Diff оновлює `anchore/sbom-action` та дві дії CodeQL (`init`, `analyze`). Таких jobs у поточних workflows ORIGINAL немає. | Це залишок перенесення supply-chain перевірок issue #23, а не оновлення вже наявних Actions. Потрібен окремий CI-крок: SBOM та рішення щодо доступності CodeQL для приватного репозиторію. Наявний pin checkout не закриває #140. |

## Точні кандидати зі старих PR

Registry повернув manifests для всіх трьох digest; це підтверджує доступність,
але не поточну «найновішу» версію, відсутність CVE чи сумісність із production.

- Python: `python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6`.
- TimescaleDB: `timescale/timescaledb:2.30.1-pg16@sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9`.
- Caddy: `caddy:2.11.3-alpine@sha256:86deaf5e3d3408a6ccec08fbb79989783dd26e206ae10bcf78a801dc8c9ab794`.
- SBOM action: `3ad7283483fc7af8ff2b4ea19663c2d5ca935e26` (існування підтверджено GitHub API).
- CodeQL action: `1c5b675653bb5c22dbe9b12b556ec555138e09fd` (існування підтверджено GitHub API).

TimescaleDB pin є у **трьох** місцях: `docker-compose.yml`,
`ops/compose.database-test.yml`, `ops/restore-integration-test.sh`.
Оновлення лише двох файлів зі старого diff залишило б restore rehearsal
на іншій версії. Caddy pin — у `docker-compose.yml`.

У `.github/` також немає конфігурації Dependabot. Автоматичне відстеження
залежностей нового репозиторію слід розглянути разом із issue #23;
наявність Dependabot PR у старому репозиторії його не налаштовує в новому.

## Наступний невеликий крок

Почати з #138: перевірити актуальний кандидат Python, змінити два pins
разом і перевірити збірку та залежні тести в ізольованому середовищі.
Після цього — Caddy, окремий TimescaleDB upgrade rehearsal та supply-chain CI.
Усі три legacy PR поки лишаються незавершеними; їх не закривали.

## Подальша перевірка Python того самого дня

Підготовлено актуальніший кандидат Python 3.14.7, обидва Dockerfile
збираються; backend/DB/API/watchdog/restore перевірки пройшли локально.
Скан виявив знахідки, які потребують розбору до merge. #138 залишається
незавершеним; [деталі й наступний крок](PYTHON-BASE-UPDATE-2026-09-28.md).
