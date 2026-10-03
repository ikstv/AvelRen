# FCM і голос на телефоні — 04.10.2026

## Код і встановлення

PR [#85](https://github.com/ikstv/AvelRen-ORIGINAL/pull/85) злитий у
`bc5abae47f1330fca421861b5c3ea0d1db9f0a33`. Усі п'ять CI PR і самого
main успішні; дерево main збігається з перевіреним merge-ref:
`8d25679fbf9c1bb571e1f8d0d522796d9c6a6f94`.

Власник окремо дозволив створення Firebase QA-клієнта, встановлення
та максимум 8 адресних push за [планом](../ANDROID-PUSH-QA.md).
Клієнт `ua.avelren.app.pushqa` створено й перевірено як ACTIVE.
Серверні credentials не вивантажувалися; токен QA передавався через SSH stdin.

На Xiaomi 22071212AG, Android 15, HyperOS `OS2.0.217.0.VLQEUXM`
встановлено `1.0.3-push-qa`, versionCode `6`, targetSdk `36`.
SHA-256 зібраного та повторно прочитаного встановленого APK збігається:
`f2f6cc71f5c450ca9d52d676ada0ae193ef5834ace5e484ab7486c136401ada5`.
Дозвіл сповіщень надано; QA Firebase token отримано без показу в UI/логах.

## Фактичний сценарій, 01:06–01:07 за Києвом

Після Home витримано щонайменше 32 секунди; QA activity не resumed,
екран Awake, keyguard=false. Надіслано **один** справжній high-priority
data push через встановлений `avelren.fcm.send`, TTL 120 секунд,
лише QA токену власника. Текст: «Можливий початок масової реєстрації на Чопі».
Заголовок — «Тест AvelRen»; синтетичний alert ID `103301`.

| Перевірка | Результат |
| --- | --- |
| FCM прийняв повідомлення | PASS |
| Застосунок отримав high priority у фоні | PASS: `priority=1 foreground=false` |
| Сповіщення на телефоні | PASS: ID `40103301`, importance=4 |
| Запуск foreground service | PASS: Android дозволив за `PUSH_MESSAGING` |
| Підключення локального TTS | PASS |
| Audio focus | **FAIL**: `Focus request DENIED`, procState=4 |
| Початок/завершення мовлення | **FAIL**: 0/0 callback, `voiceProblem=audio_busy` |
| Чутність від власника | Не підтверджена; технічного озвучення не було |

Команда встановити media=0 не змінила фактичну гучність: повторне читання
показало **5/15**, сповіщення також 5/15. Незалежність від media=0 у цій
пробі **не перевірено**. Після завершення media=5 повторно підтверджено.

## Причина відмови й межі висновку

Системний AppOps для QA: `TAKE_AUDIO_FOCUS: foreground`, з rejectTime
цієї події. Android дозволив FGS, але не надав audio focus; поточний код
коректно зупинив голос після відмови. Це відтворює попередню локальну
фонову проблему вже зі справжньою FCM доставкою.

У коді Android 15 [HardeningEnforcer](https://github.com/aosp-mirror/platform_frameworks_base/blob/android15-release/services/core/java/com/android/server/audio/HardeningEnforcer.java)
audio focus перевіряється через AppOps. [AppOpsUidStateTrackerImpl](https://github.com/aosp-mirror/platform_frameworks_base/blob/android15-release/services/core/java/com/android/server/appop/AppOpsUidStateTrackerImpl.java)
пов'язує його з foreground audio capability, а [OomAdjuster](https://github.com/aosp-mirror/platform_frameworks_base/blob/android15-release/services/core/java/com/android/server/am/OomAdjuster.java)
у цьому коді надає capability залежно від while-in-use дозволу FGS.
Це пояснення, узгоджене з логами; точний код OEM-прошивки не звірявся.
Не можна робити висновок, що відмова однакова на всіх Android-пристроях.

AppOps не перевизначали, targetSdk не знижували, відмову audio focus
не ігнорували. Телефонний тест не прийнятий як успішний голосовий сценарій.

## Зупинка та відкат

За погодженим правилом тест зупинено після першої помилки. Дубль,
фактичний початок, locked-сценарій, локальний ACK і наступні push не виконані.
Всього відправлено **1 із максимум 8**; серверних записів БД, змін підписок,
робочої реєстрації та рестартів не було.

- QA пакет force-stop: його сповіщення прибрано, відсутність перевірено.
- Видалено лише `ua.avelren.app.pushqa`; `ua.avelren.app` залишився.
- Firebase QA-клієнт прибрано через `remove` з `immediate=false` і свіжим etag.
  Повторний GET підтвердив `DELETED`, список активних клієнтів знову містить
  лише попередній `ua.avelren.app`. Це відновлюване видалення, не миттєве.
- Тимчасовий локальний `push-qa.properties` прибрано.

Локальні докази: `dist/phone-qa-1.0.3-20261003/` —
`PUSH-QA-INSTALL-RECEIPT.json`, `PUSH-SEND-LEDGER.json`,
`background_forecast.log`, `PUSH-SYSTEM-DIAGNOSTICS.log`,
`PUSH-AUDIO-STATE.json`, `PUSH-QA-CLEANUP.json`. Каталог не публікується;
токенів чи credentials в наведених звітах немає.

## Наступний крок

Потрібно виправити спосіб автоматичного озвучення на Android 15 і повторити
фонову та locked перевірки. Один варіант для окремої перевірки — підготовлені
голосові фрази як системний звук сповіщення, зі збереженням початкового голосу
та каналу гучності сповіщень. Його ще не реалізовано й не перевірено.
Реліз 1.0.3 у GitHub/Play не публікувати як такий, що має прийнятий голос.
