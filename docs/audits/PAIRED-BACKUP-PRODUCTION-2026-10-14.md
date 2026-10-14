# Спільне резервне копіювання: перша серверна спроба 14.10.2026

**Результат: дві спроби завершилися перевіреним відкатом; paired restore ще не прийнято.**
Друга спроба створила SQL і SQLite snapshots, але не завершила публікацію пари.
Штатне попереднє резервне копіювання повернуто до роботи за розкладом.

## Друга спроба — після виправлення Compose preflight

[PR #127](https://github.com/ikstv/AvelRen-ORIGINAL/pull/127) злитий у
`7c88b5162f875dc6a0a4ce7f460e1d6f121ac3ca`; усі обов'язкові перевірки
[CI 38520046405](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38520046405)
успішні, три непотрібні для зміни jobs пропущені за dispatcher-планом.
Дерево main точно збігається з протестованим merge. Незалежний review схвалив
виправлення; root звірив усі 21 файл пакета й дев'ять source payloads.
Встановлені `Runtime.verify_client()` та `Runtime.prepare_sql()` пройшли
до початку паузи; helper image і його source залишилися попередніми.

Запуск почався о **10:19:40 за Києвом** (07:19:40 UTC), generation
`8f058335-e957-4e70-a61e-0ab763cdf89b`. SQL та spool helpers завершилися
з exit 0. Від початку control-on helper до успішного завершення control-off
минуло **40,589 секунди** — це верхня межа фактичної паузи за lifecycle events,
а не `pause_seconds` із receipt. Ліміт 900 секунд не перевищено.

Після відновлення запису публікація завершилася помилкою о 07:20:57 UTC.
У сховищі є лише три часткові файли `20261014-072001`: SQL (9 013 109 байтів),
його checksum (97 байтів) та spool (516 923 байти). Немає checksum spool і
`pair.json`; receipt успіху відсутній. **Це не прийнята резервна пара.**
Категорія `network_failed` охоплює всі помилки після resume й сама не доводить
мережеву причину. Конкретний rclone error втрачено через придушення stderr.
Окрема передача, readback і видалення малого власного тестового файла в тих
самих sandbox/cleanenv умовах пройшли; це не доводить усунення першопричини.

Перевірено точний відкат файлів, environment, прав і попереднього timer.
Native status: `capture_only=false`, `mode_ack=false`, `pending_count=0`,
`last_error=null`; усі сім контейнерів з попередніми IDs/images і RestartCount 0.
Після відкату API `ok`, observations 07:22:53 UTC, age 54 s, alert checks `ok`.
Наступний timer на момент readback — 15 жовтня 06:25:13 за Києвом.
Потрібні безпечна діагностика передачі, повна публікація та isolated restore.
Після окремої явної згоди власника на тимчасове завантаження у захищену
локальну папку виконано readback часткових файлів. SQL прочитано й перевірено
як gzip, але читання checksum завершилося HTTP 403 з ознакою quota/rate-limit.
Це прямий доказ поточної помилки сховища, але не доказ причини попереднього
upload: точний Google reason code не збережено, денний ліміт і короткочасне
обмеження частоти не розрізнено. Усі локальні чутливі файли видалені в `finally`,
відсутність власної тимчасової папки перевірена. Повне відновлення не виконано.
Нижче збережено історію першої спроби.

## Джерело та дозвіл

Власник явно дозволив встановлення підготовленого пакета, спільну копію
БД і черги та окреме відновлення, із паузою до 15 хвилин і відкатом за помилки.
Пакет побудовано з `main` `145cee1a386b87dc756f1ff9f2996fd9b1d2e900`
після [PR #126](https://github.com/ikstv/AvelRen-ORIGINAL/pull/126).
Усі 11 перевірок [PR CI](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38405519319)
успішні; дерево перевіреного merge збігається з цим main.
Окремий [main-push CI](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/38412367813)
на `145cee1a` також завершився успішно; readback виконано 14 жовтня.
Це source-доказ, а не приймання нового production backup.

Після звірення хешів і прав збережено точні копії змінюваних файлів,
зокрема приватного environment, та перелік раніше відсутніх paths.
Встановлений helper підтвердив UID 10001, source commit та хеші модулів;
`systemd-analyze verify` пройшов. Runtime collector, DB і решти служб
не пересоздавали; міграції, ролі та DSN не змінювали.

## Фактична помилка

Запуск почався о **08:50:13 за Києвом** (05:50:13 UTC).
Generation `aaf0593b-495c-4395-8892-ca1b0a5dab7f` завершилася станом
`resumed`, `children=[]`, із категорією `copy_failed` о 05:50:31 UTC.
Ця загальна категорія сама по собі не означає, що копіювання почалося.
Docker events підтвердили лише успішний check-helper, перевірку запасу
черги та читання статусу. `control-on`, SQL і spool helpers не створювалися.
**Пауза записувача не починалася.** Receipt успіху не створений.

Причина — `Runtime.prepare_sql`: повна інтерполяція чотирьох чинних
Compose-файлів вимагає `AVELREN_RELEASE_MIGRATOR_DSN`, потрібну іншій
службі. Чисте середовище backup навмисно не містить міграційних credentials.
Значення секрету не виводилося й не додавалося до backup environment.

Read-only діагностика тим самим Compose 5.5.1 підтвердила:

- звичайний `config`, навіть із вибором `db`, і `ps -q db` відхиляються;
- `config --no-interpolate --format json` проходить;
- образ БД у результаті — literal Timescale 2.30.1-pg16 із digest
  `sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9`.

Наступне source-виправлення має читати лише literal образ БД без
інтерполяції сторонніх credentials і знаходити працюючу БД через Docker
labels, зберігаючи перевірки єдиної identity, image, ordered Compose paths,
working directory та network. Невизначений образ повинен відхилятися.

## Перевірений відкат

Штатний recovery успішний: `capture_only=false`, `mode_ack=false`,
`pending_count=0`, `last_error=null`; власних helper jobs не залишилося.
Старі scripts, units, environment, UID/GID та modes повернуто й звірено.
Нові destination files прибрано лише за збереженим переліком і хешами.
Попередній timer знову active/enabled; наступний запуск на момент перевірки —
15 жовтня о **06:28:28 за Києвом**.

Усі сім контейнерів мають попередні IDs/images, Running=true,
RestartCount=0. Незалежний зовнішній readback після відкату:
`status=ok`, останні observations 05:55:52 UTC, age 47 s,
`alert_channel=ok`, `undelivered_alerts=ok`, `maintenance=null`.
Перед спробою на сервері було 24 ГБ вільного місця; штатна SQL-копія
цього дня завершилася успішно о 06:23:29 за Києвом.

Приватний release, rollback snapshots, helper image та terminal state
збережені для діагностики. Нових plaintext backup artifacts у workdir немає.
Реальне paired restore, його час і точна звірка ACK/pending залишаються
відкритими до виправлення, повторного запуску та окремої репетиції.
