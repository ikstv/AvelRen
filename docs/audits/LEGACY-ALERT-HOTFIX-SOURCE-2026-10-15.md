# Legacy alert hotfix: source readiness — 15.10.2026

## Мета

Доповнити незавершений ETA backport для чинного legacy collector контрактом
повтору threshold/ETA alert до ручного видалення. Forecast/surge, Android,
схема БД, writer, spool, залежності та 60-секундний цикл не змінюються.

## Зміна

Artifact `ops/eta-legacy-hotfix/` тепер накладає на exact legacy base два файли:

- `eta.py` — уже перевірений forward-crossing backport;
- `collector.py` — файл із AvelRen
  `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27`, у якому прибрано лише
  `alerts.expire_stale(conn)` та `eta.expire_passed(conn)`.

`alerts.evaluate` і `eta.evaluate` лишаються в кожному непорожньому циклі;
первинний запис observation/run, окрема derived-транзакція, error recording,
порядок циклу та cadence не змінені. Pending alert завершується лише через
ручне DELETE відповідної threshold-підписки або ETA-цілі.

## TDD evidence

До реалізації новий тест мав два очікувані результати RED: відсутній
`collector.py` і Dockerfile копіював тільки `eta.py`. Після реалізації:

- legacy ETA fixture: 14 tests PASS;
- legacy collector behavior/build allowlist: 2 tests PASS;
- diff із базовим collector.py: рівно два вилучені expire-виклики.

Це source readiness, а не production acceptance. Новий immutable image digest,
перевірка 34 module hashes/runtime config, restricted-role PostgreSQL, restore,
rollback, CI та телефонні threshold/ETA push ще мають бути прийняті окремо.
Production не змінювався.
