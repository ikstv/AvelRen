# План реалізації PostgreSQL adoption 001–016

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести inventory, forward/inverse ownership/ACL та перевірений відкат у ORIGINAL із disposable-прийманням.

**Architecture:** Чотири модулі backend розділяють каталог, evidence, планування та виконання. Контракт прав береться з privilege_gate; усі SQL identifiers/literals складаються psycopg.sql. Production apply відсутній.

**Tech Stack:** Python чинного backend lock, psycopg, pytest; PostgreSQL 16 / TimescaleDB 2.30.1 у штатному Docker runner.

**Spec:** [Погоджений дизайн](../../POSTGRES-ADOPTION-016-DESIGN.md).

## Global Constraints

- Гілка `codex/postgres-adoption-016` залежить від PR #106, head `f03fdaac15c9f1421a71d58070ffc9c8ebbd4a14`.
- Міграції 001–016, journal/applied_at, function bodies/security/search_path не змінюються.
- Production, upstream, парольні значення, provisioning/retirement ролей, Compose/systemd та runtime DSN cutover не входять у реалізацію.
- Не використовувати REASSIGN OWNED, DROP OWNED або запис у системні каталоги.
- Timescale internals/extension/bootstrap ownership не змінювати довільно; побічний ефект ALTER root має підтверджуватися topology-тестом.
- Немає нових залежностей. DSN лише з `AVELREN_ADOPTION_DSN`, ціль із `AVELREN_ADOPTION_TARGET`; не використовувати DATABASE_URL як fallback.
- Disposable apply: `AVELREN_DATABASE_TEST=1`, target відповідає `^avelren_case_[0-9a-f]{32}_test$`, DSN dbname та current_database() точно збігаються з target.
- Snapshot/plan формат — version 1. Невідома версія, зайві/відсутні обов'язкові поля або суперечливі ідентичності відхиляються.
- Read-only inventory: repeatable read, примусовий default_transaction_read_only=on; connect/lock timeout 10 секунд, statement timeout 30 секунд.
- Семантичний fingerprint враховує grantor/GRANT OPTION; фізичні OID і відмінність NULL ACL від еквівалентного default ACL не впливають.
- Українська документація/коміти; зберегти посилання на frozen джерела обох старих репозиторіїв.

## Review Focus

1. Ідентифікатор із лапками або SQL-подібним текстом — коректний quoting або відмова, ніколи виконання довільного SQL (задачі 1, 3).
2. NULL ACL, PUBLIC та delegation chain із кількома grantors — точний inverse або відмова до першої мутації (задачі 1, 3).
3. Drift між plan і apply або між commit і inverse — відмова, яка зберігає сторонню зміну (задача 4).
4. Пошкоджений/підмінений evidence, symlink/reparse point, збій запису receipt після commit — жодного фальшивого success чи destructive retry (задачі 2, 4).
5. Compressed chunks і continuous aggregate з іншою ownership-топологією — виміряний allowlist або fail-closed, без широкого reassignment (задачі 1, 3, 5).

## Структура та спільні типи

- `services/backend/src/avelren/adoption_inventory.py`: read-only каталог, формат і fingerprint.
- `services/backend/src/avelren/adoption_evidence.py`: приватні атомарні файли та hashes.
- `services/backend/src/avelren/adoption_plan.py`: typed plan, preflight і forward/inverse SQL.
- `services/backend/src/avelren/postgres_adoption.py`: CLI та disposable state machine.
- Unit-тести: `services/backend/tests/unit/test_adoption_inventory.py`, `test_adoption_evidence.py`, `test_adoption_plan.py`, `test_postgres_adoption_cli.py`.
- Database-тести: `services/backend/tests/database/test_adoption_inventory.py`, `test_adoption_roundtrip.py`, `test_adoption_failures.py`, `test_adoption_topology.py`.
- Restore runner: `ops/postgres-adoption-restore-test.sh`; runbook: `ops/POSTGRES-ADOPTION.md`.

Тип `Snapshot` — frozen dataclass: `format_version: int`, `database: str`, `sections: dict[str, list[dict[str, object]]]`.
Sections: database, schemas, relations, columns, routines, defaults, roles, memberships, dependencies, topology, shared, journal.
Кожен запис має schema-qualified semantic identity; ACL — список grantor/grantee/privilege/grantable. PUBLIC має окремий ідентифікатор, а не role OID 0.
Тип `AdoptionError` — виняток із лише стабільним `category: str`, без SQL, DSN або server message.
Тип `AdoptionPlan` — frozen dataclass: `format_version: int`, `before: Snapshot`, `expected: Snapshot`, `forward: tuple[str, ...]`, `inverse: tuple[str, ...]`.
Тип `AdoptionResult` — frozen dataclass: `status: str`, `category: str | None`, `before_fingerprint: str`, `after_fingerprint: str | None`.

