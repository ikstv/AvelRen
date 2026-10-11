# Production adoption БД: план реалізації етапу 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Власник погодив план і вибрав послідовних implementers із task reviews 11.10.2026.

**Goal:** Додати перевірений DB executor production adoption із target binding,
receipt contract і explicit inverse, зберігши чинний disposable механізм.

**Architecture:** Повторно використовуємо inventory, planner та evidence.
Спільний транзакційний модуль виконує ownership/ACL із політикою outcome;
production coordinator додає target/operator/runtime/DB gates і окремі receipts.
Production apply CLI лишається закритим до наступного maintenance етапу.

**Tech Stack:** Python, psycopg, PostgreSQL 16, TimescaleDB 2.30.1,
pytest, Ruff, чинний ізольований Docker runner; нових залежностей немає.

**Spec:** [Погоджена специфікація](../specs/2026-10-11-postgres-production-adoption-design.md),
підготовлена комітом `2e3ee5b`, погоджена власником 11.10.2026.

## Global Constraints

- PostgreSQL 16, TimescaleDB 2.30.1, точний journal/SHA 001–016.
- Existing snapshot/plan format 1 і disposable CLI лишаються сумісними.
- Production operation manifest і receipts мають окремий format_version 1.
- Застосовані міграції, дані, функції, паролі й адміністративні ролі не змінюються.
- Production apply CLI закритий, доки не прийнятий maintenance adapter.
- Production path відхиляє test-mode environment і test failpoints.
  Конкретні заборонені variables: AVELREN_DATABASE_TEST та
  AVELREN_ADOPTION_TEST_FAILPOINT, навіть із порожнім/нульовим значенням.
- Linux evidence 0700/0600, поза checkout, без symlinks/hardlinks/overwrite.
- Credentials лише через захищене середовище; немає DATABASE_URL fallback.
- COMMIT acknowledgement/receipt loss → commit_unknown, без повтору mutation.
- Production inverse тільки явний; disposable компенсація зберігає поведінку.
- Жодних live DSN/volumes, service stop/start, єЧерга probes чи deployment.
- Сім обмежених ролей: backup, collector, notifier, watchdog, api, surge, migrator.

## Review Focus

1. Однакова назва БД/каталог в іншому кластері або physical clone: binding
   і повторна runtime verification мають зупинити mutation — задачі 1/5.
2. JSON duplicate keys, bool замість int, невідомі поля та receipt іншої
   операції не стають дозволом на inverse — задачі 1/2/5.
3. Сесія чи job з'явились під час очікування lock: повторна DB/runtime
   перевірка до mutation, обмежене очікування — задачі 3/4/5.
4. COMMIT відбувся, але acknowledgement/fsync/receipt не підтверджені:
   жодного повторного COMMIT або удаваного rollback — задачі 4/5.
5. Explicit inverse після стороннього drift/неповного evidence:
   зберегти чужу зміну й залишити невідомий outcome для діагностики — задача 5.

## Файли та спільні інтерфейси

Нові модулі в `services/backend/src/avelren/`:
`adoption_target.py` — binding; `adoption_operation.py` — manifest/receipts;
`adoption_operator.py` — production confirmation; `adoption_preflight.py` —
DB quiescence; `adoption_transaction.py` — транзакції; `adoption_production.py`
— production coordinator без публічного mutation CLI.

Чинні `adoption_inventory.py`, `adoption_plan.py`, `adoption_evidence.py`,
`privilege_gate.py` використовуємо без зміни контракту. У
`postgres_adoption.py` лише інтегруємо спільні транзакції, зберігаючи API.
Не змінюємо provenance-listed legacy source або requirements.lock.

Кожна задача має unit-тести у `services/backend/tests/unit/` із назвою
модуля; DB-тести — `services/backend/tests/database/test_adoption_production.py`
та чинний `test_adoption_failures.py`. Two-cluster acceptance має окремий файл
`services/backend/tests/rehearsal/test_adoption_two_cluster.py` і власний runner.
Нові звичайні DB test names містять adoption,
щоб їх обрав наявний `bash scripts/test_database.sh adoption`.

Команди нижче виконуються з кореня в налаштованому Linux backend runtime:
`python -m pytest -c services/backend/pytest.ini <FILE> -q`.
На Windows використовуємо чинний cached Docker test image з bind mount
та `--network none`; не встановлюємо повторно залежності лише заради плану.
Не перемикаємо checkout, поки тестовий контейнер читає його bind mount.

