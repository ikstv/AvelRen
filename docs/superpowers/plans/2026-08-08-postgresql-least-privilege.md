# PostgreSQL Least-Privilege Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and prove seven isolated PostgreSQL roles, reversible existing-database adoption, operational backup/restore credentials, and per-container secret isolation for issue #15.

**Architecture:** An admin-only staged bootstrap creates roles, provisions TimescaleDB, and closes database/schema `PUBLIC` access; migration `010` grants exact application ACLs and migrator-owned default privileges. Disposable integration suites execute real service paths under four independent runtime DSNs, verify deny-by-default and backup/restore behavior, and exercise both transactional adoption failure and committed-adoption inverse rollback before Compose can start runtime services.

**Tech Stack:** PostgreSQL 16, TimescaleDB 2.17.2, SQL/psql, Bash, Docker Compose, Python 3.12, psycopg 3, pytest, GitHub Actions.

## Global Constraints

- Only `collector` may contact `echerha.gov.ua` or `back.echerha.gov.ua`; no new external request path is permitted.
- Collector polling remains exactly 60 seconds start-to-start, every run remains durable, and upstream failures receive no aggressive retry.
- Do not edit migrations `001` through `009`; add only sequential migration `010_postgresql_least_privilege.sql`.
- The canonical roles are `avelren_admin`, `avelren_migrator`, `avelren_backup`, `avelren_collector`, `avelren_notifier`, `avelren_watchdog`, and `avelren_api`.
- `avelren_admin` owns the database, `public` schema, and TimescaleDB extension; `avelren_migrator` owns application objects.
- Migrator, backup, and runtime roles are `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION` and have no admin/migrator membership.
- Runtime containers must not receive admin, migrator, backup, legacy, or sibling-service DSNs.
- Unknown ownership, privilege failure, secret leakage, or inverse-plan mismatch fails closed while runtime remains stopped.
- All destructive database tests target names containing `test` or `ci`, set `AVELREN_TEST_DB=1`, and use disposable Compose volumes.
- No production deployment, restore, credential rotation, GitHub issue mutation, or secret publication is part of this plan.

## File map

- `db/security/bootstrap.sql`: fixed role attributes, database/schema boundary, and idempotent role password assignment from psql environment variables.
- `deploy/postgres-bootstrap.sh`: fail-closed staged fresh-install/admin entrypoint; provisions TimescaleDB before migrations.
- `db/migrations/010_postgresql_least_privilege.sql`: explicit object, column, sequence, and migrator default privileges.
- `app/tests/test_db_privileges.py`: metadata, positive SQL path, negative ACL, and future-object contracts using independent DSNs.
- `deploy/postgres-roles-integration-test.sh`: disposable database orchestration for bootstrap, migrations, and privilege tests.
- `deploy/compose-security-contract-test.sh`: resolved-Compose environment allowlist without printing resolved secrets.
- `deploy/backup.sh`, `deploy/restore-engine.lib.sh`, `deploy/restore-production.sh`, `deploy/restore-verify.sh`: backup-role and admin-role operational DB access.
- Existing backup/restore contract and integration tests: prove the operational credential split and DR compatibility.
- `deploy/postgres-ownership.lib.sh`: deterministic catalog manifest, allowlist validation, forward plan, inverse plan, and owner/ACL verification functions.
- `deploy/postgres-adopt.sh`: maintenance orchestrator that refuses mutation until both plans validate.
- `deploy/postgres-adoption-contract-test.sh`: mock/fail-closed shell-level orchestration contracts.
- `deploy/postgres-adoption-integration-test.sh`: production-like disposable TimescaleDB forward and inverse adoption tests.
- `docker-compose.yml`, `.env.example`: service-specific DSNs and explicit non-secret settings.
- `.github/workflows/ci.yml`, `scripts/backend-test.sh`, `docs/backend-testing.md`, `README.md`, `docs/disaster-recovery.md`: CI and operator documentation.

---

### Task 1: Admin bootstrap and seven-role contract

