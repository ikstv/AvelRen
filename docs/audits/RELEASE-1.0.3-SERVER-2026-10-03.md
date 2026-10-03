# Приймання серверної частини 1.0.3 — 03.10.2026

Після окремого «дій» власника встановлено виправлений пакет із main
`bc41a15222a57a0ef511010a2891cbdbad92bb72` (PR #81).
Усі 7 перевірок цього коміту успішні. Архів пакета: 70 081 942 bytes,
SHA-256 `0c8ca0d786ceb0506871f6b7a30a067665510b4ecf1a256f75f498d7847aa77f`.
Образ API, notifier і surge_worker:
`sha256:68975c958fa9ada833cca8510f39c2e2d7c8e834f06f8584f912b2b12c4c0d5b`.
Встановлена frozen модель завантажується без source mounts та мережі.

## Перемикання та приймання

Плашка підтверджена API о 02:55:12 за Києвом; штатний helper витримав
60 секунд. Додаткове порівняння рядків controller зупинилося через `Z`
проти `+00:00`; read-only перевірка UTC підтвердила тотожність часу й
власника вікна. Незмінний пакет продовжили лише після цієї перевірки.

API/notifier спочатку прийнято з вимкненим прогнозом, потім увімкнено
всі три служби. Приймання завершено 03.10 о 02:59:53 за Києвом:

- Два завершені worker цикли: processed >= 4, failed = 0, без ERROR/Traceback.
- Нові predictions для КПП 1, 6, 17, 29; baseline max ID був 0.
- Модель `surge_24h_v1`, issued_at 02:58:21 за Києвом; вікно 03:58:21
  03.10 — 02:58:21 04.10. Всі score у межах 0–1, reason null.
- Час, модель і статус кожного результату в DB та public API збігаються.
  На момент перевірки статус усіх чотирьох — `no_signal`.
- API health ok; усі три служби running, RestartCount 0, OOMKilled false.
- Collector capture_only/mode_ack false, pending 0, last_error null.
- DB/collector/watchdog/Caddy зберегли свої ID та образи; журнал міграцій
  і TimescaleDB 2.30.1 незмінні щодо baseline перед цим пакетом.

Власну плашку прибрано о 03:00:13 за Києвом, public API повертає null.
Exact staging `/tmp/avelren-model-fix-bc41a15222a5` видалено після
звірки його маніфесту. Приватний каталог і overlays для відкату збережено:
`/var/lib/avelren-model-fix/bc41a15222a57a0ef511010a2891cbdbad92bb72/`.
Приватні DSN/паролі залишилися на сервері. У Git немає backup чи ключів.

## Операторський стан і відкат

Чинний overlay — `on.json` у наведеному приватному каталозі. Для явного
Compose потрібні `/opt/avelren/docker-compose.yml`, його локальний override,
`/var/lib/avelren-release-check-20260924/deploy-013.yml`, потім цей overlay;
env-файли — `/opt/avelren/.env` та `private.env` попереднього release
`/var/lib/avelren-release-1.0.3/aecbfa66a2b704f6d1c266c756516d9c22bfbc02/`.
Generic compose up старого checkout не є чинною процедурою розгортання.

Підготовлений відкат: зупинити worker, застосувати `rollback-off.json`
лише до API/notifier, запустити штатний disabled worker для
`disable_monitoring`. Він повертає попередній application image 8300…
зі збереженням schema 016, нових observations, підписок і ACK.
Фізичний відкат БД після запуску writers первинного deployment не дозволений.
Відкат цього пакета не виконувався. Подальший production запис потребує GO.

## Android і межі приймання

Підписані 1.0.3 / versionCode 6 з того самого main:

| Артефакт | SHA-256 |
| --- | --- |
| APK | `16093954038d74eaae5cc132844b3cc5d0cd7c5c80d39e6b1d86bb888ddbfe45` |
| AAB | `b578d53d4cc8f26b20a522b4bda8c1a0d7a5428660db39f33391591410de5d98` |

Підписи перевірено. Публічні Firebase client ресурси відновлено з уже
встановленого Play APK; їхню тотожність у новому APK перевірено.
Upload signing certificate відрізняється від Play app signing certificate,
тому цей APK не оновлює встановлений Play-застосунок напряму.

Офлайн UI в emulator-5584: дві погоджені фрази, круглі маркери КПП,
фільтр країни, підтвердження видалення, ліміт 5 і відмова шостому — PASS.
Емулятор не реєстрував пристрій на production. Це не телефонне приймання.
Реальні FCM, жіночий голос, повтор/ACK, offline і PIN після перевстановлення
на фінальній 1.0.3 ще потребують конкретних сценаріїв на телефоні.

GitHub Release і Play не опубліковані: опис редагує власник. Порядок:
погоджений опис та GitHub 1.0.3, потім Google Play. Точність 99% за двома
показниками не підтверджена; експериментальний статус збережено.
ОС/Docker, автоматичні оновлення та автоматичні reboot не змінювалися.