## Task 1: target binding без зміни snapshot format

**Files:** Create `services/backend/src/avelren/adoption_target.py`;
Test `services/backend/tests/unit/test_adoption_target.py` та DB test file.

**Interfaces:** Frozen `TargetBinding(format_version: int, system_identifier: str,
database: str, database_oid: int, session_role: str, source_commit: str,
runtime_digest: str)`. Produces `capture_target(conn, *, source_commit: str,
runtime_digest: str) -> TargetBinding`, `encode_target(binding) -> bytes`,
`decode_target(payload: bytes) -> TargetBinding`, `target_digest(binding) -> str`,
`verify_target(conn, expected: TargetBinding) -> None`.
Consumes existing `AdoptionError`; helpers не відкривають з'єднання самостійно.

- [x] Написати RED: `test_adoption_target_canonical_roundtrip` перевіряє
  decode(encode(binding)) == binding і стабільний SHA-256; параметризований
  `test_adoption_target_invalid_format` відхиляє duplicate keys, extra fields,
  bool/int confusion, invalid version, nonpositive OID/system identifier,
  source commit не 40 lowercase hex і runtime digest не 64 lowercase hex.
- [x] Запустити unit file; очікується import/function failure нового модуля.
  Команда: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_adoption_target.py -q`.
- [x] Реалізувати strict JSON schema; system_identifier — decimal string,
  format_version == 1, OID — positive int, database/session_role — непорожні
  рядки без NUL. Читати identity через pg_control_system()/pg_database та
  session_user; permission/read failure не замінювати dbname-only fallback.
- [x] Додати DB assertions: актуальний binding збігається; altered OID,
  system identifier або session role відхиляється до SQL mutation.
  Two-cluster case зі справжніми різними clusters належить задачі 6.
- [x] Unit GREEN; DB case GREEN через adoption runner; commit модуля й тестів.

## Task 2: operation manifest, receipts та підтвердження

**Files:** Create `adoption_operation.py`, `adoption_operator.py` у src;
Test `test_adoption_operation.py`, `test_adoption_operator.py` у unit.

**Interfaces:** Frozen `OperationManifest(format_version: int, operation_id: str,
target_digest: str, plan_digest: str, before_fingerprint: str,
expected_fingerprint: str)`. `make_operation(binding, plan) -> OperationManifest`
створює operation_id uuid4 hex; `encode_operation`, `decode_operation`,
`write_operation(directory: Path, manifest) -> None`,
`read_operation(directory: Path) -> OperationManifest`.
`write_receipt(directory: Path, phase: str, manifest, *, category: str | None)
-> None`, `verify_receipt(directory: Path, phase: str, manifest) -> None`.
`require_production_evidence(directory: Path, *, checkout_roots: tuple[Path, ...])
-> None` вимагає абсолютний шлях поза всіма перевіреними checkout roots.
Consumes target_digest, plan_digest/fingerprint, read_private/write_private.

Frozen `Confirmation(action: str, operation_id: str, target_digest: str,
plan_digest: str)`; `confirm_operator(action: str, manifest) -> Confirmation`
перевіряє Linux/root, заборонені env і читає `/dev/tty`.
`verify_confirmation(confirmation, action: str, manifest) -> None`.
Actions — тільки ADOPT/INVERSE. Фраза: action, пробіл, повний target digest,
пробіл, повний plan digest. Confirmation зв'язаний із поточною operation ID.

- [x] RED `test_adoption_operation_roundtrip_and_binding`: target/plan/
  fingerprint hashes точні; `test_adoption_receipt_cross_operation_refused`
  міняє тільки operation_id і очікує відмову.
- [x] RED `test_adoption_operator_requires_live_tty_and_exact_action`:
  fake TTY/root/env adapters; неправильна фраза, action, не-Linux, non-root,
  не-TTY та наявний test mode/failpoint відхиляються без psycopg.connect;
  sentinel credential не присутній у stdout/stderr.
- [x] Запустити два unit files; підтвердити RED нового інтерфейсу.
  Команда: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_adoption_operation.py services/backend/tests/unit/test_adoption_operator.py -q`.
