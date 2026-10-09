# Незалежний review дослідницького стенда

Review виконав окремий gpt-6-astra у свіжому контексті, лише читання.
Початковий діапазон `ce86214..1ad4f5c`; один fix pass — `1e78afe`.
Виявлено три Important, один Minor, жодного Critical. Виправлення
підтверджені тим самим reviewer: 90 research PASS. Виконавець окремо
отримав 31 real DB PASS, 408 backend unit PASS, Ruff та provenance PASS.
CI і повні результати фіксуються окремо, не виводяться з цього review.

Повний результат перевірено тим самим reviewer: 190 CSV rows і 476
scenario metric rows, actual origins/horizon, hashes/межі 3 003 292 records,
незмінний protocol і відбір лише на selection. Невиправлених Important немає.
У звіті виправлено твердження статистичної незалежності: чотири окремі
за правилом об’єднання епізоди одного дня не доводять незалежність.
На однакових чотирьох ID pooled P/R=50%/50%, frozen=100%/100% (2/2);
основний результат pooled по 38 чергах має окремий знаменник 4 події.

## Виправлені розбіжності

1. Хвилинна готовність не доводила можливості погодинного прогнозу.
   Тепер conditional recall спирається на фактичний origin, момент
   рішення, свіжість/якість і первісний horizon. Синтетичний контрприклад
   із відновленням історії між погодинними прогнозами дає нуль доступних
   подій; overall recall не виключає таку пропущену подію.
2. Повторна підписка без ACK зберігала expired alert. Тепер ідентичність
   епізоду відокремлена від alert підписки; re-enable створює новий ID,
   приєднання використовує фактичний час, ACK зберігається. Є DB parity
   з ACK, без ACK і першого приєднання до активного епізоду.
3. Додано unknown intervals, їх union, множини зачеплених origins,
   окремі знаменники готовності, спроби/нагадування/retry/cancel і
   пригнічення. Ці поля потрапляють у CSV/JSON і деталі інтерактивного звіту.
4. Початковий Minor про історичні counts підвищено до Important:
   misleading phase counts могли змінити висновок користувача. Давні
   епізоди позначені prior_history/carry_in; +200 має явну область фази.

## Визначення додаткових агрегатів

Origins — фактичні prediction attempts із парою `(observation_origin,
clock_tick)` у визначеній області попереджень. Окремо рахуються
непридатне минуле, невідомі endpoints і сумнівні майбутні події.
Union майбутніх невідомостей не дублює origin, який зачепили дві причини.
Розрахунки з непридатним минулим не стають доступними, навіть коли
майбутнє можна оцінити. Оцінюваний майбутній час рахується незалежно
від score; його знаменник — секунди об'єднання хвилинних tick-інтервалів.

Initial alerts — епізоди forecast/fact, створені у фазі; precision
використовує тільки початкові forecast alerts. Initial attempts —
ordinal=1, reminders — ordinal>1, retries — сума attempt_count−1;
усі за часом створення спроби у фазі. Accepted attempts — прийняття
синтетичним transport, без твердження про прослуховування. Cancels —
записи cancel trace у фазі. Suppressed ACK/disabled ticks — сума хвилин
активних підтверджених/вимкнених alert; це alert×minute, а не число
гіпотетичних голосових повідомлень. Unknown trace для selected development
збережений локально; selection trials містять усі counts без повторення
великих списків origins. За потреби trace відтворюється тим самим replay.

## Рішення виконавця під час реалізації

| Рішення | Причина та практична межа |
| :--- | :--- |
| Dataset immutable mapping/tuples | Input не змінюється між fit; споживачі не додають rows in place |
| Додаткові поля завершеності Event | Censor/gap/+200 overlap мають відрізнятися; ширший внутрішній контракт |
| HistoryIndex reuse і origin/tick пара | Менше повторних сканувань, причинна cadence; перевірено DB parity |
| supported_ids, engine.step/ack, availability RLE | Frozen N/A перед predict; RLE треба рахувати за тривалістю |
| delivery_attempts/cancels і два synthetic сценарії | Повтори не множать прогноз; не доказ реального прослуховування |
| fit kwargs regularization/scales, threadpoolctl | Погоджена сітка і train-only масштаби, один BLAS thread |
| Окремий EvaluationContext | Replay не доводить майбутнє; caller передає правильну queue/fold історію |
| Data app локально, authored JSX/CSS у Git | Приватні rows і plugin runtime не публікуються; UI потребує Data plugin |
| CLI orchestration і причинний ReplayCache | Планові модулі самі не запускали пілот; cached parity перевірено |
| SQL export/validator у research package | Synthetic CI не залежить від приватного transport/SSH |
| Денний read-only snapshot | Короткі запити; це не один глобальний snapshot, backfill — нова версія |
| Реальні forecast origins для доступності | Пригнічені/невдалі обчислення не маскують пропущені події |
| Trace лише selected development | Selection counts повні; повний trace відтворюється окремим replay |

## Відкладене дрібне розходження

Після callback старого, вже видаленого subscriber alert дослідний
DeliveryReplay ставить додатковий cancel; runtime за відсутнього alert
повертається одразу. Новий alert захищений. Це не впливає на базові
`success_no_ack` / `ack_first`, добір або їхні P/R; counts саме цього
додаткового synthetic callback-сценарію не мають повного паритету.
Відкладено за правилом одного fix pass; не видаємо стенд за реконструкцію
фактичної історичної доставки.

## Що review не оцінює

Production/Android/Play поза обсягом. Історичні доставки на телефони
не реконструюються без ingestion/device/ACK history. Майбутній frozen
holdout тут не оцінюється. Повне порівняння має окремий RESULTS receipt.
