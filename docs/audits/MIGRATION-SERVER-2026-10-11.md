# Перенесення й робочий сервер — 11.10.2026

Це датований підсумок read-only перевірки близько 12:40–13:00 за Києвом
та наступної перевірки гілок. Він не є дозволом на розгортання чи restore.
База звірки ORIGINAL main: `e84e726157c4e8b66d2174c00e4984301d23cd21`.
Контрольні джерела: AvelRen `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27`
і AvelRen-ops `5be9da8b433813a664b4d4e21a0a92bae91c56a0`.

## Що підтверджено на сервері

| Компонент | Спостереження | Межа висновку |
| --- | --- | --- |
| Контейнери | Сім running, DB healthy, RestartCount=0 | Не доказ тотожності всіх образів main або відсутності попереднього recreate |
| Collector | 1438/1438 циклів за попередні 24 години успішні; fetch/derived errors=0; останні 15 циклів через 60 секунд | Запити до єЧерги для аудиту не додавалися |
| SQLite spool | У стабільній копії в пам'яті 1438 acked, started/pending=0 | Не приймання recovery зі старого DB snapshot; production SQLite не відкривали для запису |
| БД | TimescaleDB 2.30.1; SHA журналу 001–016 збігаються з main | Не завершення ownership/ACL adoption |
| API | health HTTP200/status=ok, свіжі спостереження; 38 checkpoints | Не повна перевірка всіх API/Android сценаріїв |
| Прогноз | Для ID 1, 6, 17, 29 збережені non-null scores; API HTTP200/status=no_signal, reason=null | Не оцінка точності моделі або перевірка push |
| Watchdog | Один admin device із FCM token; daily_status 11.10 прийнятий FCM о 12:02 за Києвом | Не доказ показу повідомлення на телефоні |
| Backup/retention/telemetry | Останні systemd виконання success, timers active; backup stamp близько 06:32 за Києвом | Новий cloud artifact не завантажували й не відновлювали |

Попередження watchdog «no admin devices» належать 10.10, а не поточному
стану. Notifier працює, але контрольний push у цій перевірці не надсилали.
Failed systemd units немає; диск близько 35% використаний, swap не задіяний.

Фактично імпортований Python package — під `site-packages`, а не build-копія
`/app/src`. Звірка SHA встановлених модулів показала: API `api.py` і watchdog
`watchdog.py` відповідають main; collector `collector.py` та `echerha.py`
відповідають точному head PR #113 `68f9e98`. Решта runtime змішана.
Checkout сервера лишається `81e5b047f8f18c42ca46a59f86495f71d0681af0`
із локальними змінами; його не можна просто замінити поверх.

Collector і watchdog підключаються як legacy superuser `avelren`.
API/notifier/surge worker використовують окремі non-superuser ролі.
Наявність цільових ролей не доводить переходу на них.

## Підготовлені PR

Оновлення інтеграції 11.10: #106 злитий merge-комітом `4417739`,
#107 — `297ae1d`, після 7/7 і 5/5 успішних перевірок відповідних heads.
#107 перед злиттям переведено з бази #106 на main. Production adoption
цим не виконується. #113/#114/#115 оновлено merge із цією main без
переписування історії: heads `af5c2a6`/`adbd49c`/`a9db13e`; новий CI
ще має підтвердити їх. Таблиця нижче зберігає попередній зріз.

Статуси нижче — зріз 11.10, перевіряти заново перед злиттям.
Усі п'ять PR ще відкриті як draft; жоден цим документом не оголошено злитим.

| PR | Head | CI на момент запису | Результат |
| --- | --- | --- | --- |
| [#106](https://github.com/ikstv/AvelRen-ORIGINAL/pull/106) | `1c77c0c` | 6/7 success, database виконується | Read-only privilege gate; конфлікт із main усунуто без force-push |
| [#107](https://github.com/ikstv/AvelRen-ORIGINAL/pull/107) | `b1910ef` | 4/5 success, database виконується | Disposable ownership/ACL forward/inverse; база — #106 |
| [#113](https://github.com/ikstv/AvelRen-ORIGINAL/pull/113) | `68f9e98` | 7/7 success | Перенесення встановленого collector pacing і відповідні acceptance тести |
| [#114](https://github.com/ikstv/AvelRen-ORIGINAL/pull/114) | `ec7ab8e` | 6/6 success | Одна спроба post-restore hook при HUP/INT/TERM, збереження первинного exit status |
| [#115](https://github.com/ikstv/AvelRen-ORIGINAL/pull/115) | `a03f2fa` | 6/6 success | Зупинка п'яти клієнтів після restore failure з перевіркою стану |

Локальна спільна гілка з цими п'ятьма heads пройшла 453 backend unit-тести,
чотири provenance manifests, 8 interruption і 6 failure-state контрактів,
8 engine-контрактів та production engine/orchestrator контракти.
Це локальна перевірка сумісності, не main CI й не production restore E2E.
Під час поєднання збережені всі записи release readiness.
Окремий повторний прогін `scripts/test_database.sh adoption` на незмінній
спільній гілці пройшов 43 DB-тести (83 поза обраним набором), обмежений
backup pg_dump та видалення disposable ресурсів. Перший прогін, під час
якого checkout помилково перемкнули, не враховується як доказ.

## Що лишилося

1. Завершити CI #106/#107, інтегрувати PR в порядку залежностей і перевірити
   спільну main. Новий head потребує власних результатів CI.
2. Підготувати production ownership/ACL executor, відкат і окреме приймання
   DSN cutover collector/watchdog. #107 дозволяє зміни лише в disposable DB.
3. Прийняти актуальну резервну копію в ізольованій БД та окремо спроєктувати
   узгоджене відновлення PostgreSQL/SQLite. Поточний modern restore guard
   відхиляє standalone/spool topology; встановлений legacy CLI відрізняється.
4. Перенести external health monitor і lifecycle його alerts/issues:
   scheduled workflow досі працює в старому AvelRen; успішний probe не доводить
   доставки alert. Старий monitor не вимикати до приймання заміни.
5. Завершити залишкові regression/security перевірки, runbooks і реєстр
   release/phone acceptance; узгодити історичні файли й фінальну інвентаризацію.

132 записи попереднього аудиту мають класифікацію 18 integrated,
25 superseded, 24 historical-preserve, 56 needs-work, 9 needs-decision.
Це записи файлів/контрактів, не 56 окремих функцій і не відсоток готовності.
Старі джерела зберігаються до фінального приймання.

## Як підтримувати стан

Після зміни оновлювати [залишки](../MIGRATION-REMAINING.md) і
[готовність релізу](../RELEASE-READINESS.md), зазначаючи commit, дату,
конкретний результат та обмеження. Код, CI, main merge, deployment, APK,
телефон і Play мають окремі докази. Старі аудити зберігати датованими;
новий підсумок має явно уточнювати попередні факти.

У цьому аудиті не виконували записів на production, restart/deploy,
міграцій, робочого restore, APK/Play або додаткових upstream-запитів.