**Files:**
- Create: `db/security/bootstrap.sql`
- Create: `deploy/postgres-bootstrap.sh`
- Create: `deploy/postgres-bootstrap-contract-test.sh`
- Modify: `.env.example`

**Interfaces:**
- Consumes: admin `psql` access and environment variables `AVELREN_ADMIN_PASSWORD`, `AVELREN_MIGRATOR_PASSWORD`, `AVELREN_BACKUP_PASSWORD`, `AVELREN_COLLECTOR_PASSWORD`, `AVELREN_NOTIFIER_PASSWORD`, `AVELREN_WATCHDOG_PASSWORD`, and `AVELREN_API_PASSWORD`.
- Produces: idempotent `deploy/postgres-bootstrap.sh fresh|roles-acl`, seven fixed roles, admin-owned database/schema/extension, and closed database/schema `PUBLIC` ACLs.

- [ ] **Step 1: Write the failing shell contract**

Create `deploy/postgres-bootstrap-contract-test.sh` with a fake `psql` executable that records only statement/file identifiers, never environment values. Assert that missing any one required password exits nonzero before the fake is called; `AVELREN_TEST_DB` absent rejects a target ending `_test`; `fresh` orders role creation before database creation, extension provisioning before migrate handoff, and ACL application before success; a fake failure at every stage prevents the next stage.

```bash
assert_fails env -u AVELREN_API_PASSWORD bash deploy/postgres-bootstrap.sh roles-acl
assert_fails env AVELREN_DB_NAME=avelren_test bash deploy/postgres-bootstrap.sh fresh
assert_order "$calls" roles create_database extension acl
PSQL_FAIL_ON=extension assert_fails run_bootstrap fresh
assert_not_contains "$calls" acl
```

- [ ] **Step 2: Run the contract to verify RED**

Run: `bash deploy/postgres-bootstrap-contract-test.sh`  
Expected: FAIL because `deploy/postgres-bootstrap.sh` and `db/security/bootstrap.sql` do not exist.

- [ ] **Step 3: Implement the minimal staged bootstrap**

Implement strict Bash (`set -euo pipefail`, `umask 077`) with fixed role names and no password arguments on the command line. `bootstrap.sql` uses psql `\getenv` plus `format('%L', value) \gexec` for password literals, creates missing roles, and resets every non-admin role to:

```sql
ALTER ROLE avelren_migrator NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_backup NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_collector NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_notifier NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_watchdog NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_api NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
```

The script checks stages idempotently, runs `CREATE DATABASE` outside a transaction, provisions `timescaledb` as admin, revokes all database/schema privileges from `PUBLIC`, grants only `CONNECT` and schema access from the frozen spec, and verifies owners via catalog queries. Explicit cleanup is enabled only with `--disposable-empty-test` plus both test-name and emptiness proofs.

Add empty example values for all seven passwords/DSNs; retain no usable credential.

- [ ] **Step 4: Run the bootstrap contract to verify GREEN**

Run: `bash deploy/postgres-bootstrap-contract-test.sh`  
Expected: PASS, including stage-failure and no-secret-output assertions.

- [ ] **Step 5: Commit**

```bash
git add db/security/bootstrap.sql deploy/postgres-bootstrap.sh deploy/postgres-bootstrap-contract-test.sh .env.example
git commit -m "feat: add PostgreSQL role bootstrap"
```

---

### Task 2: ACL migration, deny-by-default, and negative contracts

**Files:**
- Create: `db/migrations/010_postgresql_least_privilege.sql`
- Create: `app/tests/test_db_privileges.py`
- Create: `deploy/postgres-roles-integration-test.sh`

**Interfaces:**
- Consumes: Task 1 roles and `ADMIN_DATABASE_URL`, `MIGRATOR_DATABASE_URL`, `BACKUP_DATABASE_URL`, `COLLECTOR_DATABASE_URL`, `NOTIFIER_DATABASE_URL`, `WATCHDOG_DATABASE_URL`, `API_DATABASE_URL`.
- Produces: migration `010_postgresql_least_privilege` and a disposable role-test runner. Existing migration history verification discovers `010` from the directory and its physical-schema contract remains unchanged because this migration adds ACLs rather than relations or columns.

