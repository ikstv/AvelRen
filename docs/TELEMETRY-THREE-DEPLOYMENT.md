# Підключення трьох ресурсів і підготовка 1.0.3

Дата: 07.10.2026. [Пакет розгорнуто й прийнято](audits/TELEMETRY-THREE-2026-10-07.md)
о 14:52:56 за Києвом. Нижче збережено підготовчий baseline і gates.

Власник погодив зараз CPU, RAM і диск. Місячний трафік Hetzner та
витрати відкладаються; відсутні дані не замінюються нулями чи оцінками.
Гілку телеметрії не зливати без нового дозволу. Публікація релізу окрема.

## Свіжа read-only звірка

Кандидат PR #100: `7e35d93db8a319c0ac30759c2ad6c2d3b2e901b5`.
Усі вісім CI checks цього head завершилися SUCCESS.
SSH доступний. Публічний `/api/server/status` повертає 404,
внутрішній `/health` API — 200. Live API не має `public_cpu_status`.

API image ID:
`sha256:68975c958fa9ada833cca8510f39c2e2d7c8e834f06f8584f912b2b12c4c0d5b`.
Watchdog image ID:
`sha256:a9ac9259374ceb3e9e29e856ea0909e0041646a2406b51a5b9981d42c1b9bd1d`.
Ці ID — локальний runtime baseline, не registry digest нового кандидата.

Live API файли у `/usr/local/lib/python3.14/site-packages/avelren/`:

| Файл | SHA-256 |
| --- | --- |
| api.py | f1717eb845bb8c5f8dfb25765199df73be3ff285b25689f0dd4bba2c9c98d938 |
| telemetry.py | 3b11c271c60a58ae6878dbd6ca56144283819183b49c72515fcfabaec67945ff |

Встановлений `/usr/local/sbin/avelren-telemetry-snapshot` і очікування
активного watchdog збігаються:
`577aa6c1b213174f2ef1a6211a5047a96aeed36f188cdd00cffa0f37ad731966`.
Telemetry timer active, інтервал OnUnitActiveSec — одна хвилина.
API має лише read-only telemetry mount; Docker socket не додається.

Production checkout лишається legacy `81e5b047f8f18c42ca46a59f86495f71d0681af0`
і має чужі tracked/untracked зміни. Його не reset, не pull і не checkout.
Effective API Compose містить базовий Compose, локальний override,
`deploy-013.yml` і model-fix `on.json` з приймання 03.10.
Повторне зняття baseline обов'язкове безпосередньо перед записом.

## Обмежений пакет та gates перед записом

1. Побудувати окремий незмінний API candidate на базі активного image,
   із заміною лише `api.py`, `telemetry.py` і додаванням `public_resources.py`.
   Спершу підтвердити тотожність live бази прийнятому `bc41a15`;
   порівняти весь пакет модулів, не тільки наведені два файли.
   Diff API/telemetry від bc41a15 містить лише public resources і bounded reader.
2. Підготувати погоджену CPU/RAM/disk версію host snapshot та окремий
   watchdog candidate зі зміною лише очікуваного SHA. Не вимикати перевірку.
   Не накладати весь новий watchdog на чужий runtime без звірки.
3. Зберегти старі образи, точні файли, права й контрольні суми у приватному
   backup-каталозі; секретні env залишаються лише на сервері.
4. Перевірити кандидат без production БД і джерела: синтетичний snapshot,
   0/100%, stale/invalid, whitelist, health та відсутність traffic-запитів.
   Зберегти manifest/SBOM саме розгорнутого кандидата.
5. Скласти окремий overlay лише API/watchdog зі збереженням усіх чинних
   overrides/env. Перевірити resolved model без друку секретів.
   Ніякого generic compose up, міграцій, зміни collector/notifier/worker,
   DB/Caddy чи перезапуску хоста.
6. Перед записом погодити конкретну операцію: встановлення snapshot та
   recreate лише API/watchdog. Власник дав цей окремий GO у чаті 07.10;
   повторне погодження того самого пакета не потрібне. Preflight gates
   і перевірка відкату залишаються обов'язковими.

## Підготовлені та перевірені кандидати

Усі 43 Python-модулі активного API побайтово (SHA-256) збігаються
з `bc41a15`; активний watchdog.py також має той самий SHA.
Нові образи побудовано на точних старих image IDs, без встановлення
залежностей. Dockerfile FROM використовує окремі локальні base tags:
BuildKit розпізнає голий `sha256:...` як назву registry repository,
тому початкову невдалу збірку виправлено; робочі контейнери не змінювалися.
Успішний build output підтвердив фактичні SHA обох баз.

| Кандидат | Локальний image ID |
| --- | --- |
| API | sha256:1a11dd56a064b4db7aa405dfce879c3bcc87396b7c55e747eff96ab9892338ee |
| Watchdog | sha256:77e55b1dc74dac65a665ab1e0fd00269a62b821bd337fcf957b600b006e257af |

Host candidate SHA збігається з очікуванням нового watchdog:
`c07f9332b7e868c84f7f22a5f0a0b0890495e3610bc5ffcffe32c01d4454def1`.
`bash -n` пройшов. Одноразовий контейнер API з `--network=none`, без
production volumes/env/БД, перевірив CPU/RAM/disk 0/100, invalid/bool,
stale, malformed JSON, whitelist та наявність `/server/status`: PASS.
Це component smoke, не повне HTTP/server/phone приймання.

Кандидати й пакет збережено у `/tmp/avelren-telemetry-7e35d93-20261007`.
Тимчасова папка не є backup і може зникнути при reboot; до переключення
потрібне приватне стале сховище точного пакета та rollback.
Перелічені серверні gates закрито подальшим датованим прийманням:
package SBOM, resolved Compose, rollback overlays, deployment і два цикли.
Фактичний відкат та телефонне приймання не виконувалися.

## Приймання та відкат

Після запису: `/api/server/status` — 200, CPU 0–100, RAM/disk bytes
відповідають host probes, timestamps свіжі, приватні поля відсутні;
traffic unavailable. Перевірити щонайменше два штатні telemetry cycles,
watchdog hash check, health/restarts/log errors. Collector cadence і IDs
незачеплених контейнерів незмінні; журнал міграцій не змінювався.

Відкат повертає точний попередній host script і попередні API/watchdog
image IDs через перевірений rollback overlay. Дані БД не відкочуються.
Перевірити фактичний скрипт, snapshot SHA, API health і watchdog після відкату.
До проходження preflight немає готового до запуску deployment command.

## Release 1.0.3

GitHub і Play ще не опубліковані. Старі APK/AAB з bc41a15 не містять
сьогоднішню телеметрію: не додавати їх до релізу під новим описом.
Потрібні окреме погодження інтеграції гілки, clean-main APK/AAB,
SHA/readback, телефонне приймання трьох живих смужок, великого шрифту,
обох тем, offline/refresh і затверджений однаковий опис GitHub/app/Play.
Не публікувати 1.0.3 лише на підставі зеленого CI.
