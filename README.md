# AvelRen

Історія завантаженості пунктів пропуску на кордоні України — для вантажівок.

Державний сервіс [єЧерга](https://echerha.gov.ua/workload/1/1) показує лише
поточний зріз і не зберігає історію. Водій бачить «3 дні 11 годин» і не може
зрозуміти, чи це норма для цього пункту, чи аномалія, і коли їхати вигідніше.

AvelRen накопичує спостереження щохвилини й дає те, чого немає в першоджерелі:
динаміку, порівняння пунктів і ґрунт для прогнозу.

## Залізне правило

> **До `echerha.gov.ua` звертається лише наш сервер. Клієнти — ніколи.**

Жоден клієнт — веб, Android, iOS, сторонній скрипт — не ходить у єЧергу напряму.
Усі читають наш API.

Це не стильова вподоба. Державний API віддає `x-ratelimit-limit: 60`, тож тисяча
клієнтів із власними запитами миттєво впирається в ліміт, ловить бани по IP і
кладе сервіс — і чужий, і наш. Один збирач, один запит на 60 секунд.

Порушення цього правила — архітектурна помилка, а не оптимізація. Якщо клієнту бракує
даних, розширюємо наш API, а не пускаємо його назовні.

## Як це працює

```
echerha API ──(1 запит / 60 с)──> collector ──> PostgreSQL + TimescaleDB
                                                      │
                                     Caddy ──> api ───┘ ──> клієнти
```

- **collector** — опитує єЧергу рівно раз на 60 секунд, пише спостереження;
- **api** — FastAPI, віддає дані **тільки з нашої БД**, ніколи не проксює запит;
- **db** — PostgreSQL 16 + TimescaleDB, часовий ряд зі стисненням;
- **caddy** — HTTPS і реверс-проксі.

`collector` та `api` — один Docker-образ, дві різні команди запуску.

## Межа операційної авторизації

> **УВАГА: злиття PR #29 НЕ АВТОРИЗУЄ жодну production-операцію.**

Зокрема, merge PR #29 не дозволяє `production adoption`, `production restore`,
`deployment`, `credential generation`, `credential rotation`, `legacy NOLOGIN`,
`legacy REVOKE CONNECT` або закриття issue #15. Production adoption потребує
окремої явної авторизації (`separate explicit authorization`). Issue #15
залишається **OPEN навіть після merge**, доки production rollout і retirement
legacy-ролі не будуть окремо виконані та доведені безпечними.

## Де що написано: політика проти стану

`PROJECT_STATUS.md` — **тільки політика**: межі авторизації, процедури,
bring-up, CI parity. Змінюється рідко, свідомо і людиною.

`STATE.md` — **тільки стан**: наскільки прод відстає від `main`, що заїде в
наступний Gate 11 re-prep, відкриті PR та issues, відставання гілок.
Генерується `scripts/generate-state.sh`; **руками не редагується** — будь-яка
правка зникне при наступній регенерації.

Розділення існує тому, що волатильні факти, які підтримувалися руками,
протухали швидше, ніж їх оновлювали, і двічі ввели в оману читача, який
приходить без контексту й не має як перевірити написане. Єдиний волатильний
факт, якого git знати не може, — комміт, на якому стоїть прод; він живе одним
рядком у `deploy/PROD_PIN` і оновлюється оператором під час re-prep, у тому ж
атомарному кроці, що й evidence та копія gate-runner. Пін, якого немає в
історії `main`, генератор відхиляє і відмовляється рахувати відстань, замість
того щоб видати правдоподібне, але неправильне число.

## Джерело даних

```http
GET https://back.echerha.gov.ua/api/v5/workload/1
Accept: application/json
Content-Type: application/json
X-Client-Locale: uk
X-User-Agent: UABorder/3.9.0 Web/1.1.0 User/guest
X-Device-Id: <persistent-uuid>
X-Device-Name: AvelRen collector
```

`/1` — вантажівки, `/2` — автобуси. Зараз у скоупі лише вантажівки.
Гостьовий контракт v5: без цих заголовків сервіс віддає `403`. `X-Device-Id` —
persistent UUID гостя (див. `ECHERHA_DEVICE_ID`), не секрет. Авторизації немає;
reCAPTCHA стоїть на бронюванні, не на статистиці.

Поле `wait_time` — у секундах. `vehicle_in_active_queues_counts` — авто в черзі.

## Ролі PostgreSQL

Канонічна модель має сім окремих LOGIN-ролей. Кожен application/runtime-сервіс
отримує лише свій `DATABASE_URL`; runtime-контейнери не отримують admin,
migrator, backup або DSN сусідніх сервісів. Контейнер `db` отримує лише
`POSTGRES_USER`, `POSTGRES_PASSWORD` і `POSTGRES_DB` як bootstrap configuration,
а не application DSN.

| Роль | Єдина відповідальність |
|---|---|
| `avelren_admin` | Лише `bootstrap`, `adoption` і `restore`; не використовується застосунками у runtime. |
| `avelren_migrator` | Лише `migration`, DDL, володіння application-об'єктами та `schema`/`catalog verification`. |
| `avelren_backup` | Лише `pg_dump`; без запису, DDL або restore. |
| `avelren_collector` | Runtime SQL для `countries`, `checkpoints`, `observations`, `collector_runs` і поточного threshold/ETA lifecycle; без доступу до devices та health lifecycle. |
| `avelren_notifier` | Runtime SQL для `pending notification`, `delivery` state і очищення невалідних `FCM` токенів; без запису спостережень чи health state. |
| `avelren_watchdog` | Runtime SQL читання `observations` і `collector_runs`, запису лише `health_alerts` та SELECT лише `devices.id`, `devices.is_admin`, `devices.fcm_token` для health notifications; `devices.secret_hash`, усі інші непов'язані device fields і будь-які device writes заборонені. |
| `avelren_api` | Лише endpoint-authorized `registration`, `authentication`, `subscription`, `ETA`, `history` і `telemetry` SQL; не DDL і не collector writes. |

Порожні змінні `AVELREN_*_PASSWORD` і `AVELREN_*_DSN` перелічені в
`.env.example`. Реальні значення належать лише авторизованому secret store та
host configuration і не потрапляють у Git, документацію, логи чи evidence.

## Fresh install

Fresh install є ідемпотентною послідовністю, а не однією транзакцією:

1. `create roles` через `bash deploy/postgres-bootstrap.sh fresh`.
2. `create database` з owner `avelren_admin`.
3. Provision `TimescaleDB` від імені admin.
4. Закрити `database/schema ACL` від `PUBLIC`.
5. `migrate` від імені `avelren_migrator`.
6. Виконати privilege та isolation `contracts`.
7. Лише після GREEN перевірок `start runtime`.

`postgres-bootstrap.sh fresh` потребує `AVELREN_ADMIN_DSN` і всіх семи
`AVELREN_*_PASSWORD` у середовищі процесу. Значення не передаються аргументами
командного рядка. Вивід `migrate_handoff` означає тільки перехід до окремого
migration gate; він не дозволяє пропустити migrations або contracts. Якщо етап
падає, runtime не запускають. Опція `--disposable-empty-test` дозволена лише для
доведено нової порожньої тестової БД і не є production cleanup.

Режим `postgres-bootstrap.sh roles-acl` — **disposable-only**. Він переписує
ownership і ACL уже наявної БД, тобто виконує ту саму за класом мутацію, що й
adoption, і тому вимагає `AVELREN_TEST_DB=1` та імені цілі з `test` або `ci`.
Застосування ролей і ACL до production-БД виконується виключно через
`deploy/postgres-adopt.sh`, який спершу доводить preflight-evidence,
forward/inverse плани та fingerprints і має перевірений inverse rollback.

Підготовка локального host configuration:

```bash
cp .env.example .env
```

Усі secret/DSN placeholders у шаблоні навмисно порожні. Порядок перевірок і
окремі повільні security/DR/adoption gates описані в
[`docs/backend-testing.md`](docs/backend-testing.md).

Після окремо авторизованого запуску та проходження всіх gate перевірка API:

```bash
curl -s localhost:8000/health
```

## API

| Метод | Шлях | Опис |
|---|---|---|
| `GET` | `/health` | стан сервісу та свіжість даних |
| `GET` | `/checkpoints` | довідник пунктів пропуску |
| `GET` | `/workload` | останній зріз по всіх чергах |
| `GET` | `/history/{checkpoint_id}` | історія пункту за період |

## На майбутнє

[Прогноз черг по кожному КПП](docs/forecast.md) — на накопиченій історії.
Не раніше жовтня 2026: тижнева сезонність потребує 8–12 тижнів даних.

## Ліцензія

Дані належать їхньому джерелу — державній системі «єЧерга».