- [ ] **Step 1: Write RED metadata and negative tests**

In `test_db_privileges.py`, connect separately to every DSN and assert:

```python
@pytest.mark.parametrize("dsn_name", RUNTIME_AND_BACKUP_DSNS)
def test_role_has_no_elevated_capability(dsn_name):
    with connect_env(dsn_name) as conn:
        assert scalar(conn, "SELECT has_schema_privilege(current_user,'public','CREATE')") is False
        assert scalar(conn, "SELECT has_database_privilege(current_user,current_database(),'CREATE')") is False
        assert scalar(conn, "SELECT has_database_privilege(current_user,current_database(),'TEMP')") is False
        assert scalar(conn, "SELECT pg_has_role(current_user,'avelren_admin','MEMBER')") is False
        assert scalar(conn, "SELECT pg_has_role(current_user,'avelren_migrator','MEMBER')") is False
```

Add `assert_denied(dsn, sql)` cases for runtime `CREATE ROLE`, `CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`, migration-history writes, and `SET ROLE`; then the exact role-specific negative matrix from the frozen spec. Assert SQLSTATE `42501` (`insufficient_privilege`) rather than accepting arbitrary errors.

- [ ] **Step 2: Run disposable test to verify RED**

Run: `bash deploy/postgres-roles-integration-test.sh --privileges-only`  
Expected: FAIL because migration `010` and the runner do not yet establish grants.

- [ ] **Step 3: Implement migration `010`**

Revoke all application table/sequence ACLs from `PUBLIC`; apply explicit table and column grants from the spec. Preserve notifier's table-wide `DELETE` on `notification_cancels`, collector's `INSERT`-only outbox access, exact sequence lists, API device column restrictions, and backup read-only dump access. Add global migrator default revokes for functions/types and schema-scoped table/sequence defaults.

The disposable runner must bootstrap as admin, run all migrations as migrator, run the existing schema/history verifier (which discovers `010` and checks its SHA), export role DSNs only to the test process, and always remove its Compose volume. Do not add a fake physical object to `schema_verify.py` for an ACL-only migration.

- [ ] **Step 4: Add future-object isolation test**

Have migrator create uniquely named table/function/enum objects, then assert runtime has no table access, `PUBLIC` cannot execute the function, and `PUBLIC` cannot use the enum. Remove all three objects in `finally` under migrator.

```python
assert scalar(admin, "SELECT has_table_privilege('avelren_api', %s, 'SELECT')", (table,)) is False
assert scalar(admin, "SELECT has_function_privilege('public', %s, 'EXECUTE')", (signature,)) is False
assert scalar(admin, "SELECT has_type_privilege('public', %s, 'USAGE')", (type_name,)) is False
```

- [ ] **Step 5: Run the ACL suite to verify GREEN**

