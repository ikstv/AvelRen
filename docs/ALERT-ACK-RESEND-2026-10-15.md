# Підтвердження кожної повторної доставки — 15.10.2026

Контракт: [повтори до ручного DELETE](ALERT-REPEAT-CONTRACT-2026-10-15.md).
Під час підготовки server package виявлено окремий дефект source-кандидата:
після успішного resend другий OK зберігав acknowledged_at від першої доставки.
Оскільки active-alerts порівнює last_sent_at з acknowledged_at, foreground
звірка могла залишити щойно підтверджену повторну картку активною.

Для threshold і ETA acknowledged_at тепер оновлюється, якщо останню
успішну доставку ще не підтверджено. Повторний ACK тієї самої доставки
лишає timestamp незмінним. GREATEST(now(), last_sent_at) не дозволяє
transaction-start timestamp позначити підтвердження раніше від доставки.
Alert лишається pending, ETA-ціль активна; термінальна дія — DELETE.
Schema, API payload, FCM payload, repeat interval і collector не змінені.

Незалежний review також знайшов попередній timing defect у notifier:
last_sent_at = now() записував початок транзакції ще до очікування FCM.
ACK в окремій транзакції під час цього очікування міг приховати наступну
успішну доставку. Тепер last_sent_at = clock_timestamp() записується після
успішного send. Регресія test_ack_during_send_does_not_hide_later_successful_resend
детерміновано commit-ить ACK під час fake FCM send, використовуючи реальні
notifier/API ролі PostgreSQL; для threshold і ETA старий код дав 2 expected
failures (268 deselected). Відтак кандидат містить API та notifier correction,
а не лише API. Failed-send visibility перевіряється наявним окремим тестом.

Межа протоколу: ACK містить alert ID, але не delivery-generation ID.
Затриманий ACK попередньої доставки не можна відрізнити від ACK нової.
Ця зміна не обіцяє cross-delivery retry identity і не змінює клієнтський API.

Регресія test_ack_dismisses_each_successful_resend у database/api/
test_repeat_alert_ack.py перевіряє два resend/ACK цикли для обох видів,
видимість active-alerts, pending і duplicate-ACK idempotence. На source
f87a4de з новим тестом:2 expected failures,108 passed; обидва падіння
відтворили старий acknowledged_at < last_sent_at. Новий green і повні
database/runtime результати записуються окремим receipt після завершення.
Проміжний API-only варіант: 110 API, 268 database і 705 unit tests passed.
Ці результати не замінюють фінальну перевірку notifier correction.

Фінальний source-кандидат: 110 API tests passed (2 deprecation warnings),
270 database tests passed, 705 unit tests passed (2 deprecation warnings).
Повний database run включає обидві timing-регресії та failed-send сценарії;
pg_dump під backup-роллю завершився успішно з попередженням TimescaleDB про
циклічні FK. Provenance verifier і ruff 0.16.1 пройшли; hosted CI використовує
іншу версію ruff і цим не замінюється. Linux isolated backup-manifest contract:
10 tests passed; первинний Windows запуск не пройшов через temp permissions.
Жодного зовнішнього запиту або реального FCM send у цих тестах немає.

Це source-підготовка, не production deployment, phone acceptance або Play.
Hosted CI, злиття і immutable runtime image ще не виконані. Штатний
ops/build-candidate-image.sh дозволяє образ лише з чистої main; feature-branch
кандидат не збираємо обхідною командою.