- [x] Реалізувати strict canonical manifests/records. Production filenames:
  `production-operation.json`, `production-apply-intent.json`,
  `production-committed.json`, `production-accepted.json`,
  `production-inverse-intent.json`, `production-inverse-committed.json`,
  `production-inverse-accepted.json`. Усі records містять version/operation/
  target/plan/before/expected та phase/category; невідомий phase заборонений.
  Рядки DSN, passwords, SQL errors чи application data не включати.
- [x] Додати tests duplicate/unknown fields, corrupt/foreign disposable
  receipt, overwrite, checksum tampering, symlink/hardlink, permissions,
  interrupted publication. Використати існуючі evidence helpers без дубля.
  Окремо absolute/outside-checkout test: relative path і вкладений у checkout
  каталог відхиляються навіть із 0700; невідомий/порожній roots tuple теж.
- [x] GREEN unit files на Linux; commit operation/operator і тестів.

## Task 3: DB quiescence та обмежені locks

**Files:** Create `services/backend/src/avelren/adoption_preflight.py`;
Test unit `test_adoption_preflight.py` та DB production test file.

**Interfaces:** `require_quiescent(conn) -> None` перевіряє актуальну ціль;
`acquire_adoption_locks(conn, database: str, *, timeout_ms: int = 10000)
-> None`. Consumes AdoptionError і чинний перелік application lock targets
із postgres_adoption/privilege_gate, без нового дубльованого ACL контракту.

- [x] RED `test_adoption_quiescence_rejects_idle_session`: друга idle client
  session дає відмову; `test_adoption_quiescence_jobs` відхиляє scheduled,
  Running, неповний/unknown job metadata та непідтримуваний background writer.
  Mock prepared transaction для unit; відсутність read permission теж відмова.
- [x] RED `test_adoption_advisory_wait_is_bounded`: зайнятий session advisory
  lock завершує очікування timeout, не чекає безмежно й не міняє ACL.
- [x] Запустити unit file і відповідний DB selector; підтвердити RED.
  Команди: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_adoption_preflight.py -q`;
  `AVELREN_ADOPTION_TEST_SELECTOR=adoption_quiescence bash scripts/test_database.sh adoption`.
  Lock-wait DB test: `AVELREN_ADOPTION_TEST_SELECTOR=adoption_advisory bash scripts/test_database.sh adoption`.
- [x] Реалізувати reads pg_stat_activity, pg_prepared_xacts та Timescale
  jobs/job_stats. Не зберігати query text/config із потенційними секретами
  в diagnostics. Звірити фактичні pinned 2.30.1 columns/worker identities
  у test DB; невідомі worker types — відмова, не широка allowlist за name.
- [x] Lock очікувати в autocommit із statement timeout 10000ms, після нього
  почати repeatable-read й отримати ті самі application object locks до
  першого capture. Identity reads до RR виконуються окремо, не створюють
  stale transaction snapshot. Timeout не завершує чужі sessions.
- [x] Unit/DB GREEN, включно з появою session під час lock wait;
  commit preflight і tests. Jobs не pause/resume у цьому етапі.

## Task 4: спільний engine зі збереженням disposable поведінки

**Files:** Create `services/backend/src/avelren/adoption_transaction.py`;
Modify `postgres_adoption.py` (_lock, _inverse, apply_disposable);
Test existing unit CLI/DB failures та new `test_adoption_transaction.py`.

**Interfaces:** Frozen `TransactionOutcome(status: str, category: str | None,
fingerprint: str | None)`. `run_mutation(dsn: str, plan: AdoptionPlan, *,
direction: str, before_write, before_commit) -> TransactionOutcome`:
direction forward/inverse; callbacks приймають live connection і повертають
None або AdoptionError. Engine не пише receipts, не підтверджує оператора,
не керує runtime і не виконує автоматичний post-commit inverse.
Consumes read_snapshot/fingerprint/capture, план і locks із задачі 3.

- [x] Спершу запустити чинний unit CLI і adoption DB suite як baseline.
  RED new `test_adoption_mutation_commit_ack_loss_closes_connection`:
  commit error викликає close, не повторний context-manager COMMIT/rollback;
  `test_adoption_inverse_commit_ack_loss_is_unknown` має той самий результат.
- [x] Реалізувати engine: validated/regenerated plan, locks, callback,
  re-capture очікуваного from fingerprint, statements, перевірка to fingerprint,
  before_commit callback, commit. До commit exception — rollback та окремий
  read-only доказ from; непідтверджений rollback — rollback_failed.
- [x] Перенести disposable orchestration на engine, зберігши _guards,
  FAILPOINTS, private API _inverse і AdoptionResult signatures, старі filenames,
  automatic guarded inverse після disposable acceptance failure та CLI rc.
  Production-only quiescence не нав'язувати disposable fixtures без потреби.
- [x] GREEN unit file, existing CLI, lock-wait regression і весь adoption
  DB suite; assert no diff у db/migrations/bootstrap; commit engine/refactor.
  Команди: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_adoption_transaction.py services/backend/tests/unit/test_postgres_adoption_cli.py -q`;
  `bash scripts/test_database.sh adoption`.