Run: `bash deploy/postgres-roles-integration-test.sh --privileges-only`  
Expected: PASS for metadata, negative matrix, exact sequence access, and future-object cleanup.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/010_postgresql_least_privilege.sql app/tests/test_db_privileges.py deploy/postgres-roles-integration-test.sh
git commit -m "feat: enforce PostgreSQL least privilege"
```

---

### Task 3: Positive contracts through real service SQL paths

**Files:**
- Modify: `app/tests/test_db_privileges.py`
- Modify: `deploy/postgres-roles-integration-test.sh`
- Modify only if a proven SQL-path requirement was missed: `db/migrations/010_postgresql_least_privilege.sql`

**Interfaces:**
- Consumes: Task 2 DSNs and current functions in `db.py`, `alerts.py`, `eta.py`, `notifier.py`, `watchdog.py`, API/TestClient, and cancellation helpers.
- Produces: a privilege suite that fails whenever a real service operation lacks a required grant.

- [ ] **Step 1: Add RED collector positive scenarios**

Seed prerequisite subscriptions/ETA targets as admin; set `settings.database_dsn` and reset `db._pool` to collector DSN. Execute `db.upsert_countries`, `db.upsert_checkpoints`, `db.insert_observations`, `db.record_run`, threshold/ETA evaluation, expiry/cancel enqueue, and `db.record_derived`. Assert committed rows and no device access.

- [ ] **Step 2: Add RED notifier and watchdog positive scenarios**

Under notifier DSN execute the actual pending query, `_mark_sent`, dead-token cleanup, cancellation attempt/accept/abandon flow, and `cleanup_closed`; under watchdog DSN execute `_checks`, `_open_alerts`, health insert/update/recovery paths with FCM mocked. Assert notifier cannot mutate health and watchdog cannot mutate ordinary alerts in the same test fixture.

- [ ] **Step 3: Add RED API positive scenarios**

Run the actual FastAPI app with API DSN through TestClient: `/health`, checkpoint/workload/history reads, device registration/authentication, subscription create/list/delete/ack, ETA create/list/delete/ack, and admin telemetry. Seed and clean fixtures only through the admin connection outside the API request.

- [ ] **Step 4: Run all positive scenarios and capture only missing privilege names**

Run: `bash deploy/postgres-roles-integration-test.sh --positive-only`  
Expected: RED until every real path is represented by migration grants; output must name role/object/operation but never a DSN.

- [ ] **Step 5: Make the smallest ACL corrections and rerun**

Change only migration `010` grants proven necessary by a real current SQL path. Do not grant whole-table write when column privileges suffice and do not weaken any negative assertion.

Run: `bash deploy/postgres-roles-integration-test.sh`  
Expected: PASS for positive, negative, metadata, and future-object suites.

- [ ] **Step 6: Commit**

```bash
git add app/tests/test_db_privileges.py deploy/postgres-roles-integration-test.sh db/migrations/010_postgresql_least_privilege.sql
git commit -m "test: prove service database capabilities"
```

---

### Task 4: Compose per-service DSNs and secret-isolation gate

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Create: `deploy/compose-security-contract-test.sh`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: service DSNs from Tasks 1-3.
- Produces: backend services with explicit environment allowlists and a CI gate that inspects resolved service environments without printing them.

- [ ] **Step 1: Write the RED Compose isolation test**

Create temporary non-secret sentinel DSNs for every role, run `docker compose config --format json` into a mode-0600 temporary file, parse it with Python, and assert exact visibility:

```python
expected = {
    "migrate": {"MIGRATOR_SENTINEL"},
    "collector": {"COLLECTOR_SENTINEL"},
    "notifier": {"NOTIFIER_SENTINEL"},
    "watchdog": {"WATCHDOG_SENTINEL"},
    "api": {"API_SENTINEL"},
}
assert "env_file" not in service_definition
assert seen_database_sentinels == expected[service]
```

Assert runtime never sees admin, migrator, backup, legacy, or sibling sentinels. On failure print only service and forbidden variable category, then delete the resolved file.

- [ ] **Step 2: Run test to verify RED**

Run: `bash deploy/compose-security-contract-test.sh`  
Expected: FAIL because every backend currently uses `env_file: .env`.

- [ ] **Step 3: Replace shared `env_file` with explicit environments**

Map each service's dedicated DSN into container-local `DATABASE_URL`. List shared non-secret settings explicitly only where used; keep FCM path/settings out of collector/API and source-only settings out of notifier/watchdog/API. The DB service receives admin bootstrap variables only; no application runtime service receives them.

- [ ] **Step 4: Run isolation and Compose validation**

Run: `bash deploy/compose-security-contract-test.sh`  
Run: `docker compose --env-file .env.example config --quiet`  
Expected: both PASS without resolved secrets in stdout/stderr.

- [ ] **Step 5: Add CI gate and commit**

```bash
git add docker-compose.yml .env.example deploy/compose-security-contract-test.sh .github/workflows/ci.yml
git commit -m "security: isolate service database credentials"
```

---

### Task 5: Backup-role dump and admin-only restore

**Files:**
- Modify: `deploy/backup.sh`
- Modify: `deploy/backup-contract-test.sh`
- Modify: `deploy/restore-engine.lib.sh`
- Modify: `deploy/restore-production.sh`
- Modify: `deploy/restore-verify.sh`
- Modify: `deploy/restore-contract-test.sh`
- Modify: `deploy/restore-engine-contract-test.sh`
- Modify: `deploy/restore-production-contract-test.sh`
- Modify: `deploy/restore-integration-test.sh`
- Modify: `deploy/restore-production-integration-test.sh`

**Interfaces:**
- Consumes: `avelren_backup` and `avelren_admin` from Task 1 plus existing restore safety invariants.
- Produces: `AVELREN_BACKUP_DB_USER`/backup credential dump path and `AVELREN_ADMIN_DB_USER` admin restore path, with no hard-coded legacy `avelren` operational login.

- [ ] **Step 1: Extend contract tests first**

Assert backup invokes `pg_dump` as `avelren_backup`, never admin/migrator/legacy; restore engine and production orchestrator invoke `psql`, `createdb`, and `dropdb` as `avelren_admin`; missing role configuration fails before database mutation. Retain plaintext cleanup, SHA, encryption boundary, restore-test default, production confirmation, Timescale pre/post restore, maintenance, and freshness assertions.

- [ ] **Step 2: Run contracts to verify RED**

Run: `bash deploy/backup-contract-test.sh && bash deploy/restore-contract-test.sh && bash deploy/restore-engine-contract-test.sh && bash deploy/restore-production-contract-test.sh`  
Expected: FAIL on hard-coded `-U avelren` and absent role gates.

- [ ] **Step 3: Implement operational user split**

Replace hard-coded users with strict defaults `avelren_backup` for dump and `avelren_admin` for restore. Pass credentials through the authorized Docker/host mechanism without command-line passwords and never log environment values. Keep restore target validation and production authorization unchanged.

- [ ] **Step 4: Prove actual dump and restore under restricted roles**

Update disposable integration setup to run Task 1 bootstrap and Task 2 migrations, dump as backup, restore as admin through the existing Timescale restore engine, then run schema verification and smoke. Add an explicit negative assertion that backup cannot insert a marker before dumping.

Run: `bash deploy/restore-integration-test.sh`  
Run: `bash deploy/restore-production-integration-test.sh`  
Expected: PASS; dump/restore/schema/smoke work with no legacy operational role.

- [ ] **Step 5: Commit**

```bash
git add deploy/backup.sh deploy/backup-contract-test.sh deploy/restore-engine.lib.sh deploy/restore-production.sh deploy/restore-verify.sh deploy/restore-contract-test.sh deploy/restore-engine-contract-test.sh deploy/restore-production-contract-test.sh deploy/restore-integration-test.sh deploy/restore-production-integration-test.sh
git commit -m "security: split backup and restore credentials"
```

---

### Task 6: Ownership manifest and pre-commit adoption rollback

**Files:**
- Create: `deploy/postgres-ownership.lib.sh`
- Create: `deploy/postgres-adopt.sh`
- Create: `deploy/postgres-adoption-contract-test.sh`
- Create: `deploy/postgres-adoption-integration-test.sh`

**Interfaces:**
- Consumes: admin connection, fixed legacy/admin/migrator names, exact known application-object list from migrations, and a mode-0700 evidence directory.
- Produces: `capture_manifest`, `validate_owned_object_allowlist`, `build_forward_plan`, `build_inverse_plan`, `verify_target_ownership`, and a fail-closed maintenance orchestrator.

- [ ] **Step 1: Write RED catalog/allowlist contracts**

Mock catalog TSV inputs for database, schema, extension, relations, sequences, functions/types, Timescale internal/dependent objects, and shared objects. Assert deterministic sorted manifest output; an extra legacy-owned table, extension, tablespace, or shared object must fail before `compose stop` or SQL mutation. Assert evidence directory modes 0700/0600 and no ACL/password values in console output.

- [ ] **Step 2: Write RED transaction-failure integration scenario**

On a disposable migrated DB owned by legacy, capture original owner/ACL fingerprints. Inject an error after the first ownership statement but before commit. Assert the transaction aborts and catalog fingerprints exactly match the original state.

```bash
AVELREN_ADOPTION_FAILPOINT=before_commit \
  bash deploy/postgres-adoption-integration-test.sh
