# Серверне приймання CPU, RAM і диска

07.10.2026, завершення 11:52:56 UTC / 14:52:56 Київ.
Окремий явний GO власника: встановити host snapshot та recreate лише
API/watchdog. Гілку не злитo, APK/GitHub Release/Play не публікували.

## Пакет і передумови

Код `7e35d93db8a319c0ac30759c2ad6c2d3b2e901b5`.
Усі 43 модулі live API SHA-256 збіглися з прийнятою базою bc41a15.
Live watchdog.py також збігся. Нові образи додають тільки три API-файли
та змінюють тільки watchdog expected snapshot SHA; залежності не міняються.
Ізольований `--network=none` smoke: крайні значення, stale/invalid,
malformed JSON, whitelist та endpoint PASS. Це не перевірка startup на БД.

| Сервіс | Новий локальний image ID |
| --- | --- |
| API | sha256:1a11dd56a064b4db7aa405dfce879c3bcc87396b7c55e747eff96ab9892338ee |
| Watchdog | sha256:77e55b1dc74dac65a665ab1e0fd00269a62b821bd337fcf957b600b006e257af |

Власний точковий CycloneDX package SBOM з importlib.metadata/dpkg-query
збережений для обох старих і нових образів: по 124 Python/OS components,
набори незмінні. Без завантаження Syft, не vulnerability/license scan.
Не видавати це за ширше source/image CI SBOM чи security acceptance.

Resolved Compose окремо API і watchdog: environment відповідає live,
forward/rollback overlay змінює лише image. Старі різні overrides збережені.
Незакомічений legacy checkout не редагували й не reset/pull.

## Виконання та результат

Ordinary maintenance (без restarts_at/boot_id) підтверджено public API,
витримано 60 секунд попередження. Watchdog зупинено перед заміною скрипта,
щоб уникнути тимчасової hash-тривоги. Telemetry timer/service коротко
зупинено для атомарної заміни, потім відновлено; unit/config не змінені.
Recreate `--no-deps --no-build --pull never` лише API і watchdog.
Скрипт SHA:
`c07f9332b7e868c84f7f22a5f0a0b0890495e3610bc5ffcffe32c01d4454def1`.

Public `/api/server/status` замість 404 повертає 200 і вузький whitelist.
Знімки RAM/disk: 11:50:41, 11:51:45, 11:52:47 UTC; CPU має власний час.
Усі три ресурси fresh; traffic null/unavailable, не вигаданий 0%.
Останній прийнятий snapshot: CPU 5.0%, RAM 1085333504/4005441536 bytes,
disk 13073682432/39964635136 bytes. Це датований знімок, не поточне значення.
Total відповідає прямим host probes, used — у межах 64 MiB різниці
через рухомі лічильники між snapshot і probe; не доказ побайтової синхронності.

Watchdog hash check PASS. API/watchdog restart_count=0, OOM=false;
у перевірених logs після першого приймання немає ERROR/Traceback.
Collector, notifier, worker, DB і Caddy зберегли container та image IDs.
Журнал 16 міграцій незмінний (SHA
`2b01750e225952f5002c7efb110790bc1c92f045d5a28ee1c2a50e1536fcca16`).
Collector runs 11:51:21/11:52:21/11:53:21/11:54:21 UTC — рівно 60 секунд.
Public health 200, status ok, observation age 29s, alert channels ok.
Власну maintenance-плашку прибрано, `/api/status` повертає maintenance null.

## Чинний запуск та відкат

Захищений сталий каталог `/var/lib/avelren-telemetry-release/7e35d93/`
містить candidate, snapshot-before.sh, baseline, SBOM manifest і результати.
Окремі `api-on.json`/`watchdog-on.json` застосовані після відповідних
попередніх Compose overlays. Точні argv для forward та rollback збережені
як `*-on-command.json` та `*-rollback-command.json` у тому самому каталозі.
Env-файли залишилися на сервері; значення не копіювали в Git/чат.
Generic compose up у legacy checkout не є чинним способом запуску.

Відкат повертає old snapshot і точні попередні image IDs через ці rollback
argv лише для двох сервісів, без rollback БД. Overlays перевірено, реальний
відкат не виконувався. Майбутній запис/recreate потребує власного GO.
`/tmp/avelren-telemetry-7e35d93-20261007` — залишений staging без секретів;
не є backup. Старі образи збережені, cleanup/prune не виконували.

## Незакриті етапи

Android гілка не злитa; встановлений APK не містить цих останніх змін.
1.0.3 Test має ще отримати повнофункціональний окремий client із live API/FCM,
перевірки, clean-main збірку й телефонне приймання. Не ототожнювати
server acceptance з готовністю GitHub/Play релізу чи завершенням міграції.