## Task 5: production coordinator та explicit inverse

**Files:** Create `services/backend/src/avelren/adoption_production.py`;
Test unit `test_adoption_production.py`, DB production test file.

**Interfaces:** Frozen `MaintenanceContext(operation_id: str, target_digest: str,
plan_digest: str, runtime_digest: str, phase: str)`; phase лише quiescent.
`RuntimeVerifier.verify(context: MaintenanceContext, manifest: OperationManifest)
-> None` — Protocol наступного adapter, обов'язкова фактична повторна перевірка.
`RuntimeVerifier.checkout_roots() -> tuple[Path, ...]` повертає перевірені
source/runtime checkout roots для evidence location guard із задачі 2.
`apply_production(dsn: str, binding: TargetBinding, plan: AdoptionPlan,
evidence_dir: Path, context: MaintenanceContext, confirmation: Confirmation,
runtime: RuntimeVerifier) -> AdoptionResult` та `inverse_production` з такими
самими параметрами. Consumes задачі 1–4 і privilege_gate.audit.

- [x] RED `test_adoption_production_rejects_context_before_connect`:
  mismatched operation/target/plan/runtime або phase дає нуль mutation;
  runtime verification не можна замінити receipt/timestamp.
  `test_adoption_production_rechecks_runtime_under_locks` відхиляє drift
  після початкового runtime verify, навіть за незмінного DB fingerprint.
- [x] RED DB forward acceptance та explicit inverse: synthetic legacy-like
  ownership, compressed chunks/CAGG, hashes journal/data/function definitions
  точні; privilege gate приймає forward; inverse повертає before fingerprint.
- [x] Реалізувати apply: production env guard, binding/manifest/confirmation,
  runtime verify, evidence location guard, plan regeneration, preflight, intent;
  engine callback повторює
  binding/runtime/quiescence. Після commit committed receipt, fresh capture,
  gate, accepted receipt. Receipt/verification loss → commit_unknown.
  Підтверджене gate failure → rollback_failed/category acceptance_failed,
  без автоматичного inverse. already_target вимагає валідний receipt chain
  і фактичний expected fingerprint; неповний intent блокує повтор.
- [x] Реалізувати inverse: окремий INVERSE confirmation, валідні production
  intent/committed records, maintenance і exact expected fingerprint під locks.
  Explicit inverse допустимий при збереженому committed receipt навіть без
  accepted після підтвердженої gate failure; відсутній committed не дозволяє
  компенсацію. Post-inverse capture/receipt loss → commit_unknown.
- [x] RED/GREEN assertions для before_commit SQL failure, commit_ack_loss,
  receipt fsync failure, acceptance failure, inverse error та чужого drift;
  чужий GRANT збережено, automatic inverse не викликано. Corrupt receipt
  відмовляє до mutation, stdout/stderr без sentinel DSN.
- [x] У isolated tests injected runtime/operator adapters не походять із CLI;
  fixture спершу звіряє test DB prefix/DSN, після цього прибирає production-
  forbidden env тільки на час coordinator call. Немає bypass flag у коді.
  Test failpoints підміняють connection/filesystem/gate, не environment mode.
