# Production Restore Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Додати окремий fail-closed production restore path, який до maintenance перевіряє artifact, production identity, migration/role evidence і verified safety snapshot, а після restore відкриває ingress лише після health gates.

**Architecture:** Публічний `ops/restore.sh` залишається тільки для `restore_test`; новий internal-only orchestrator складає вузькі source-only gates і production wrapper над спільною Timescale primitive. Усі destructive boundaries спершу доводяться fake-command contract tests та випадково названим Docker Compose integration test.

**Tech Stack:** Bash 5, Python 3.14 standard library, PostgreSQL/TimescaleDB, Docker Compose, pytest/JUnit для чинних API/Android контрактів, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-28-production-restore-gate-design.md`

## Global Constraints

- Не редагувати жодну застосовану migration; journal і SHA-256 тільки перевіряються.
- `ops/restore.sh` ніколи не приймає production target; новий production entrypoint окремий і manual-only.
- Немає default/latest commit, backup, migration pin або role model.
- DSN, password, rclone key, FCM token і environment dump не потрапляють у Git, argv або логи.
- Snapshot failure, remote read-back failure або digest mismatch завжди блокують maintenance.
- Ordinary maintenance без restart має максимум `21600` секунд; planned reboot з `restarts_at`/`boot_id` — максимум `900` секунд.
- До maintenance будь-яка помилка не має runtime side effects; після maintenance помилка не відкриває ingress автоматично.
- Production server-side preflight, deployment і restore кожен потребують нового явного GO власника.
- Collector не звертається до upstream частіше ніж раз на 60 секунд; restore тести взагалі не звертаються до upstream.

## Review Focus

- Artifact замінено між preflight і `dropdb`: повторна SHA/stat перевірка перед restore відмовляє до destructive DB command; тест у Task 6.
- Ordinary 6-hour maintenance випадково містить restart fields: backend і Android відхиляють його; тести у Task 1.
- Backup remote verified, але receipt не записався атомарно або лишився після failure: orchestrator не переходить до maintenance; тест у Task 3.
- Невідома DB session з'явилась після початкового preflight: повторний session gate після stop блокує restore; тест у Task 6.
- SIGINT/TERM після початку maintenance: ingress лишається закритим, maintenance не очищається, recovery summary не містить секретів; тест у Task 6.

---

### Task 1: Довге ordinary maintenance без неправдивого reboot

**Files:**
- Modify: `services/backend/src/avelren/maintenance.py`
- Modify: `services/backend/tests/unit/test_maintenance.py`
- Modify: `apps/android/app/src/main/java/ua/avelren/app/data/ServerStatus.kt`
- Modify: `apps/android/app/src/test/java/ua/avelren/app/data/ServerStatusTest.kt`
- Create: `ops/maintenance-works.sh`
- Create: `ops/maintenance-works-contract-test.sh`

**Interfaces:**
- Backend `read_window(now: datetime) -> dict[str, str] | None`: two-field ordinary window accepts duration `1..21600`; restart window accepts `1..900` and still requires valid `restarts_at` plus current `boot_id`.
- Android `MaintenanceWindow.bounds(now: Instant)`: same conditional limits.
- `ops/maintenance-works.sh --duration-seconds N`: root-only publisher for `120..21600`; writes only `starts_at` and `ends_at`, confirms `/api/status`, then waits 60 seconds before returning.

- [ ] **Step 1: Write failing backend and Android tests**

  Add cases asserting ordinary `21600` is valid, `21601` is invalid, restart `901` is invalid, and a `21600` payload with restart fields is invalid. Assert Android resolves a valid long ordinary window to `MAINTENANCE`, never `RESTARTING`.

- [ ] **Step 2: Run the focused tests and verify failure**

  Run backend: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_maintenance.py -q`.
  Run Android from `apps/android`: `bash gradlew :app:testDebugUnitTest --tests ua.avelren.app.data.ServerStatusTest --no-daemon --max-workers=2`.
  Expected: new 6-hour cases FAIL under the current 900-second bound.

- [ ] **Step 3: Implement conditional duration validation**

  Introduce exact constants `MAX_ORDINARY_SECONDS = 21600` and `MAX_RESTART_SECONDS = 900` in Python, and matching private constants in Kotlin. Select the limit only after determining whether both restart fields are present; one restart field without the other remains invalid.

