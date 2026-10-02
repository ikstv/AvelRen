# Пакування frozen моделі та стан сервера — 03.10.2026

## Причина та виправлення

Серверний образ main `aecbfa66a2b704f6d1c266c756516d9c22bfbc02`
не містить `avelren/models/surge_24h_v1.json` у встановленому wheel.
Setuptools знаходив Python-пакети, але JSON не був явно зазначений
як package data. Тести з PYTHONPATH/source mount використовували файл
із checkout і не перевіряли встановлений wheel.

До `services/backend/pyproject.toml` додано лише package-data `models/*.json`.
Залежності, lock, модель, її контрольна сума, формула та міграції незмінні.
Походження pyproject з `ikstv/AvelRen` збережено в CORE-PROVENANCE.json;
ця правка має окремий revision з посиланням на цей документ.

`ops/verify-installed-model.py` відхиляє source import, вимагає запис JSON
у distribution metadata та завантажує модель з перевіркою її SHA і розмірів.
Перевірка виконується у candidate image без source mounts і мережі:
у CI image-sbom та перед успішною attestation штатного build script.

Локальний RED: точний образ `sha256:8300a1bd8b414d592118bd0628620563fe3b02b01d9357ae9fb15737b367188e`
відхилено через відсутній JSON у wheel. GREEN: локальний тестовий образ
із package-data пройшов installed-model перевірку. Fake-Docker контракт
також спостерігав RED приймання образу без моделі, потім GREEN відмову.
Тестовий образ не є main-кандидатом і не встановлювався на production.

## Фактичний production стан після погодженого переходу

Усі 8 CI exact main успішні. Погоджений immutable ZIP:
`ed3d4a0894605d181209f80cc663a97569101367e0be508507ca3194da9591a4`.
Світлий/темний UI, телефон і Play цим серверним записом не приймалися.

- Native свіжий encrypted backup та ізольована main restore-репетиція PASS:
  3 059 950 observations збережено; стенд прибрано, робочий baseline незмінний.
- Окремо погоджена поправка плашки: старий API підтримує900s, новий3600s.
  Вікна підтверджено public API. Перший захисний stop не зупиняв служби.
- Online Backup collector: integrity/pending digests PASS, SHA-256
  `3c3b613e4f301b329572160fead242a8363441a70894f62fd3d4bb09c5f96dd1`.
  Через недоступність temporary /tmp для Docker cp ті самі backup bytes
  передано docker exec cat лише в погоджений приватний файл на сервері;
  temporary прибрано, на ПК SQLite/backup не переносилися.
- Quiesced encrypted backup `daily/avelren-20261002-221641.sql.gz`,
  7 062 492 bytes, SHA-256
  `81a0424da7a40125b3ca8e1a345ffd21ed2a39d7b551b171b51d36032fcc413a`.
- Cold copy `avelren_103_cold_aecbfa66a2b7`: усі file hashes/owner/mode
  збігаються; contents SHA-256
  `23a9d198b9c068adfd334363b52dabf8a9a8e426d2169fce82966e0dc56ed98b`.
- Timescale2.30.1, restoring=off, exact015/016, schema/counts/backup ACL PASS.
  Перед writers: 3 060 786 observations, 51 376 hourly rows, сім compressed
  chunks; старий journal001–014 незмінний, source digests001–016 збігаються.
- Collector не зупинявся/recreate. Після capture-only off всі pending
  дозаписано FIFO. Природні цикли03.10 01:28:21–01:32:21 за Києвом:
  п’ять HTTP200/38rows/derived без помилок, інтервали60/60/60/60s.
- Межу writers пройдено03.10 о01:26:09 за Києвом. Cold restore після неї
  не виконувався; нові записи, ACK та additive схема збережені.
- Worker виявив packaging failure, processed=0/failed=4. За погодженим
  kill-switch прогноз вимкнено (`SURGE_ENABLED=false` API/notifier), worker
  зупинено, disabled worker штатно виконав disable_monitoring.
- Recovery health/alert_channel/undelivered_alerts ok, pending=0,
  last_error=null. Backup/retention timers повернутоactive/enabled,
  власну плашку та plaintext копію прибрано. Cold rollback volume збережено.

Функцію прогнозу **не прийнято і не ввімкнено**. Для завершення потрібні
review/CI цього виправлення, чистий main-кандидат із installed-model gate,
конкретний пакет лише application images та окремий production GO.
Не повторювати DB upgrade/міграції. Новий backend ще не розгорнуто.
99% precision/recall не підтверджено; GitHub Release/Play не опубліковано.

## Операторський контур

Чинні private overlays розташовані в
`/var/lib/avelren-release-1.0.3/aecbfa66a2b704f6d1c266c756516d9c22bfbc02/`.
Використовується **release-off.json**, з усіма explicit базовими Compose,
override та старим pin як у погодженому INSTALLATION-PLAN. Generic Compose
up через старі /opt-файли може повернути старі images/pin, тому заборонений.
Collector залишається в окремому managed runtime, Caddy незмінний.
Private env/DSN/password не додано до репозиторію. ОС/Docker, автоматичні
оновлення/reboot та встановлені restore-сценарії не змінювалися.
