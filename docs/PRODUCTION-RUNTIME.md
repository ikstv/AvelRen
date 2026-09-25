# Пакет production runtime

Production Compose runtime перенесено зі старого `AvelRen` з checkout-коміту
`81e5b047f8f18c42ca46a59f86495f71d0681af0` та адаптовано до шляхів монорепозиторію
(`services/backend`, `ops/`). Пакет описує конфігурацію, але цей checkout не
розгортався на сервері.

## Конфігурація хоста

Очікуваний шлях checkout на сервері — `/opt/avelren`. `.env`,
`docker-compose.override.yml`, Firebase credentials і telemetry snapshot
залишаються поза Git. `.env.example` містить порожні секрети й DSN та безпечні
несекретні значення за замовчуванням. Production override може містити
migration pin та налаштування переходу; не додавайте його до Git і не
підміняйте ефективну Compose-конфігурацію запуском лише основного файла.

## Межа міграцій

Сервіс `migrate` доступний лише через явний профіль `migrate`; звичайний запуск
Compose не повинен застосовувати міграції. Під час read-only звірки 2026-09-23
у production були застосовані міграції 001–009, їхні контрольні суми збіглися
з приватним репозиторієм. 010 і 011 у репозиторії є, але на production не
застосовані. Це не дозвіл їх запускати.

## Склад і залишок робіт

Compose описує DB, migrate runner, collector, notifier, watchdog, API та Caddy.
Caddy обслуговує privacy page з `ops/static/`. Snapshot script і telemetry
systemd units тепер також присутні в `ops/`; дивіться
[опис telemetry units](TELEMETRY-SYSTEMD.md). Production вже мав активний
telemetry timer під час останньої read-only звірки. Виконувальну інструкцію
розгортання не переносили: історичний ops runbook містить команди, що вже не
відповідають поточному migration/adoption процесу. Її треба окремо звірити й
підготувати після явної команди та дозволу власника.

Restore CLI та verifier перенесено, але production restore orchestrator і
актуальний runbook лишаються окремою роботою. Жоден production сервер,
database, secret, service чи image у межах цих змін не змінювався.

## Локальні перевірки

Compose contract перевіряє модель із тестовими маркерами, не запускаючи служби.
Backend image було зібрано локально з Docker Desktop. Telemetry unit contract
перевіряє статичні директиви service і timer. Ці перевірки не підтверджують
розгортання на сервері або роботу systemd на production.
