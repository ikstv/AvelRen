# Production DSN collector/watchdog — 14.10.2026

Після окремого дозволу власника обидві операції прийнято. Підсумкова read-only
перевірка о **19:08:06 за Києвом (16:08:06 UTC)** підтвердила watchdog на
`avelren_watchdog`, collector на `avelren_collector`. Це завершує саме перехід
цих двох runtime DSN, підготовлений у [попередньому аудиті](POSTGRES-CUTOVER-READINESS-2026-10-14.md).

| Перевірка | Доказ |
| --- | --- |
| Watchdog | phase `accepted`, systemd Result `success`, exit 0; весь операційний інтервал приблизно 337,840 с |
| Collector | phase `accepted`, systemd Result `success`, exit 0; весь операційний інтервал приблизно 211,095 с |
| Ліміт | Кожна операція завершилася в межах початкового 900-секундного бюджету |
| Runtime | Сім контейнерів running, restart count 0; образи збережені |
| Collector | Три природні цикли без помилок за 120 с; capture-only=false, mode_ack=false, pending=0 |
| API | health `ok`, вік останнього спостереження під час перевірки 39 с |
| Резервне копіювання | Попередня пара лишилася `published`; нове захоплення не запускалося, backup/recovery services inactive |
| Timer | Після повернення active; наступний запуск за readback — 15.10 о 06:27:05 за Києвом (03:27:05 UTC); LastTrigger і stamp незмінні |

Watchdog image: `sha256:77e55b1dc74dac65a665ab1e0fd00269a62b821bd337fcf957b600b006e257af`.
Collector image: `sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3`.
Інтервали від stop ACK до container StartedAt становили відповідно 1,093 с і
60,877 с. Це **не** вимір повної недоступності сервісів: операційні інтервали
вище також включають перевірки та приймання. Відкат не знадобився.

Джерело — приватний структурований `final-acceptance.json`, звірений оператором
і незалежно прочитаний під час підготовки документа. Сирі runtime bindings,
секрети, DSN та приватні файли сюди не переносяться.

Межі: не виконано retirement legacy ролі або перенесення власників Timescale
jobs; це не повний production DR і не нове відновлення резервної копії.
[Раніше прийняте ізольоване відновлення](PAIRED-LEGACY-RESTORE-2026-10-14.md)
залишається окремим доказом. Цей аудит не приймає телефонні FCM/голос/ACK,
Play, зовнішній scheduled monitor або завершення всього перенесення. Health
і час наступного timer є датованими спостереженнями, а не постійною гарантією.
