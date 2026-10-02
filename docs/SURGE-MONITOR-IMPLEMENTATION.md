# Експериментальний моніторинг напливу: реалізація

Гілка `codex/experimental-surge-monitor`, основа main `857eb61`, залежність
PR #72 `e68e731` приєднана комітом `d134c0b`. Правила єЧерги незмінні.
Якість 99% не підтверджено; прогноз експериментальний.

## Схема 016 та права

Окремі таблиці підписок, прогнозів, подій, повідомлень, стійких спроб
доставки та стану КПП. Нові таблиці й послідовності мають SELECT для backup.
Міграції 001–015 не змінені. Потрібні 015 і 016 у погодженому порядку;
production pin не змінювався.

`surge-bootstrap.sql` створює обмежену роль `avelren_surge` як NOLOGIN.
LOGIN/пароль надається окремою погодженою процедурою розгортання; чинні
паролі не змінюються. Worker читає спостереження, підписки й capability,
записує тільки власні події/стан та cancel-outbox. Немає доступу до
secret_hash, Admin, зміни observations або DDL. API має окремі права
підписок/ACK/capability, notifier — повідомлень і спроб доставки.

Зміни перенесених файлів зберігають їхнє походження в manifests:

- `migrate.py`: нові об'єкти у fail-closed перевірці порожньої історії.
- `schema_verify.py`: optional 016, повний перелік колонок, унікальні
  обмеження та partial index; зберігається контракт 015 із PR #72.
- `schema_gate.py`: перевірка exact migration та об'єктів нової функції.
  Загальний мінімум чинних служб залишається 015, а не 016.
- `postgres-bootstrap.sh`: додатковий NOLOGIN bootstrap та CONNECT/USAGE
  для окремої ролі. Застосована міграція 010 не редагується.
- `restore-engine.lib.sh`: шість таблиць і п'ять послідовностей у двох
  allowlist; вони обов'язкові тільки за записаної 016.

## Перевірки 02.10.2026

На синтетичних даних ізольованого Compose-проєкту: 36 тестів БД,
311 модульних тестів, перевірка allowlist (21 таблиця/11 послідовностей)
і штатна restore-репетиція з TimescaleDB hooks пройшли. Результат
належить тестованій гілці; це не production-приймання й не CI.
Нові API/Android/доставка ще реалізуються. Production не змінювався.


## Епізоди та worker

Хвилинний worker читає тільки нашу БД. Прогноз зберігається раз на
годину за Києвом, із майбутнім вікном 1–24 години; inference не навчається.
Події атомарно закривають pending і додають cancel; ACK не змінюється
при позитивному годинному оновленні. Старий APK без surge_v1 не отримує
новий alert. Advisory locks серіалізують worker і операції за КПП.

Повторне ввімкнення вже вимкненої pending-підписки отримує новий alert_id.
Вузька SECURITY DEFINER функція очищає лише задані id+device, статус expired,
наявний cancel та відсутню/вимкнену підписку. ACK і чинні повідомлення
залишаються. Runtime не має прямого DELETE. Startup/restore перевіряє
owner, search_path та grants; restore повертає власника avelren_migrator.
Глобальний kill switch закриває події й cancel при запуску worker із
SURGE_ENABLED=false. Сам run_cycle disabled не відкриває пул.

Конфігурація додає тільки surge_enabled=false; контракт collector незмінний.
Міграція 016 ще не застосована на production; уточнення її прав/function
перевіряються тільки на disposable синтетичній БД.

Оновлення перевірок: 330 unit і44 database пройшли, restore повторно пройшов після додавання cleanup-функції. CI/production/Android не прийняті.


## API та сумісність

Новий router керує вибором кількох КПП, двома типами, приватним ACK,
списком власних повідомлень і публічним статусом експерименту. Авторизація
та rate limit чинні; чужий alert не підтверджується. Непідтриманий прогноз
відхиляється, фактичне зростання доступне для наявних КПП. Прогноз має
майбутнє вікно та experimental=true, без score або відсотка ймовірності.
Точні фрази Чопа спільні для DTO і майбутньої доставки.

