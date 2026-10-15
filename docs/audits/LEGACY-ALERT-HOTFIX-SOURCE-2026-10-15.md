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
- legacy collector behavior/build/provenance allowlist: 3 tests PASS;
- diff із базовим collector.py: рівно два вилучені expire-виклики.

Hosted CI commit `4503477f334c72ab05409bf241779592d2fe0bf1` завершився SUCCESS.
На production host без зупинки чинного collector зібрано candidate від exact
base `sha256:e7b02f58581d…` з вимкненою мережею. Candidate image:
`sha256:40219d6c8ceee5a862382dbb62fe3df06181a20488635d47c5a965512eda9a72`.
Перевірено незмінний base-layer prefix, image config (крім source identifier),
той самий набір 68 установлених файлів та рівно два змінені модулі:
`eta.py`, `collector.py`. Exact source/image pair додано без послаблення
restore allowlist; cross-pairs і near-miss лишаються заборонені.

Production runtime ще не перемикався. Restricted-role PostgreSQL, restore,
rollback і телефонні threshold/ETA push мають бути прийняті окремо.