assert_fingerprint_equal original after_failure
```

- [ ] **Step 3: Implement deterministic planning library**

Use catalog queries with `pg_get_userbyid`, `aclexplode`, `pg_extension`, `pg_depend`, Timescale information views, and database/shared catalogs. Plans must contain fixed quoted identifiers derived only from validated catalog rows. The inverse plan is generated from the pre-mutation manifest, parsed in a disposable transaction, and fingerprint-validated before the forward plan may run.

The controlled sequence is:

```text
validate exhaustive legacy-owned set
REASSIGN OWNED legacy TO admin
transfer allowlisted application objects admin TO migrator
restore exact target ACLs
verify DB/schema/extension admin ownership
verify application migrator ownership
verify no unexpected legacy owner
```

- [ ] **Step 4: Implement maintenance orchestrator through pre-commit gate**

Require explicit `--confirm-adoption`, exact expected commit, clean backup/recovery preflight result, stopped known clients, validated forward/inverse files, and empty unexpected-running-service list. Any failed command leaves runtime stopped. Do not include automatic production restore or optimistic restart.

- [ ] **Step 5: Run contracts and pre-commit integration GREEN**

Run: `bash deploy/postgres-adoption-contract-test.sh`  
Run: `AVELREN_ADOPTION_SCENARIO=before_commit bash deploy/postgres-adoption-integration-test.sh`  
Expected: PASS; unknown objects cause zero mutation, injected transactional failure restores the exact original fingerprint.

- [ ] **Step 6: Commit**

```bash
git add deploy/postgres-ownership.lib.sh deploy/postgres-adopt.sh deploy/postgres-adoption-contract-test.sh deploy/postgres-adoption-integration-test.sh
git commit -m "feat: add fail-closed database adoption planning"
```

---

### Task 7: Committed adoption, validated inverse rollback, and legacy retirement gate

**Files:**
- Modify: `deploy/postgres-ownership.lib.sh`
- Modify: `deploy/postgres-adopt.sh`
- Modify: `deploy/postgres-adoption-contract-test.sh`
- Modify: `deploy/postgres-adoption-integration-test.sh`

**Interfaces:**
- Consumes: Task 6 validated forward/inverse plans and fingerprints.
- Produces: post-commit failure handling, exact inverse verification, accepted-cutover marker, and guarded legacy `NOLOGIN` retirement.

- [ ] **Step 1: Write RED post-commit failure scenario**

Commit forward adoption, inject failure at each post-commit gate (`migrate`, privilege contracts, Compose switch, smoke, freshness, environment isolation), run inverse transaction, and assert the original owner/ACL fingerprint before permitting a fake old-runtime restart. Add a deliberately corrupted inverse plan and assert maintenance remains active and restart is never called.

- [ ] **Step 2: Write RED successful adoption/retirement scenario**

Assert successful forward adoption yields admin database/schema/extension owners, migrator application owners, all privilege contracts green, new runtime start only after gates, and no legacy owner. Legacy `NOLOGIN` is forbidden until backup/admin tooling proof, smoke/freshness, isolation, and accepted-soak marker are all present.

- [ ] **Step 3: Implement inverse and retirement state machine**

Persist only non-secret stage/fingerprint evidence. On any post-commit failure, keep maintenance, execute inverse in one transaction, compare exact manifest fingerprint, and only then call previous-runtime restart. If inverse SQL or comparison fails, exit nonzero with maintenance unchanged. Implement `--retire-legacy` as a separate explicit command requiring all evidence gates and performing `ALTER ROLE <legacy> NOLOGIN` plus final owner/ACL/environment verification.

- [ ] **Step 4: Run both adoption scenarios**

Run: `AVELREN_ADOPTION_SCENARIO=after_commit bash deploy/postgres-adoption-integration-test.sh`  
Run: `AVELREN_ADOPTION_SCENARIO=success bash deploy/postgres-adoption-integration-test.sh`  
Expected: PASS for exact inverse rollback, corrupted-inverse fail-closed, Timescale extension ownership, successful cutover, and guarded retirement.

- [ ] **Step 5: Commit**

```bash
git add deploy/postgres-ownership.lib.sh deploy/postgres-adopt.sh deploy/postgres-adoption-contract-test.sh deploy/postgres-adoption-integration-test.sh
git commit -m "test: prove reversible PostgreSQL adoption"
```

---

### Task 8: CI, operator documentation, and full regression

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/backend-test.sh`
- Modify: `docs/backend-testing.md`
- Modify: `docs/disaster-recovery.md`
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: all previous task commands.
- Produces: documented fresh/adoption/rollback procedures and mandatory exact-head CI gates.

