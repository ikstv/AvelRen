# Окрема перевірка FCM і голосу, 03.10.2026

## Мета й межі

Власник погодив окремий тестовий застосунок, зберігаючи встановлену Play-версію.
Потрібна справжня доставка FCM після згортання та блокування телефона:
локальний запуск служби не доводить, що Android дозволить голос після push.

`-PavelrenPushQa=true` збирає лише debug-пакет `ua.avelren.app.pushqa`.
Він використовує робочі `AvelRenMessagingService`, `Notifications`,
`SurgeVoiceService` і локальну частину `AckReceiver`. Замість `AvelRenApp`
запускається стандартна Application, API адреса — `https://127.0.0.1:9/api`.
Тому немає реєстрації в API, робочих підписок чи серверного ACK.
Натискання сповіщення відкриває QA-екран через alias `MainActivity`.

Токен FCM зберігається лише у приватному `files/push-qa-token`; UI й логи
його не показують. Перед тестом оператор перевіряє дозвіл сповіщень,
мережу, гучність сповіщень та стан екрана. Нові debug-логи підтверджують
пріоритет FCM і callback початку/завершення TTS без тексту повідомлення.
Тембр, темп і правила повторів не змінюються.

## Збірка та перевірки

Окремий Firebase Android-клієнт має packageName `ua.avelren.app.pushqa`.
Його конфігурація зберігається в gitignored `apps/android/push-qa.properties`:
`packageName`, `googleAppId`, `senderId`, `apiKey`, `projectId`.
Конфігурацію робочого клієнта використовувати заборонено.

CI використовує `app/src/pushQa/fixture.properties` лише для компіляції:

```sh
cd apps/android
bash gradlew -PavelrenPushQa=true -PavelrenPushQaConfig=app/src/pushQa/fixture.properties :app:assembleDebug :app:lintDebug
cd ../..
python3 scripts/verify_push_qa.py
```

APK з fixture **не встановлювати й не запускати**. CI перевіряє реальний
merged manifest і BuildConfig, окремий пакет, Application, launcher/alias,
FCM/голос/ACK, Firebase provider та відсутність робочої адреси API.
Release у будь-якому тестовому режимі та поєднання режимів заборонені.
Для телефона потрібен чистий main після CI, справжній QA config,
версія/коміт/SHA-256 і звірка встановленого APK.

## Конкретний план зовнішнього тесту — потрібен окремий GO

1. Повторно прочитати Firebase Android clients через наявні серверні
   credentials. Preflight 03.10: HTTP 200, лише `ua.avelren.app`.
   Створити рівно один клієнт `ua.avelren.app.pushqa` з назвою
   `AvelRen phone QA 2026-10-03`; зберегти його resource name для відкату.
   Якщо такий пакет уже існує, зупинитися й звірити походження.
   Не змінювати IAM, ключі, обмеження API чи конфігурацію робочого клієнта.
2. Дочекатися завершення операції, завантажити лише QA `getConfig`.
   Перевірити packageName, appId і project перед перетворенням у properties.
   Серверні credentials залишаються у контейнері; значення config не логуються.
3. Зібрати й встановити окремий QA APK на телефон власника. Отримати
   токен через `adb run-as` лише цього пакета та передати через SSH stdin.
   Не друкувати токен і не зберігати його в Git/receipt.
4. Через встановлений модуль `avelren.fcm.send` надіслати максимум
   **8 high-priority data повідомлень** лише цьому токену: по прогнозу
   й фактичному початку у фоні та на заблокованому екрані, до двох
   контрольних повторів і до двох cancel. TTL не більш ніж 120 секунд.
   У повідомленні явно зазначити «Тест», використати окремі QA alert IDs.
   Фрази: «Можливий початок масової реєстрації на Чопі» та
   «Почалось зростання черги на Чопі».
   Фіксований порядок: фоновий прогноз → його дубль з тим самим attempt →
   фоновий факт → cancel цього факту → заблокований прогноз → його дубль →
   заблокований факт → cancel цього факту. Перед другим прогнозом перевірити
   застосування першого cancel у приватному локальному ledger або дочекатися
   `expires_at` попереднього факту. ACK не скасовує `activeFact`, тому самі
   нові alert IDs не ізолюють другу пробу. Дубль надсилати після завершення
   першого озвучення, усі payload — зі свіжими датами та узгодженим TTL.
5. Перед фоновою пробою дочекатися завершення activity grace period
   (щонайменше 30 секунд після Home); перед заблокованою — згортання
   й блокування, також щонайменше 30 секунд. Перевірити keyguard,
   resumed activity, FCM priority, notification, audio focus, TTS callbacks.
   Власник окремо підтверджує чутність. Дубль attempt не має озвучуватися
   вдруге; локальний ACK має прибирати сповіщення і голос.
6. Записати фактичні результати, прибрати власні QA сповіщення.
   При помилці зупинити надсилання, зберегти безпечну діагностику.

Тести не створюють рядків у БД, підписок чи admin-прив'язок, не рестартують
служби. Не підтверджують серверний ACK/retry scheduler, Play release
або повне наскрізне приймання застосунку — ці етапи залишаються окремими.

## Відкат і прибирання

Зупинити QA пакет, прибрати його сповіщення; за необхідності видалити
лише `ua.avelren.app.pushqa`. Для створеного цією перевіркою Firebase
клієнта звірити resource name, packageName, displayName і свіжий etag,
виконати `androidApps.remove` з `immediate=false`; повторно перевірити
стан. Якщо результат create невідомий — спочатку звірка списку, без
повторного сліпого create. Робочий клієнт `ua.avelren.app` не змінювати.
При відмові API не розширювати права автоматично.

Офіційні контракти Firebase:
[create](https://firebase.google.com/docs/reference/firebase-management/rest/v1beta1/projects.androidApps/create),
[getConfig](https://firebase.google.com/docs/reference/firebase-management/rest/v1beta1/projects.androidApps/getConfig),
[remove](https://firebase.google.com/docs/reference/firebase-management/rest/v1beta1/projects.androidApps/remove).