- [ ] **Step 4: Write the failing publisher contract**

  Test root gate, `119/21601/non-numeric` duration rejection, exact two-key JSON, `0644` atomic output, API confirmation, 60-second wait through a fake `sleep`, cleanup on failed confirmation, and absence of `restarts_at`/`boot_id` in file and response.

- [ ] **Step 5: Implement and verify the publisher**

  Implement `maintenance-works.sh` with `umask`, temp-file + `mv`, exact response parsing through Python stdlib, and fakeable commands through `PATH`. Run `bash ops/maintenance-works-contract-test.sh`; expected final count PASS. Re-run backend and Android focused tests; expected PASS.

- [ ] **Step 6: Commit**

  `git commit -m "feat(status): підтримати довгі технічні роботи без reboot"`

### Task 2: Static recovery evidence validator

**Files:**
- Create: `ops/restore-role-pin.py`
- Create: `ops/restore-role-pin-contract-test.py`

**Interfaces:**
- `validate_evidence(record_path: Path, source_root: Path, dump_sha256: str) -> dict[str, object]` returns the validated record or raises `EvidenceError`.
- CLI: `python3 ops/restore-role-pin.py verify --record PATH --source-root PATH --dump-sha256 64HEX`; success prints only `production restore evidence verified`.
- Required JSON keys are exactly `target_commit`, `recovery_migration_pin`, `database_journal`, `role_model`, `roles`, `role_memberships`, `ownership_and_grants_verified`, `backup_sha256`.

- [ ] **Step 1: Write failing validator tests**

  Cover valid synthetic migrations; unknown/extra key; malformed/non-lowercase commit; `latest` pin; pin absent from journal/tree; missing, extra, reordered or non-contiguous migration journal; SHA mismatch; backup digest mismatch; missing expected role; runtime superuser; unexpected direct membership; false ownership flag; symlinked migration outside source root. Assert diagnostics name only the rejected field/category and never record values.

- [ ] **Step 2: Run and verify failure**

  Run `python3 ops/restore-role-pin-contract-test.py`.
  Expected: FAIL because `restore-role-pin.py` does not exist.

- [ ] **Step 3: Implement the minimal stdlib validator**

  Use `json`, `hashlib`, `pathlib` and strict type/key checks. Enumerate `db/migrations/[0-9][0-9][0-9]_*.sql` in lexical order through resolved paths inside `source_root`; compare every journal entry through the explicit pin. Do not shell out or read environment secrets.

- [ ] **Step 4: Verify and commit**

  Run `python3 ops/restore-role-pin-contract-test.py`; expected all cases PASS. Run `python3 -m py_compile ops/restore-role-pin.py ops/restore-role-pin-contract-test.py`.
  Commit: `feat(restore): перевіряти recovery pin і role evidence`.

### Task 3: Atomic receipt for the mandatory safety snapshot

**Files:**
- Modify: `ops/backup.sh`
- Modify: `ops/backup-contract-test.sh`

**Interfaces:**
- Optional `AVELREN_BACKUP_RECEIPT=/root-owned/path.json` requests an atomic `0600` JSON receipt after remote dump, sidecar, digest and size all verify.
- Receipt keys are exactly `created_at`, `remote_artifact`, `remote_sidecar`, `sha256`, `bytes`; it contains no local plaintext path, config path or credentials.

- [ ] **Step 1: Extend backup contract with failing receipt cases**

  Assert receipt is absent for dump/upload/read-back/digest/size/rotation failure; valid success receipt is mode `0600`, parses as exact JSON, names the just-created remote pair and digest, and is written via same-directory temp + atomic rename. Seed an old receipt and assert a failed run cannot leave it looking fresh.

- [ ] **Step 2: Run and verify failure**

  Run `bash ops/backup-contract-test.sh`; expected FAIL on missing receipt behavior.

- [ ] **Step 3: Implement receipt publication**

  Validate receipt parent exists, is root-owned in production mode, and is not inside the plaintext work directory. Remove/stale-mark any requested receipt before dump. Publish JSON only after remote verification and retention success; extend cleanup trap for receipt temp only, never delete a completed receipt.

- [ ] **Step 4: Verify and commit**

  Run `bash -n ops/backup.sh ops/backup-contract-test.sh` and `bash ops/backup-contract-test.sh`; expected PASS.
  Commit: `feat(backup): видавати verified snapshot receipt`.

### Task 4: Read-only production preflight composition