- [ ] **Step 1: Add all disposable gates to CI**

Run shell syntax checks; bootstrap contracts; role privilege integration; Compose isolation; backup/restore contracts and integrations; adoption contracts; before-commit, after-commit, and success adoption integrations. Ensure every integration uses a unique Compose project, guaranteed volume cleanup, and no production `.env`.

- [ ] **Step 2: Update local backend workflow**

Keep `scripts/backend-test.sh` as the fast Ruff/migrate/pytest path, then document separate commands for the slower security/DR/adoption gates. Do not silently add production mutation or external credentials to the fast path.

- [ ] **Step 3: Document exact operational boundaries**

README documents seven credential variables and per-service Compose behavior without example passwords. DR docs specify backup role, admin restore, Timescale extension-owner evidence, maintenance/inverse rollback, and legacy retirement. State explicitly that merge does not authorize production adoption, restore, rotation, deployment, or issue closure.

- [ ] **Step 4: Run static and focused verification**

Run:

```bash
bash -n deploy/postgres-bootstrap.sh deploy/postgres-adopt.sh deploy/postgres-ownership.lib.sh
bash deploy/postgres-bootstrap-contract-test.sh
bash deploy/compose-security-contract-test.sh
bash deploy/postgres-adoption-contract-test.sh
git diff --check
```

