# Caddy: перевірка перед оновленням, 28.09.2026

## Стан

У гілці `codex/caddy-image-refresh` виправлено втрату
`X-AvelRen-Client-IP` та оновлено pin Caddy з 2.9.1 на 2.11.4.
Тест двічі виявив помилку до виправлення; після виправлення повна
матриця пройшла на обох версіях із двома різними клієнтськими адресами.
Production, старі репозиторії та TimescaleDB не змінювалися.
Локальна перевірка не замінює CI точного head, merge або deployment.

## Відтворення

`bash ops/caddy-integration-test.sh` створює окрему внутрішню Docker-мережу,
синтетичний API та Caddy без опублікованих портів. Домен розв'язується
мережевим alias усередині тесту; до production і первинного джерела
запитів немає. Лише для тесту додається `tls internal`.

До виправлення `caddy validate` проходив. Запит `/api/health?probe=1` доходив до
фікстури як `/health?probe=1`, але серед отриманих заголовків відсутні
і `X-Forwarded-For`, і `X-AvelRen-Client-IP`. Тест завершувався з кодом 1.

## Причина та вплив

У вихідному `ops/Caddyfile` для одного заголовка були задані і видалення, і встановлення.
У [коді Caddy 2.9.1](https://github.com/caddyserver/caddy/blob/v2.9.1/modules/caddyhttp/headers/headers.go)
`HeaderOps.ApplyTo` виконує `Set` перед `Delete`: встановлене значення
потім видаляється незалежно від порядку рядків Caddyfile.

`services/backend/src/avelren/ratelimit.py` без цього заголовка використовує
`request.client.host`. За конфігурації, де це адреса проксі, різні користувачі
отримають спільний лічильник запитів. Це висновок із коду, а не підтвердження
поточного production-стану чи причини минулого блокування адміністратора.

## Виправлення та перевірки

За GO власника залишено встановлення заголовка адресою TCP-клієнта без
суперечливого видалення. Set замінює надіслане клієнтом значення.
Видалення недовіреного `X-Forwarded-For` збережено.

- Старий образ: `caddy:2.9.1-alpine@sha256:b4e3952384eb9524a887633ce65c752dd7c71314d2c2acf98cd5c715aaa534f0`.
- Новий образ: `caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b`.
- [Офіційний реліз](https://github.com/caddyserver/caddy/releases/tag/v2.11.4)
  містить security/bugfix зміни; це новіший patch, ніж 2.11.3 зі старого PR #143.
- На обох образах: validate, prefix/query, точний IP із підробленим заголовком
  та без нього, два клієнти, privacy, fallback, HTTP→HTTPS 308,
  приймання 1 KB / відхилення 65537 bytes з 413, gzip — успішно.
- Backend unit: 200 passed, два попередження deprecation Starlette/httpx/anyio.
- CI scopes: 14 examples; provenance та Android source/asset checks — успішно.
- Новий інтеграційний тест додано до database workflow.

Тест використовує приватний CA без перевірки довіри лише в ізольованій
мережі; він не перевіряє production DNS, ACME/Let's Encrypt чи реальний
сертифікат. CVE-скан Caddy в цьому кроці не виконувався.
Перший запуск Compose-контракту на Windows зупинився через відсутній
host Python; це не помилка Caddy. Повний Compose/DB/restore CI потрібно
перевірити перед merge. TimescaleDB та залишок #143 не закриті.
Зміна production потребує окремого GO та перевірки bind-mounted Caddyfile
усередині контейнера перед reload і після відкату.
