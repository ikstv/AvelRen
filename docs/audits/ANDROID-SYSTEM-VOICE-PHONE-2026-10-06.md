# Системний голос: продовження на ноутбуці 06.10.2026

[Погоджений план](../FCM-TEST-PLAN-2026-10-06.md), максимум 8 спроб.
Сесія продовжує [приймання 04.10](ANDROID-SYSTEM-VOICE-PHONE-2026-10-04.md).

## Кандидат і умови

Чистий main `1f30f6dc535e3e54c84cba1134915c5607b8f7f1`;
`ua.avelren.app.pushqa`, `1.0.3-push-qa`/code6. SHA-256 APK:
`3df34578d008c88c0f4f74239058efdd25adb04c8aa1c41c4c01a507e6ab6f90`.
Третє USB-встановлення успішне після явного прохання власника повторити;
SHA установленого base.apk збігається. Xiaomi 22071212AG, Android 15.
210 JVM-тестів, preview та pushQa lint, assemble й manifest isolation пройшли.

Перед send перевіряли media0/notif15, NORMAL/zen OFF, дозвіл сповіщень,
фактичні HIGH4 канали та sound URI, voice-ready й SHA відповідного WAV.
Голос uk-UA-language, pitch1/rate0.88. Перший send — після 32 с у фоні.
Токен лише QA-пакета, SSH stdin, high-priority data/TTL120.

## Сценарії

| Слот | Сценарій | Доказ і результат |
| --- | --- | --- |
| 1 | Новий прогноз Чопа | PASS: реальний FCM priority1/foregroundfalse, один старт; SystemUI onCompletion; власник «Так, почув повністю» |
| 2 | Фактичний початок Чопа | PASS: правильний WAV факту, один старт/completion; власник почув повністю. Forecast ledger cancelled=true |
| 3 | Нова attempt того самого факту після «Зрозуміло» | PASS: durable acknowledged=true; ART trace має 1 onMessageReceived і 1 claimAttempt, 0 delivery/service entries; повідомлення і служба відсутні |
| 4 | Нова незалежна подія Чопа після ACK | PASS: окремий alert ID, один старт/completion; власник «Почув, екран ще відкритий» |
| 5 | Прогноз Краківця із заблокованим екраном | UNKNOWN: locked preflight пройшов, але SSH sender не підтвердив FCM request. Події CP6 у локальному ledger немає; власник повідомив про обрив інтернету. Не називати дефектом голосу чи PASS |
| 6 | Краківець, locked | PASS: HTTP200, правильний CP6 WAV; SystemUI старт 08:34:09.308, completion 08:34:13.447 (Київ); власник почув повністю |
| 7 | Ягодин, locked | PASS: HTTP200, правильний CP1 WAV; старт 08:34:48.301, completion 08:34:52.305; власник почув повністю |
| 8 | Ягодин — порожні вантажівки, locked | PASS: HTTP200, правильний CP29 WAV; старт 08:35:30.388, completion 08:35:35.769; власник почув повністю |

Метод trace після stop дописується асинхронно: перше копіювання дало
порожній файл; повторне копіювання завершеного файла без нового push
має 1 051 229 байтів і наведені входи. Порожній файл не є доказом відсутності
входу FCM. Бінарні receipts лишаються поза Git.

## Мережеве переривання та продовження

Після UNKNOWN виконано cleanup: Firebase QA GET DELETED, production ACTIVE;
QA-пакет видалено й відсутній у package list. Використано 5/8 слотів,
із них 4 підтверджені FCM HTTP200 та одна невизначена SSH-спроба.
П'ятий слот не повертаємо до бюджету.

Після нового «go» власника та повідомлення про обрив інтернету відновлено
ту саму QA-ідентичність і повторно встановлено той самий APK. SHA нового
base.apk знову збігається. Продовження лише в решті 3 слотів; невиконані
сценарії потребують наступного окремого погодженого повтору.

Докази: `dist/phone-system-voice-qa-20261006/` на ноутбуці,
PUSH-SEND-LEDGER.json, PREFLIGHT-*.json, installed-base*.apk,
ack-retry-complete.trace. Офіційний Play APK — 0.1.2/code5.
Production registration/ACK, БД й серверні служби не змінювалися.
Після слота 8 cleanup підтверджено: Firebase QA ACTIVE → DELETED із GET
readback, production identity guard ACTIVE; ADB uninstall Success і package
list містить лише офіційний `ua.avelren.app`. Приватний QA config раніше
прибрано. Ліміт вичерпано: 8 спроб, 7 FCM HTTP200 і 1 UNKNOWN, без прихованих
повторів. Рава-Руська locked ще потребує окремого GO на додатковий тест.
Overflow/deadline, TTS/lifecycle та повний реліз ще не прийняті.
