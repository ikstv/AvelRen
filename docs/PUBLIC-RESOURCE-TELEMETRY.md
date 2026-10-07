# Публічні ресурси сервера

Кандидат 07.10.2026, не встановлений на production.

Екран показує CPU, RAM, Disk Memory Usage і Traffic Usage.
RAM = MemTotal−MemAvailable; диск використовує df used, не total−available.
Нові поля знімка — точні bytes; старі поля збережені. Недоступне
вимірювання не підміняється нулем. Публічний GET /api/server/status
додає memory/disk/traffic до чинних CPU-полів; кожен блок має власні
used_bytes/total_bytes/measured_at/stale. Traffic додатково billing_month.

Клієнт робить один запит при відкритті вкладки, далі лише вручну.
Локальний таймер прибирає прострочені цифри без HTTP. Невдалий refresh
позначає всі попередні показники неоновленими.

## Traffic: окремий незавершений gate

Офіційна схема Hetzner підтверджує included_traffic та nullable
outgoing_traffic: https://github.com/hetznercloud/hcloud-go/blob/main/hcloud/schema/server.go.
Правила billing: https://docs.hetzner.com/cloud/billing/faq/.
Вони не дали в цій перевірці точного timestamp/ідентифікатора меж
розрахункового періоду для надійного датування snapshot. Доступ конкретного
сервера та read-only токен не підтверджені. Жодного токена не створено.

За погодженим fail-closed дизайном live traffic залишається недоступним.
Не використовується /proc/net/dev і не вшивається 20 ТБ. Погодинний
provider collector/timer не реалізовані й не встановлені: спершу підтвердити
billing period і доступ. API не виконує запитів до Hetzner. Preview використовує
лише явно синтетичні обсяги для перевірки інтерфейсу, не billing evidence.

Гілка не зливається. Production deployment, secrets/timer та clean-main
APK/телефонне приймання потребують окремих дозволів.

## Перевірки кандидата

Локально: backend unit 395; API integration 78; watchdog 9 і snapshot 16;
Android JVM 246, compile/lint успішні. Dependency deprecation warnings,
34 Android lint warnings/6 hints і Timescale pg_dump circular-FK warning
зафіксовані, не трактуються як відсутність зауважень.
Незалежний read-only review не знайшов Critical; bounded reader до 1 МіБ
додано після перевіреного RED, full unit GREEN. Залишені minor:
CPU/resources можуть походити з двох сусідніх атомарних знімків;
over-quota preview має повний градієнт, не суцільний червоний;
валідація billing_month має бути завершена до live traffic.
Це не CI конкретного head, deployment чи телефонне приймання.
