# Контракт повторних alert — 15.10.2026

Поріг черги й ціль ETA є довготривалими підписками. Їхній створений alert
лишається `pending` і повторюється notifier-ом раз на п’ять хвилин, доки
власник не скасує відповідну підписку або ціль у меню.

Кнопка «ОК» записує момент підтвердження та прибирає тільки поточну картку.
Вона не деактивує ETA-ціль, не закриває alert і не припиняє повторів. До
успішної наступної доставки foreground reconciliation не має відтворювати
підтверджену картку; після неї повертається той самий ID alert.

Collector не завершує pending alert, коли кількість у черзі зменшилася або
час ETA уже минув. Єдина terminal дія — ручний DELETE підписки чи цілі; він
каскадно прибирає alert і ставить cancel у outbox.

Цей документ фіксує source-revision для `subscriptions_api.py`, `alerts.py`,
`eta.py`, `cancels.py` та `notifier.py`. API payload, FCM credentials,
collapse keys, TTL, cadence collector-а та схема БД не змінюються.

Перевірки: API ACK і reconciliation, notifier resend/error, ручне
скасування, а також regression collector replay. Локальні API та database
набори пройшли; production, телефон, APK/AAB і Play цим контрактом не
прийняті.