**Files:**
- Create: `ops/restore-production-preflight.lib.sh`
- Create: `ops/restore-production-preflight-contract-test.sh`

**Interfaces:**
- `avelren_verify_production_preflight DUMP SIDECAR EVIDENCE SOURCE_ROOT` composes artifact verification, canonical Compose identity, static evidence validation and live read-only PostgreSQL assertions.
- Requires `AVELREN_ADMIN_PASSWORD` through environment and exact admin role `avelren_admin`; never prints either.
- On success exports only sanitised shell variables: `AVELREN_VERIFIED_TARGET_COMMIT`, `AVELREN_VERIFIED_MIGRATION_PIN`, `AVELREN_VERIFIED_ARTIFACT_SHA`.

- [ ] **Step 1: Write failing fake-command contract tests**

  Test ordering: artifact → Compose identity → static evidence → DB identity/roles/grants → session inventory. For each stage force failure and assert no later command occurs. Verify DSN/password are environment-only, expected database is exactly `avelren`, role assertions execute inside SQL without dumping `pg_roles`, and unknown active sessions reject.

- [ ] **Step 2: Add Review Focus live-state tests**

  Cover extra runtime superuser, unexpected membership/owner/grant, journal hash mismatch against live `schema_migrations`, wrong `current_database()`, and newline/command-like data in fake output. Expected: fail closed with category-only diagnostic.

- [ ] **Step 3: Run and verify failure**

  Run `bash ops/restore-production-preflight-contract-test.sh`; expected FAIL because the library does not exist.

- [ ] **Step 4: Implement the source-only gate**

  Source existing artifact and identity libraries; call the Python validator with fixed option names. Execute SQL assertions with `psql -v ON_ERROR_STOP=1` inside the canonical DB container. The function may read exact boolean/count results only; it must not parse or log arbitrary role rows.

- [ ] **Step 5: Verify and commit**

  Run `bash -n ops/restore-production-preflight.lib.sh ops/restore-production-preflight-contract-test.sh`, then the contract test; expected PASS.
  Commit: `feat(restore): додати production read-only preflight`.

### Task 5: Separate production wrapper over the shared Timescale primitive

**Files:**
- Modify: `ops/restore-engine.lib.sh`
- Modify: `ops/restore-engine-contract-test.sh`
- Create: `ops/restore-production-engine.lib.sh`
- Create: `ops/restore-production-engine-contract-test.sh`
- Modify: `ops/restore-allowlist-contract-test.py`

**Interfaces:**
- `_avelren_restore_engine_primitive DUMP TARGET STACK_DIR COMPOSE_FILE COMPOSE_PROJECT DB_SERVICE` contains the existing Timescale restore implementation.
- Existing `avelren_restore_engine` remains public-to-source callers and accepts only `restore_test`.
- New `avelren_restore_production_engine DUMP STACK_DIR COMPOSE_FILE COMPOSE_PROJECT DB_SERVICE` hardcodes target `avelren`; no target parameter exists.

- [ ] **Step 1: Add failing boundary tests**

  Preserve every existing restore_test assertion. Add production wrapper tests proving exact target, admin role, pre/post hook order, post hook attempted after import failure, primary error preserved, relation allowlist and owner handoff. Assert `ops/restore.sh --target avelren` still fails before Docker.

- [ ] **Step 2: Run and verify failure**

  Run `bash ops/restore-engine-contract-test.sh`, `bash ops/restore-production-engine-contract-test.sh`, `python3 ops/restore-allowlist-contract-test.py`; expected new production test FAIL only.

- [ ] **Step 3: Extract without changing restore_test behavior**

  Move the existing body behind `_avelren_restore_engine_primitive`; keep validation for `restore_test` in `avelren_restore_engine`. Implement the production wrapper in its own source-only file with no executable mode and no arbitrary target argument.

- [ ] **Step 4: Verify and commit**

  Run both engine contract tests, public restore contract and allowlist test; expected PASS, including unchanged `restore contract tests: 15 passed` or an explicitly increased count.
  Commit: `refactor(restore): відокремити production Timescale wrapper`.

### Task 6: Manual fail-closed production orchestrator

**Files:**
- Create: `ops/restore-production.sh`
- Create: `ops/restore-production-contract-test.sh`
- Modify: `ops/RECOVERY.md`