Expected: all exit 0 and no secret-bearing output.

- [ ] **Step 5: Run full backend and security/DR integration regression**

Run:

```bash
bash scripts/backend-test.sh
bash deploy/postgres-roles-integration-test.sh
bash deploy/backup-contract-test.sh
bash deploy/restore-contract-test.sh
bash deploy/restore-engine-contract-test.sh
bash deploy/restore-production-contract-test.sh
bash deploy/restore-integration-test.sh
bash deploy/restore-production-integration-test.sh
AVELREN_ADOPTION_SCENARIO=before_commit bash deploy/postgres-adoption-integration-test.sh
AVELREN_ADOPTION_SCENARIO=after_commit bash deploy/postgres-adoption-integration-test.sh
AVELREN_ADOPTION_SCENARIO=success bash deploy/postgres-adoption-integration-test.sh
```

Expected: all exit 0; backend baseline remains green; every disposable volume is removed.

- [ ] **Step 6: Inspect repository diff for forbidden changes**

Run: `git diff --name-only main...HEAD`  
Expected: no Android behavior changes, no edited migration `001`-`009`, no `.env`, secrets, dumps, evidence manifests, or production-state artifacts.

- [ ] **Step 7: Commit final CI/docs changes**

```bash
git add .github/workflows/ci.yml scripts/backend-test.sh docs/backend-testing.md docs/disaster-recovery.md README.md .env.example
git commit -m "docs: add least-privilege rollout gates"
```

- [ ] **Step 8: Final review gate before publication**

Record exact local HEAD and test results, request an independent code/security review, and fix findings through new RED/GREEN commits. Only after review and exact-head CI may the branch be pushed and a Draft PR opened. Do not deploy, rotate credentials, mutate issue #15, mark the PR ready, merge, or close the operational gate without separate authorization.
