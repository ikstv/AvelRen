# Серверне ядро

Перенесено collector, notifier та їхні спільні модулі. Усі 19 вихідних
файлів, включно з трьома наборами тестів, pyproject і lock, незмінні
відносно коміту в [маніфесті](../../docs/CORE-PROVENANCE.json).
Старі технічні коментарі збережено для точного порівняння; нова документація
й пояснення українською.

Додано [міграції та ізольовані інтеграційні тести БД](../../db/README.md).
Також перенесено [API та Admin із перевірками](../../docs/API-TRANSFER.md).
Також перенесено [watchdog і телеметрію](../../docs/WATCHDOG-TRANSFER.md)
з перевіреного серверного варіанта. Production Docker-збірка та повні
експлуатаційні сценарії ще не перенесені.
Не запускати collector або notifier проти єЧерги чи робочої БД з цієї копії.

## Перевірки з кореня репозиторію

Створити venv, активувати його та встановити залежності. На Linux:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r services/backend/requirements.lock
python -m pip install pytest==9.1.1 ruff==0.16.8 tzdata==2026.4
```

На Windows після створення й активації `.venv`:

```powershell
python scripts/prepare_unit_requirements.py .venv/unit-requirements.lock
python -m pip install --no-deps --require-hashes -r .venv/unit-requirements.lock
python -m pip install pytest==9.1.1 ruff==0.16.8 tzdata==2026.4 colorama==0.4.6
python -m pip check
```

Оригінальний lock орієнтований на Linux. Копія пропускає лише uvloop,
який не підтримує Windows; tzdata й colorama додаються окремо.

```sh
python scripts/verify_core_provenance.py
python -m ruff check services/backend/src services/backend/tests scripts/*.py
python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q
```

Перевіряються контракт HTTP єЧерги, незмінність ідентичності між циклами,
допустимі налаштування, обробка FCM, запис помилки без повтору запиту й
збереження основної транзакції при збої похідних сповіщень.
HTTP підмінений; справжні HTTP-транспорти й підключення PostgreSQL
заблоковані тестовими запобіжниками, зовнішні socket-запити заборонені.
Локальні loopback sockets дозволені для внутрішньої роботи Windows asyncio.

Локальний попередній результат: Python 3.12 / Windows, 62 тести успішні;
наступний блок додав три перевірки відмови небезпечного запуску БД.
GitHub workflow перевіряє Linux / Python 3.14. Ці unit-тести не доводять
сумісність реальної БД, придатність backup/restore або готовність до deploy.