## Задача 1: read-only inventory та fingerprint

**Files:** inventory module, два inventory test files; існуючу database fixture використовувати без зміни її production guards.

**Interfaces:** `capture(conn: psycopg.Connection) -> Snapshot`, `encode(snapshot: Snapshot) -> bytes`, `decode(payload: bytes) -> Snapshot`, `fingerprint(snapshot: Snapshot) -> str`; `AdoptionError` визначається тут.

- [ ] Написати failing tests: fresh snapshot містить рівно 21 application relation, 11 sequences, чотири functions, journal 16; повторний capture дає той самий fingerprint.
- [ ] Unit assertions: reordered rows/ACL та заміна фізичних OID не змінюють fingerprint; зміна owner/grantor/grantable/journal змінює його; encode/decode round-trip точний; version 2 і malformed input відхиляються.
- [ ] Database assertions: inventory залишає journal, synthetic rows і catalog metadata незмінними; NULL ACL розгортаються семантично; writable transaction відхиляється категорією read_only_required; extension members і application functions відділені.
- [ ] Запустити unit tests та `bash scripts/test_database.sh`, підтвердити RED через відсутній модуль/поведінку.
- [ ] Реалізувати каталог згідно interfaces і sections; не читати парольні поля pg_authid, дані tables або виконувати application functions.
- [ ] Повторити відповідні tests до GREEN; commit inventory і tests.

## Задача 2: evidence без перезаписування та секретів

**Files:** evidence module і unit tests.

**Interfaces:** `write_private(directory: Path, name: str, payload: bytes) -> str` повертає SHA-256; `read_verified(directory: Path, name: str, expected_sha256: str) -> bytes`.
Consumes: AdoptionError із задачі 1. Names — тільки прості basenames, без absolute path, separator або `..`.

- [ ] RED tests: create/read/hash; існуючий файл, path traversal, symlink parent/file, некоректний hash і загальнодоступний evidence directory відхиляються; private file permissions підтверджуються на Linux.
- [ ] Failure tests: simulated short write/fsync/atomic publication error не публікує частковий final file; помилки не містять sentinel DSN; довільний input path не використовується для delete.
- [ ] Реалізувати atomic exclusive publication і validation через native filesystem primitives; Windows reparse-point відхиляти, POSIX files 0600/directories 0700. Окремий temporary file прибирати лише за підтвердженої власності поточного виклику.
- [ ] GREEN unit tests; commit evidence і tests.

## Задача 3: forward/inverse із чинного контракту

**Files:** plan module, unit plan tests, database roundtrip/topology tests.

**Interfaces:** `build_plan(snapshot: Snapshot) -> AdoptionPlan`, `encode_plan(plan: AdoptionPlan) -> bytes`, `decode_plan(payload: bytes) -> AdoptionPlan`, `plan_digest(plan: AdoptionPlan) -> str`.
Consumes: Snapshot, AdoptionError, encode/fingerprint; ROLES/TABLES/SEQUENCES/TABLE_ACL/COLUMN_ACL/SEQUENCE_ACL/FUNCTIONS із privilege_gate без зміни gate behavior.

- [ ] RED tests: canonical fresh snapshot дає порожні forward/inverse і identical expected fingerprint; owner/ACL legacy-like snapshot дає explicit scoped statements; encode/decode/hash стабільні.
- [ ] Refusal assertions: journal mismatch, role escalation/membership, function body/security/search_path drift, unexpected application object/extension/version і unsupported ownership topology — AdoptionError до SQL execution.
- [ ] SQL assertions: усі identifiers quoted; відсутні migrate, ALTER ROLE, REASSIGN/DROP OWNED, UPDATE catalog або service commands; inverse відновлює columns/functions/defaults та grant options.
- [ ] Реалізувати планування з expected snapshot; не копіювати SQL міграції 010 як forward. Default ACL і grantor залежності обробляти явно; непідтримуваний grant graph відхиляти.
- [ ] Database round-trip: тест сам застосовує statements в транзакціях через admin fixture; forward проходить privilege gate, inverse fingerprint дорівнює before. Journal/applied_at та synthetic rows точні.
- [ ] Topology fixture із compressed observations, chunks та observations_hourly: capture/план/round-trip доводять очікувані побічні ownership-зміни, усі інші owners незмінні. Quoted identifiers поза allowlist відхиляються до запису.
- [ ] GREEN unit/database tests; commit planner і tests.

