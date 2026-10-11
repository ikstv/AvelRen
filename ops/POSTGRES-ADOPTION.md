# Перенесення ownership та ACL PostgreSQL — кандидат 001–016

Цей компонент переносить контракт прав із двох старих репозиторіїв у
AvelRen-ORIGINAL. DB executor production adoption реалізований як source
кандидат; публічний production apply/inverse CLI закритий до приймання
maintenance adapter. Production adoption, створення ролей, DSN cutover
та retirement не виконуються.
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
вимкнені application/FK triggers,
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
Очікування session advisory lock завершується до створення repeatable-read
snapshot; таблиці блокуються перед першою snapshot-producing query.

До commit помилка відкочує транзакцію та звіряє before fingerprint. Після
commit виконується read-only gate; inverse дозволений лише за точного expected
fingerprint і валідних apply-intent/committed records, прив'язаних до version,
target та plan digest. Втрата відповіді на COMMIT повертає `commit_unknown`
без повтору COMMIT, rollback або автоматичного inverse.
За іншого fingerprint чужа зміна зберігається і повертається
`rollback_failed`. Втрата доказу
commit повертає `commit_unknown`: автоматичний повтор заборонений. Intent і
receipts публікуються без перезапису. Повтор після прийнятого receipt потребує
узгоджених plan hash, before/after fingerprints та фактичного стану.

Exit codes: 0 — adopted/already_target/inspected; 1 — refused/rolled_back;
2 — unavailable або invalid arguments; 3 — rollback_failed; 4 — commit_unknown.
`inspect` повертає advisory category для drift; це не дозвіл повторювати apply.

## Окремі наступні production етапи

Потрібні свіжий read-only audit та прийнятий maintenance adapter. Далі окремо:
provisioning ролей; ownership adoption із приватним evidence та перевіреним
rollback; runtime DSN cutover; acceptance кожної служби; soak і retirement
legacy ролей. Кожен етап має власний явний GO. Поточний кандидат не містить
production apply-команди і не змінює міграції, bootstrap чи service runtime.

## DB executor — source кандидат 11.10.2026

`adoption_production.apply_production` та `inverse_production` споживають
окремі target binding, operation manifest, confirmation і MaintenanceContext.
Binding включає system identifier, dbname/OID, session role, source commit
і runtime digest. RuntimeVerifier має доводити фактичний runtime та походження
checkout roots; цей етап містить його контракт та injected test adapters.
Production path відхиляє саму присутність test environment/failpoint variables.

DB identity, quiescence і runtime перевіряються до mutation, під locks,
перед COMMIT та під час acceptance. Невідомі сесії/jobs блокують операцію;
production код не зупиняє jobs або sessions. Manifest і receipts мають
окремий format 1; intent публікується до першого SQL, committed після COMMIT,
accepted після свіжого read-only gate. Production inverse потребує окремого
INVERSE confirmation і не запускається автоматично після gate failure.
Втрата acknowledgement або доказу після COMMIT означає `commit_unknown`.
Disposable CLI та його компенсація зберігають чинний контракт.

```bash
bash ops/postgres-production-adoption-test.sh
```

Новий runner використовує два власні випадкові Compose projects, той самий
pinned TimescaleDB 2.30.1/PG16 образ і bootstrap fixture. Однакові dbname,
catalog fingerprint та plan не дозволяють прийняти binding першого кластера
на другому: обидва ACL/data fingerprints лишаються незмінними. Лише свіжі
синтетичні journals отримують однаковий фіксований `applied_at` перед baseline;
production/відновлені journals не нормалізуються. Resource names,
Compose labels та network endpoints перевіряються перед attachment/cleanup;
після cleanup підтверджується відсутність власних containers/networks/volumes.
Physical clone з тим самим system identifier та іншим host manifest перевіряє
unit fake RuntimeVerifier: він має відхилити інший runtime digest до connect.
Це не перевірка реального host adapter або production maintenance.

Код executor — коміти `c84d0a9..69c25cc`; isolated acceptance і актуальні
межі наведено в [runbook](../docs/POSTGRES-ADOPTION-PRODUCTION-RUNBOOK.md).
Maintenance stop/start, job pause/resume, runtime failure/restart, DSN cutover
та operational acceptance залишаються окремими етапами.
