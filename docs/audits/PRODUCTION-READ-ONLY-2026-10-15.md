# Робочий сервер: read-only звірка — 15.10.2026

Перевірка виконана 15.10.2026 о 05:27 UTC через SSH із зафіксованим
ED25519 host key і публічними HTTPS GET. Не виконувалися deploy, restart,
recreate, міграції, SQL-записи, backup/restore або надсилання контрольного
push.

## Підсумок

Сервер відповідає зафіксованому операційному контракту: API доступне,
collector формує свіже спостереження, канал сповіщень не повідомляє про
помилку, а плашка технічних робіт вимкнена. Ознак нової runtime-поломки в
цьому зрізі не знайдено.

| Перевірка | Фактичний результат |
| --- | --- |
| `GET /api/health` | HTTP 200, `status=ok`, `alert_channel=ok`, `undelivered_alerts=ok`, вік спостереження 37 с |
| `GET /api/status` | HTTP 200, `maintenance=null` |
| Публічні API | `checkpoints`, `workload` і `privacy` повернули HTTP 200 |
| Контейнери | Сім контейнерів запущені; TimescaleDB `healthy` |
| Стабільність контейнерів | Для всіх семи `RestartCount=0`, `OOMKilled=false` |
| Systemd | `avelren-backup`, `avelren-device-retention` і `avelren-telemetry` timers активні; останні запускалися успішно; failed units немає |
| Ресурси | Диск: 14 GiB з 38 GiB зайнято (38%); доступно близько 2.7 GiB RAM; swap не використовується |

`avelren-backup-recovery.service` лишається inactive після успішного
oneshot-виконання; це очікуваний стан, не помилка. Наступний backup
запланований на 16.10 о 03:26 UTC, retention — на 04:00 UTC.

## Межі висновку

Health і runtime-статус не підтверджують показ push, звук, кнопку «ОК» чи
повтор на конкретному телефоні. Також цей зріз не є доказом нового
production image для виправлення повторів, не приймає резервне відновлення
і не дозволяє реліз 1.0.4. Ці етапи залишаються у
[реєстрі готовності](../RELEASE-READINESS.md).
