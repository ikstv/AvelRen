# Перенесення ownership та ACL PostgreSQL — кандидат 001–016

Цей компонент переносить контракт прав із двох старих репозиторіїв у
AvelRen-ORIGINAL. Виконавець змін підтримує тільки одноразові тестові БД.
Production adoption, створення ролей, DSN cutover та retirement не виконуються.
Залежність: [PR #106](https://github.com/ikstv/AvelRen-ORIGINAL/pull/106).
Специфікація: [design](../docs/POSTGRES-ADOPTION-016-DESIGN.md).

Історичні джерела: [AvelRen 4a8e010](https://github.com/ikstv/AvelRen/tree/4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27)
та [AvelRen-ops 5be9da8](https://github.com/ikstv/AvelRen-ops/tree/5be9da8b433813a664b4d4e21a0a92bae91c56a0).
Старі stamp 010 і blanket ownership-команди не застосовуються.

## Інвентаризація та план

Модуль: `python -m avelren.postgres_adoption` із backend PYTHONPATH.
Connection береться тільки з `AVELREN_ADOPTION_DSN`; target — з
`AVELREN_ADOPTION_TARGET`. Значення з credentials не передавати в argv чи лог.
`inventory --output-dir PATH` виконує read-only repeatable-read catalog snapshot;
`plan --evidence-dir PATH` будує forward/inverse без доступу до БД;
`inspect --evidence-dir PATH` звіряє поточний fingerprint без змін.

Evidence зберігається на Linux у власному каталозі 0700, файли 0600;
symlinks, hardlinks, перезапис і підміна checksum відхиляються. Windows
publication не підтримується: chmod не доводить приватність Windows ACL.
Evidence містить metadata ролей, ownership/ACL та журнал, але не passwords
чи application rows. Зберігати його приватно поза Git.

План приймає PostgreSQL 16, TimescaleDB 2.30.1 та точний hash-журнал 001–016.
Невідомі об'єкти, schema/function drift, role escalation/membership,
делеговані grants з не-owner grantor та непідтримувана топологія відхиляються.
Права descendants мають відповідати кореню: зміни виконуються через public
батьківські об'єкти й штатні Timescale hooks. Новий compressed-relation layout
перевіряється зі стисненими chunks/CAGG; старий compressed-hypertable layout
відхиляється як `unsupported_legacy_compression` до будь-якого запису.

## Disposable приймання

```bash
bash scripts/test_database.sh adoption
bash ops/postgres-adoption-restore-test.sh
```

Runner сам створює ізольований Docker project без production DSN. Restore
runner використовує штатну синтетичну restore-репетицію і одноразовий clone
відновленої БД; forward/gate/inverse звіряють fingerprint, дані та весь журнал.
`apply-test --evidence-dir PATH` допускає лише `AVELREN_DATABASE_TEST=1` і
dbname `avelren_case_<32 lowercase hex>_test`, однаковий у DSN, plan і target.
Ті самі guards застосовуються до inverse. Інші application sessions блокують
операцію; виконавець не завершує їх. SQL із evidence повторно генерується
з inventory, а не довіряється вхідним statements.

До commit помилка відкочує транзакцію та звіряє before fingerprint. Після
commit виконується read-only gate; inverse дозволений лише за точного expected
fingerprint. Чужа зміна зберігається і повертає `rollback_failed`. Втрата доказу
commit повертає `commit_unknown`: автоматичний повтор заборонений. Intent і
receipts публікуються без перезапису. Повтор після прийнятого receipt потребує
узгоджених plan hash, before/after fingerprints та фактичного стану.

Exit codes: 0 — adopted/already_target/inspected; 1 — refused/rolled_back;
2 — unavailable або invalid arguments; 3 — rollback_failed; 4 — commit_unknown.
`inspect` повертає advisory category для drift; це не дозвіл повторювати apply.

## Окремі наступні production етапи

Потрібні свіжий read-only audit і погоджений production executor. Далі окремо:
provisioning ролей; ownership adoption із приватним evidence та перевіреним
rollback; runtime DSN cutover; acceptance кожної служби; soak і retirement
legacy ролей. Кожен етап має власний явний GO. Поточний кандидат не містить
production apply-команди і не змінює міграції, bootstrap чи service runtime.
