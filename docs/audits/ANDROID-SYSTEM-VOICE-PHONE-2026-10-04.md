# Системний голос: телефон, 04.10.2026

## Код, CI та встановлений кандидат

[PR #88](https://github.com/ikstv/AvelRen-ORIGINAL/pull/88) злитий у
`2a7a849943acd47942bfeaddbe9f2a5276d894eb`. Усі чотири перевірки точного
head `965617c` і merge-коміту успішні. Локально 210 JVM-тестів, preview
assemble/lint та справжня pushQa assemble/lint/manifest isolation успішні.
Чотири важливі findings незалежного review виправлені через RED→GREEN;
connectedTest probe лишається preparation-only, це відкладене Minor.

Збірка з чистої main: `ua.avelren.app.pushqa`, `1.0.3-push-qa`, versionCode6.
APK і установлене readback мають однаковий SHA-256:
`d6ef883972679de5d4844f81a8732f5e3731c488b96f0e443f03838c5f1838c5`.
Телефон Xiaomi22071212AG, Android15/API35. Перші два встановлення скасовані
Xiaomi; третє підтверджене власником та завершилося успішно.

## Локальні продуктові сценарії

Це той самий assets/provider/delivery/service, що використовує робочий
застосунок. Тригер локальний, а не FCM; production registration/підписок/ACK немає.
Android API підтвердив media0/15, notification15/15; гучність агент не змінював.

| Сценарій | Результат |
| --- | --- |
| Підготовка ресурсів | 10 WAV та 10 metadata, token-ready і voice-ready окремо підтверджені |
| Повторне відкриття | SHA усіх 10 WAV незмінні |
| Відсутній WAV | Видимий fallback, voice_not_ready, голос не стартує; файл повернуто |
| ACK до старту | Durable acknowledged, повторна claim відхилена, повідомлення/голос відсутні |
| ACK під час фрази | Власник: «Так, почалась і зупинилась»; повідомлення прибране, завершення фрази не було |
| П'ять КПП | 5 starts, 5 SystemUI onCompletion, служба завершена; власник: «Так, усі п’ять повністю» |
| Старий/новий канал NONE | notification_blocked, повідомлення й голос відсутні, fallback не обходить блок |

П'ять фраз: Чоп, Краківець, Ягодин, Ягодин для порожніх вантажівок,
Рава-Руська. Первинний голос uk-UA-language, pitch1/rate0.88 збережений.
Overflow/deadline, відсутній TTS та lifecycle abort ще не прийняті на телефоні;
відповідні локальні автоматичні тести не замінюють телефонного приймання.

## Справжній FCM: 1/8, зупинка

Власник явно дозволив конкретний FCM-TEST-PLAN. Наш попередній Firebase
QA-клієнт відновлено зі стану DELETED; identity та ACTIVE перевірено GET.
Після першого скасованого встановлення виконано cleanup; за окремим проханням
власника повторити встановлення повернено ту саму підтверджену QA-ідентичність.

Надіслано **один** target-only high-priority data push, TTL120. Сервер прийняв
його, Android отримав `priority=1 foreground=false` після 32с у фоні. Голос
не почався: `notification_silent`, 0 starts/0 completions. Це **FAIL**, а не
приймання фонової доставки голосу. Дублі/FCM ACK/locked/кілька КПП не перевіряли.

Причина підтверджена фактичними налаштуваннями: після QA вимкнення/повторного
увімкнення Xiaomi виставив обом каналам `mImportance=2`, `mUserLockedFields=4`,
замість початкового HIGH4. Візуальне «увімкнено» не відновило звуковий режим.
Код правильно поважив тихі канали. Перший helper widget tap також не змінив
перемикач; натискання назви рядка дозволило перевірити NONE. Обидва недоліки
QA процедури зафіксовані; перед повторним FCM потрібен фактичний preflight
importance/sound/voice resources, а не лише volume і ready marker.

За stop-on-fail більше push не надсилали. Cleanup підтверджено:
QA Firebase DELETED, активний лише `ua.avelren.app`; QA пакет видалено,
приватний config прибраний. Робочий APK лишився `0.1.2`/code5; БД, серверні
підписки, служби, ОС/Docker не змінені.

Безсекретні receipts: `dist/phone-system-voice-qa/`, зокрема
PUSH-QA-INSTALL-RECEIPT.json, cancel.json, sequence.json, channel-0/1.json,
PUSH-SEND-LEDGER.json, FAILURE-CHANNEL-AUDIO.json та CLEANUP.json.
Підготовлено окремий повторний план у
`dist/phone-system-voice-qa-retry-20261004/FCM-TEST-PLAN.md`; ще не дозволений.

## Межа релізної готовності

Продуктовий локальний голос з media0 та скасування/п'ять КПП прийняті.
Справжній FCM, locked і повна телефонна матриця **ще не прийняті**.
GitHub Release1.0.3 та Play не опубліковані; опис релізу редагує власник.