`schemas.py`, `subscriptions_api.py` додають capability до registration
і authenticated token refresh. Якщо 016 відсутня, звичайна реєстрація
працює; нові маршрути повертають 503. `api.py` підключає router,
`cancels.py` додає два окремі списки reconciliation тільки для доступної
функції. Вісім нових API-сценаріїв і попередні контракти пройшли:
74 API-тести на синтетичній БД, включно з історичними міграціями та
performance gate. AST-перевірка rate limit бачить усі шість нових маршрутів.

Походження попереднього wait-time контракту збережено в
[описі PR #72](WAIT-ESTIMATE-IMPLEMENTATION.md); поточні revisions
у manifests посилаються на цей спільний журнал подальших змін.


## Доставка FCM

Спроба з UUID записується та commit виконується до HTTP. Повтор після
втраченої відповіді використовує той самий UUID у п'ятихвилинному інтервалі.
Наступне заплановане нагадування отримує новий ordinal, навіть коли
попередня відповідь лишилась невідомою; стару не позначаємо accepted.
Після підтвердженого прийняття Google наступне нагадування через 300 секунд.
ACK/expiry зупиняють резервування. Пізній normal callback повторно ставить
cancel у чергу, не повертаючи ACK у pending. Підтвердження Google не є
підтвердженням показу на телефоні.

`notifier.py` commit-ить legacy-зміни перед окремою surge-фазою, щоб не
очікувати власного lock на devices через другу pool connection. Нова фаза
має межу 30 секунд, потім працюють cancels; помилка surge не припиняє їх.
Мертвий токен очищається тільки якщо він досі збігається з токеном спроби.
Payload має окремий surge_alert_id, attempt_id, ordinal, created_at, expiry
і experimental, без legacy alert_id. TTL до 360 секунд і не довший за expiry.
Android має перевіряти ordinal, ACK/cancel та expiry перед текстом/голосом.

[Офіційний контракт FCM collapse](https://firebase.google.com/docs/cloud-messaging/customize-messages/collapsible-message-types)
не гарантує порядок і зберігає лише чотири collapse keys для одного токена.
Тому не обіцяємо доставку всіх offline push; повтори, TTL та foreground
reconciliation доповнюють одне одного.
[Строк актуальності FCM](https://firebase.google.com/docs/cloud-messaging/customize-messages/setting-message-lifespan).

Новий cancel має `cancel_surge_alert_id`, а не legacy `cancel_alert_id`: старий Android ігнорує невідомий тип і не скасовує повідомлення здоров’я сервера з тим самим числовим ID. Чинний threshold/eta payload не змінено.

## Android: контракт і локальні підтвердження

Окремі DTO та API для моніторингу; registration і token refresh передають `surge_v1`. Локальний preferences ledger має синхронний commit і спільний process lock: підтвердження, cancel tombstone, UUID/ordinal переживають створення нового store. Збій запису або пошкоджений ledger не дозволяє показ. Відома активна фактична подія блокує пізній прогноз того самого КПП.

«Зрозуміло» спершу записує local ACK, відразу прибирає notification і зберігає pending до WorkManager з network constraint та backoff. Успіх або own-alert 404 після recovery завершує pending; 503/offline не завершує. Startup/foreground відновлює pending. Legacy threshold/eta paths збережено; active-alerts має окремі нові списки. Stop voice буде підключено разом із голосовим сервісом. Це JVM-перевірки persistence boundary, а не доказ перевірки на реальному телефоні.

## Інтерфейс моніторингу

Третя плитка відкриває моніторинг кількох КПП з окремими forecast/fact налаштуваннями, глобальною local voice preference та чинним count forecast як окремою дією. Стиль звірено з AvelRen: Overpass, жовтий F5C400, темні картки 0A0A0A, тонка біла рамка38FFFFFF, кути16dp, поля20dp. Footer закріплено Scaffold.

02.10.2026 офлайн preview (без INTERNET) перевірено на окремому емуляторі API36: вибрані два КПП, loading, error, довгий scroll, font_scale1.5, відсутність sample button, footer видимий. Останню версію карток повторно оглянуто на screenshot style-final. Це синтетичні стани UI, не доказ доставки push або перевірки телефона.

## Голос і окремі сповіщення

Нові kind використовують власний канал із notification usage, full-ID tag та окрему дію «Зрозуміло». Колізія IDs9001 і10009001 не перекриває різні notification/ACK PendingIntent; cancel і reconciliation зберігають tag. Факт атомарно погашає попередній локальний прогноз того самого КПП, включно з його озвученням.

Короткий mediaPlayback FGS показує foreground notification до TTS, перевіряє фактичний `RemoteMessage.priority`, voice preference, permission/channel, DND/ringer, expiry й durable ACK. Локальний встановлений uk voice, bounded queue10, init10s/utterance30s/service60s, audio focus, stop/cancel та release ресурсів. START_NOT_STICKY: reboot не відтворює стару voice queue. Жіночий голос залежить від installed TTS і потребує перевірки на телефоні.

02.10.2026 compile/JVM/lint/assemble пройшли. Офлайн емулятор API36: Google TTS успішно bound, uk voice недоступний — service завершився без crash, текст лишився, причина показана в UI. Фактичний full-ID collision/cancel перевірено. Priority/queue/ACK/expiry перевірено JVM; background handler probe не підтвердив OS rejection і не вважається доказом цього сценарію. Фонову доставку реального FCM, screen-lock, audio-focus refusal, жіночий голос і repeat5min перевіряємо перед релізом на телефоні; зараз не підтверджено.

Джерела Android API: [обмеження FGS](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start), [тип mediaPlayback](https://developer.android.com/develop/background-work/services/fgs/service-types), [TextToSpeech](https://developer.android.com/reference/android/speech/tts/TextToSpeech). Preview лишається debug-only/offline/no Firebase; POST_NOTIFICATIONS збережено для локального probe. Сервіс/type повторено в test overlay, бо lint аналізує overlay окремо від merged manifest.

## Runtime та інтеграційне приймання

Окремий profile surge, власний DSN, false за замовчуванням для API/notifier/worker.
Журнал після зовнішнього commit: cycle timestamp, processed, failed, model_version.
Контракт Compose перевіряється справжнім parser без запуску контейнерів.
Синтетична історія з реальною frozen моделлю, фактом, notifier payload, API ACK,
cancel і новими worker-з’єднаннями перевіряється разом на внутрішній мережі.
Restore fixture охоплює ACK/UUID та всі шість нових таблиць. Ці перевірки
не підтверджують точність, реальну FCM-доставку або телефонний жіночий голос.

## Незалежний review та виправлення

02.10 whole-branch review d04d7ce виявив п’ять Important: неіснуюча sort_index
у enabled списку КПП, відсутній екранний ACK, початковий голос, видима позначка
експерименту й повтор bigint alert ID після старого restore. Виправлення:
сортування country_name/title/id, local-first ACK з екрана, стійка ознака
явного вибору голосу, видимий текст «Функція в розробці» без зміни озвучення.

У ще не застосованій016 alert ID генерується як позитивний random63-bit ключ
із cryptographic UUID, а не з rewindable sequence. Bigint контракт збережено;
UUID спроб доставки лишається окремим. Restore зберігає старі ідентичності,
нові SQL INSERT не повторюють sequence. PK відхиляє live collision, worker
повторює цикл після rollback. Колізія з утраченим історичним ключем має
залишкову ймовірність63-bit random key; це не математична гарантія128-bit UUID.
Ручне призначення runtime alert ID заборонено. Перевірка повертає sequence
до старого значення та підтверджує інший новий ID. Applied001–015 не змінені.

Точний production Timescale2.17.2 digest на disposable стенді не підтримує015
через compression. Тому розгортання потребує окремого ручного DB upgrade
і погодженого способу відкату; зелений candidate2.30 test цього не замінює.

Емуляторний екранний ACK фактично зберіг99017/99006 і pending offline.
WorkManager виявив preview-only відсутність ACCESS_NETWORK_STATE; preview
залишає цей дозвіл спостереження, але без INTERNET/Firebase. Після виправлення
ACK перевірено без FATAL/crash. Немає встановлення на телефон власника.
Репетиція upgrade2.17.2→2.30.1 із compressed даними,015/016, відновленням,
API/collector/watchdog пройшла локально. Стан сервера від цього не змінився.
