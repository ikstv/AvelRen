# Оновлення FCM-токена під час відправлення — 12.10.2026

Source кандидат: `codex/notifier-token-race-20261012`, база `eed0cb0`.
Зміна обмежена legacy notifier та його cancel outbox. Політика перенесення
токенів між devices/subscriptions і surge delivery не змінюється.
Первинний source hash notifier збережено в `CORE-PROVENANCE.json`;
оновлено лише поточний revision hash і notes. Попереднє розширення
normal → surge → cancel описано в
[surge implementation](SURGE-MONITOR-IMPLEMENTATION.md).

## Контракт

Notifier читає T1, надсилає T1 до FCM та може отримати UNREGISTERED уже
після того, як API зберіг T2. `_disable_device(conn, device_id, sent_token)`
очищає токен одним умовним UPDATE за device ID і точним sent_token;
повертає bool із фактичної кількості змінених рядків. Токени не додаються
до журналу. Обидва callers передають саме відправлене значення.

Normal threshold/ETA alert після dead-token помилки залишається pending,
send_count і last_sent_at не змінюються. Для cancel успішне очищення
поточного токена зберігає негайне mark_abandoned. Якщо UPDATE не змінив
рядок, cancel виконує record_attempt: attempt_count +1, last_attempt_at,
abandoned_at лише за чинною межею created_at старше години. Нового send
у цьому циклі немає; наступний цикл читає поточний токен. Недеструктивна
FCM-помилка зберігає попередню поведінку. Порядок normal → surge → cancel
та surge interface незмінні. Міграції й права БД не змінені.

## Локальні докази

`services/backend/tests/database/test_notifier_token_race.py` використовує
наявну disposable database fixture, справжні notifier/API ролі й підміняє
лише зовнішній FCM send. Coroutine блокується після читання T1; незалежне
API-підключення commits T2; після цього повертається synthetic UNREGISTERED.
Перевірки читають фактичні токени й lifecycle із PostgreSQL.

Команда з кореня репозиторію:

```sh
AVELREN_ADOPTION_TEST_SELECTOR=notifier_token_race bash scripts/test_database.sh adoption
```

До виправлення: 6 failed, 8 passed, 176 deselected; усі шість гонок
втрачали T2 (`None` замість нового токена). Після виправлення: 14 passed,
176 deselected. Покрито threshold/ETA normal і cancel, retry/age-limit,
негайне очищення поточного dead token та недеструктивний INVALID_ARGUMENT.
Для свіжого cancel перевірено успішне прийняття на T2 наступним циклом.
Default database runner і Timescale upgrade runner збирають увесь
`services/backend/tests/database`, отже новий модуль входить в обидва
набори без зміни selector/runner. Повний upgrade rehearsal у цьому кроці
не запускався. FCM та єЧерга не опитувалися.

Повний backend unit suite у cached Linux/Python 3.14 контейнері, readonly
checkout і network=none: 669 passed, 2 dependency deprecation warnings.
Disposable `/tmp` потребував `size=4g`: початковий менший tmpfs спричинив
два spool quota-test failures через чинний low-free-space guard; повтор
із достатньою вільною місткістю пройшов без зміни source/tests.

Database runner завершився з exit 0; штатний pg_dump має попередження TimescaleDB
про circular foreign-key constraints `continuous_agg`. Це не доказ restore.
Hosted CI, незалежний review, злиття, production deployment і перевірка
доставки на телефоні ще очікуються; локальні результати їх не закривають.