- [x] GREEN unit/DB tests; commit coordinator. Жодного apply-production/
  inverse-production parser route, інсталяції чи service mutation.
  Команди: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_adoption_production.py -q`;
  `AVELREN_ADOPTION_TEST_SELECTOR=adoption_production bash scripts/test_database.sh adoption`.

## Task 6: приймання, документація та whole-branch review

**Files:** Create `ops/postgres-production-adoption-test.sh` для two-cluster
fixture; Modify `ops/POSTGRES-ADOPTION.md`, production runbook,
`docs/MIGRATION-REMAINING.md`, `docs/RELEASE-READINESS.md`;
Modify `.github/workflows/database.yml` тільки для нового isolated rehearsal.

- [x] RED two-cluster rehearsal: один план/catalog і однакове dbname,
  target від першого кластера не приймається другим; перший/другий
  fingerprints незмінні. Runner створює тільки власні random Compose
  projects/БД, без live env; cleanup перевіряє ownership resource names.
- [x] Реалізувати runner на тому самому pinned Timescale image, reuse
  existing fixture helpers. Physical-clone identity ambiguity перевірити
  unit fake runtime із тим самим system identifier та іншим host manifest.
- [x] GREEN rehearsal і adoption restore rehearsal; cleanup без власних
  залишкових контейнерів/volumes. Не змінювати checkout під bind-mounted run.
  Команди: `bash ops/postgres-production-adoption-test.sh` та
  `bash ops/postgres-adoption-restore-test.sh`.
- [x] Оновити docs: DB executor source готовий, production CLI закритий,
  maintenance adapter, DSN cutover та operational acceptance залишаються.
  Записати фактичні commit/test межі, не називати сервер прийнятим.
- [x] Фінально: backend unit suite; Ruff; verify_ci_scopes.py;
  verify_core_provenance.py; git diff --check; bash scripts/test_database.sh
  adoption; bash ops/postgres-adoption-restore-test.sh; новий rehearsal.
  Success — exit 0, усі обрані tests PASS, cleanup підтверджений.
  Unit: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q`.
  Ruff: `python -m ruff check services/backend/src services/backend/tests scripts/*.py`.
  Repository: `python scripts/verify_ci_scopes.py`,
  `python scripts/verify_core_provenance.py`, `git diff --check`.
- [x] Whole-branch review через requesting-code-review: один незалежний
  reviewer; поправки перевірити відповідними regression tests.
- [ ] Draft PR до main, attach artifact, exact-head relevant CI; integration
  лише після review/CI. Серверні операції й новий maintenance план — окремо.

## Мінімальні assertions для test-first циклів

Наведені фрагменти — конкретні assertions у названих tests; fixture/helper
імена створюються в їхніх unit/DB файлах, не є новими production API.

```python
# Задача 1: binding fixture має version=1 та valid positive identity.
assert decode_target(encode_target(binding)) == binding
assert target_digest(binding) == target_digest(decode_target(encode_target(binding)))
# Задача 2: context іншої операції не приймається за receipt того самого plan.
with pytest.raises(AdoptionError):
    verify_confirmation(other_operation_confirmation, "INVERSE", manifest)
# Задача 3: друга відкрита idle session відхиляється без terminates.
with pytest.raises(AdoptionError):
    require_quiescent(admin_connection)
# Задача 4: simulated inverse COMMIT acknowledgement loss.
assert outcome.status == "commit_unknown"
assert connection.commit.call_count == 1
assert connection.rollback.call_count == 0
# Задача 5: production gate failure не запускає автоматичний inverse.
assert result.status == "rollback_failed"
assert result.category == "acceptance_failed"
inverse_spy.assert_not_called()
# Задача 6: two-cluster target refusal не змінює чужу БД.
assert fingerprint(snapshot_second_cluster_after) == fingerprint(snapshot_second_cluster_before)
```

## Самоперевірка та спосіб виконання

Binding → задача 1; evidence/operator → 2; DB session/jobs/locks → 3;
спільні transactions → 4; production outcome/explicit inverse → 5;
two-cluster та інтеграція → 6. Кожен Review Focus має названий test.
MaintenanceContext/RuntimeVerifier тільки контракт цього етапу: реалізація
stop/start, job pause/resume, runtime rc 5 і DSN cutover належать наступним
планам; їх немає в production CLI поточної зміни.

Власник погодив план 11.10.2026 та обрав окремих послідовних implementers
із review кожної задачі. Задачі 1–5 реалізовані й прийняті task reviews
(`c84d0a9..69c25cc`). Whole-branch review, exact-head CI та integration
залишаються окремими незакритими gates задачі 6.


Фінальні локальні докази та рішення: [verification](2026-10-11-postgres-production-executor-verification.md). Hosted CI та серверне приймання перевіряються окремо.
