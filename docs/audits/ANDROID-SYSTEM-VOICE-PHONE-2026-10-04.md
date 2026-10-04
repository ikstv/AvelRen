# Кандидат системного голосу — 04.10.2026

## Стан приймання

Продуктову збірку ще не встановлено й не прослухано. Справжній FCM
нового механізму, media=0 та матриця ACK/кількох КПП **не прийняті**.
Попередній throwaway prototype прийнято окремо:
[phone probe](ANDROID-NOTIFICATION-VOICE-PROBE-2026-10-04.md).

Локальні JVM/preview compile/lint та fixture pushQa compile/lint/manifest
пройшли. ConnectedTest compile/lint пройшли; його Activity зараз перевіряє
лише підготовку ресурсів, доставка там не запускається.
Релізний manifest має приватний voice provider без QA receiver.

Незалежний review знайшов чотири важливі дефекти, їх виправлено через
поведінкові RED→GREEN тести. Конкретний план нового FCM QA з max8,
TTL120, stop-on-fail і cleanup збережено локально:
`dist/phone-system-voice-qa/FCM-TEST-PLAN.md`.
За AGENTS.md зовнішні операції очікують нового дозволу власника.

## Що записати після дозволу й тесту

Точний main commit, версія, versionCode, SHA-256 APK і readback,
дата/умови кожного сценарію, виміряні гучності, результат запуску служби,
відповідь власника, bounded push ledger і фактичний cleanup.
Жодного поля «перевірено на телефоні» до цього не заповнювати.