**Interfaces:**
- CLI: `sudo /usr/local/sbin/avelren-restore-production --artifact PATH --sidecar PATH --evidence PATH`.
- `avelren_confirm_production_restore INPUT_FD` reads exact `RESTORE avelren YYYY-MM-DD`; entrypoint always passes `/dev/tty` and UTC host date.
- Fixed production identity: stack `/opt/avelren`, project `avelren`, service `db`, database `avelren`; no overrides in production entrypoint.

- [ ] **Step 1: Write the failing orchestration contract**

  With fake commands assert exact sequence: root/TTY/confirmation → preflight → safety backup receipt → ordinary maintenance publish → stop Caddy and DB clients → repeat session gate → repeat artifact SHA/stat gate → production engine → post-restore schema/role/API/collector/Caddy config gates → start Caddy → external health → remove maintenance.

- [ ] **Step 2: Add every failure boundary**

  Before maintenance, each failure leaves services untouched. After maintenance, dump replacement (inode/size/digest), new unknown DB session, engine failure, post hook failure, schema/API/collector failure, external health failure, SIGINT and SIGTERM all leave or re-stop Caddy, retain maintenance, return non-zero and print a sanitised recovery summary. Assert no secret sentinel appears in log or fake argv.

- [ ] **Step 3: Run and verify failure**

  Run `bash ops/restore-production-contract-test.sh`; expected FAIL because the entrypoint does not exist.

- [ ] **Step 4: Implement minimal state-machine orchestration**

  Use explicit phases `preflight`, `snapshot_verified`, `maintenance`, `restored`, `healthy`, `complete`. Trap signals and EXIT; cleanup may remove temp files but removes maintenance only in `complete`. Capture artifact canonical path, device, inode, size and digest at preflight; recheck all immediately before engine call.

- [ ] **Step 5: Implement recovery summary and success cleanup**

  Summary contains phase, stopped service names, verified snapshot receipt path and `ops/RECOVERY.md` section name only. On success, remove maintenance atomically after external health and record the exact target commit/pin/digest without credentials.

- [ ] **Step 6: Verify and commit**

  Run `bash -n ops/restore-production.sh ops/restore-production-contract-test.sh` and the contract test; expected all cases PASS.
  Commit: `feat(restore): додати manual production orchestrator`.

### Task 7: Isolated integration, CI and readiness evidence

**Files:**
- Modify: `ops/restore-integration-test.sh`
- Modify: `.github/workflows/database.yml`
- Modify: `docs/PRODUCTION-RESTORE-GAP-MATRIX.md`
- Modify: `docs/RELEASE-READINESS.md`

**Interfaces:**
- Integration test uses a random Compose project and test-only database target through `_avelren_restore_engine_primitive`; it never calls `restore-production.sh` against a real/canonical identity.
- Database workflow runs every new Python/shell contract, syntax check and integration rehearsal.

- [ ] **Step 1: Extend the Docker rehearsal**

  Add synthetic evidence/sidecar and verify restore, Timescale hooks, migration journal SHA, owners/grants, API/schema smoke, active-session refusal and post-restore failure preservation. Add an assertion that no container, volume, network, path or project equals canonical production identifiers.

- [ ] **Step 2: Run the isolated integration test**

  Run `bash ops/restore-integration-test.sh`; expected PASS and cleanup of only the random project resources.

- [ ] **Step 3: Wire every gate into CI**

  Add new shell files to `bash -n`; run `restore-role-pin-contract-test.py`, maintenance works, production preflight, production engine and production orchestrator contracts before integration. Keep the existing `restore_test`, backup, DB and 60-second collector tests unchanged.

- [ ] **Step 4: Run the complete verification matrix**

  Run:
  `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q`;
  `bash ops/backup-contract-test.sh`;
  every restore/maintenance contract named in the workflow;
  `bash ops/restore-integration-test.sh`;
  `bash scripts/test_database.sh`;
  Android `ServerStatusTest` and compile;
  `git diff --check`.
  Expected: all PASS; no production host connection and no upstream request.

- [ ] **Step 5: Update evidence without claiming deployment**

  Mark source implementation and isolated rehearsal complete, but leave server-side preflight, deployment, real-backup staging rehearsal and production capability unaccepted. Document the three future explicit GO gates from the spec.

- [ ] **Step 6: Commit and prepare review**

  Commit: `test(restore): перевірити production-shaped recovery flow`.
  Open a PR with exact CI results, threat boundaries and rollback/runbook review points; do not deploy or run server-side preflight.