## Задача 4: disposable CLI та перевірений відкат

**Files:** postgres_adoption module, unit CLI tests, database failure tests.

**Interfaces:** `apply_disposable(dsn: str, target: str, plan: AdoptionPlan, evidence_dir: Path, *, failpoint: str | None = None) -> AdoptionResult`; `main(argv: list[str] | None = None) -> int`.
Consumes: interfaces задач 1–3 та read-only privilege_gate.audit; connection details не потрапляють у Result/evidence.

CLI: `inventory --output-dir PATH`, `plan --evidence-dir PATH`, `apply-test --evidence-dir PATH`, `inspect --evidence-dir PATH`.
Test failpoint лише `AVELREN_ADOPTION_TEST_FAILPOINT`, приймається тільки після disposable guards.
JSON містить status/category/fingerprints; rc 0 — adopted/already_target/inspected, 1 — refused/rolled_back, 2 — unavailable, 3 — rollback_failed, 4 — commit_unknown.

- [ ] RED subprocess tests: відсутні DSN/target, невідомі/production аргументи, prod target, інша DSN database, вимкнений test mode, extra argv — відмова без SQL mutation; stderr не розкриває sentinel DSN.
- [ ] Реалізувати apply preflight: guards, цілісність plan/evidence, відсутність інших application sessions, advisory/object locks і fingerprint recheck перед першою зміною. Не завершувати sessions.
- [ ] Реалізувати transaction forward, post-commit snapshot/gate, receipt і guarded inverse; кожен етап фіксує intent/state атомарно. Невдала компенсація не повертає success.
- [ ] Database assertions для failpoints before_commit/after_commit/during_inverse/receipt_write: відповідно початковий fingerprint, verified rollback, rollback_failed, commit_unknown. Receipt failure не спричиняє автоматичного повтору apply.
- [ ] Drift tests: інша session, зміна після plan і після commit перед inverse — відмова зі збереженням чужої зміни; timeout не залишає частково застосований forward.
- [ ] Повторний apply canonical target повертає already_target; некоректний/пошкоджений receipt не приймається як доказ завершення.
- [ ] GREEN unit/database tests; commit executor і tests.

## Задача 5: restore-приймання, runbook і інтеграція

**Files:** restore runner, ops/POSTGRES-ADOPTION.md, docs/MIGRATION-REMAINING.md, docs/POSTGRES-ADOPTION-GAP-2026-10-01.md, docs/RELEASE-READINESS.md; `.github/workflows/database.yml` для окремого disposable restore step.

**Interfaces:** runner `bash ops/postgres-adoption-restore-test.sh` створює лише випадковий власний Compose project/БД; cleanup видаляє тільки його resources.
Consumes: штатні synthetic restore helpers/Timescale pre/post hooks та CLI задачі 4. Не використовувати production backup, volumes або env.

- [ ] RED integration rehearsal: synthetic fresh restore із compressed даними/continuous aggregate; inventory → plan → apply-test → privilege gate → inverse і точна звірка original fingerprint/data/journal.
- [ ] Реалізувати runner на чинному pinned Timescale image; не встановлювати іншу версію або дублювати production orchestrator. Cleanup failure лишає зрозумілий failed результат.
- [ ] Перенести runbook: separate provisioning, ownership adoption, DSN cutover, runtime acceptance, soak/retirement. Старий stamp 010 не переносити в поточну 001–016; не додавати production apply command у цьому PR.
- [ ] Документи мають frozen source links, dependency PR #106 та чіткий статус code/CI; production ще не прийнятий.
- [ ] Виконати backend unit suite, `bash scripts/test_database.sh`, restore rehearsal, Ruff, `python scripts/verify_core_provenance.py`, `git diff --check`; усе GREEN. Перевірити незмінність db/migrations і bootstrap.
- [ ] Незалежний whole-branch review за requesting-code-review; виправлення перевіряти цільовими регресіями.
- [ ] Створити draft PR, спочатку base `codex/postgres-privilege-gate-016`, attach artifact, перевірити всі CI exact head. Base main змінювати лише після інтеграції dependency, без merge цього PR і production deployment.

## Самоперевірка та виконання

Spec sections покриті задачами 1–5; Review Focus має відповідні негативні тести.
Імена спільних types/interfaces узгоджені. План не допускає production apply
і не змінює погоджену межу між source acceptance та production-операцією.

Рекомендований спосіб — native: реалізую сам у цій сесії, один незалежний
перегляд усієї гілки наприкінці. Задачі залежать від одного snapshot/plan
контракту; цей спосіб зменшує передачі контексту між виконавцями.
