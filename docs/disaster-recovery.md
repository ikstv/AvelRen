# Disaster recovery runbook

## Operational authorization boundary

> **WARNING: merge of PR #29 DOES NOT authorize production operations.**

Merge of PR #29 does not authorize `production adoption`, `production restore`,
`deployment`, `credential generation`, `credential rotation`, `legacy NOLOGIN`,
`legacy REVOKE CONNECT`, or closure of issue #15. Production adoption requires
separate explicit authorization. Issue #15 remains **OPEN even after merge**
until production rollout and legacy retirement are separately executed and
proven. This runbook documents safety contracts; it is not that authorization.

## PostgreSQL recovery identities

- `avelren_backup` is the dump-only identity. `deploy/backup.sh` fixes
  `AVELREN_BACKUP_DB_USER` to that role and uses `pg_dump --no-owner`; it has no
  restore, write, DDL, or runtime-container capability.
- `avelren_admin` is the bootstrap/adoption/restore identity. Production restore
  verifies both `AVELREN_ADMIN_DSN` and current user before mutation.
- `avelren_migrator` performs migrations plus schema/catalog verification after
  restore. Runtime identities never perform either operation.
- TimescaleDB extension, database, and `public` schema ownership must verify as
  `avelren_admin`; application object ownership must verify as
  `avelren_migrator`.

No password, DSN, token, resolved environment, decrypted dump, or credential
value belongs in this file, Git, CI output, PR comments, or evidence.

## Pre-adoption recovery (single-role production)

Everything above assumes the post-adoption role model. Until the least-privilege
rollout completes (issue #15, stages 3B.1–3F), production is still a **single
`avelren` SUPERUSER** that owns the database, the TimescaleDB extension, and all
objects. In that state the restore engine (`restore.sh` / `restore-engine.lib.sh`)
**does not apply** — by design it requires `avelren_admin` and verifies extension
ownership as `avelren_admin` (contract-enforced). This is not a bug; it is the
adoption-era guard.

If production must be recovered before adoption completes, use a plain,
timescale-aware manual restore under the legacy `avelren` superuser into a
disposable target first (never over the live database blind):

1. Pull and decrypt the chosen backup off-host (`rclone copy` from the crypt
   remote decrypts automatically); verify `gzip -t`.
2. `createdb` a disposable target; `CREATE EXTENSION IF NOT EXISTS timescaledb`.
3. **`SELECT timescaledb_pre_restore();`** — required, or hypertable/chunk
   foreign keys fail mid-load (`observations is not a hypertable`).
4. Load the dump (`zcat dump | psql -d <target>`).
5. **`SELECT timescaledb_post_restore();`** — re-registers chunks.
6. Verify row counts, `max(version)` in `schema_migrations`, and table set.

Steps 3 and 5 are the difference between a clean restore and a stuck one; a
manual `psql` load without them leaves the hypertable half-registered. This
manual path retires the moment adoption completes — after 3B the standard
engine flow above is the DR path, and this section becomes historical.

## Prerequisites

- Authorized operator access to the production host and external backup vault.
- The exact `AVELREN-PRODUCTION-RESTORE` confirmation phrase.
- A selected encrypted backup and its encrypted SHA-256 sidecar.
- Independently verified access to the off-host rclone crypt recovery material.
- A declared maintenance window and an operator communication channel.

No RTO or RPO is asserted here; neither has been approved.

## Backup selection and integrity

> Restore rehearsal on an isolated bench — `docs/restore-rehearsal.md`
> (performed on a production artifact 2026-08-17).

1. Select the intended daily, weekly, or monthly artifact.
2. Retrieve it through the configured `gdrive-crypt` remote.
3. Retrieve and compare its `.sha256` sidecar.
4. Check encrypted-remote object presence and decrypted size.
5. Run `gzip -t` after download.

An encrypted remote existing is not proof that its decryption key is recoverable.

## Maintenance entry and service quiesce

Use only `deploy/restore-production.sh`. It blocks ingress by stopping Caddy
before stopping `api`, `collector`, `notifier`, and `watchdog`. The script then
verifies that these services are not running.

The exact production restore CLI is retained only as an interface reference,
not an authorization:

```bash
bash deploy/restore-production.sh <local-gzip-artifact> --confirm-production-restore AVELREN-PRODUCTION-RESTORE
```

The public low-level CLI is fail-closed to the disposable target:

```bash
bash deploy/restore.sh <local-gzip-artifact> --target restore_test
```

It rejects every production target; production restore must go through the
orchestrator above after separate authorization.

## Session verification

The orchestrator queries `pg_stat_activity` after known clients are stopped.
Any remaining target session is treated as unknown and aborts the operation
before `DROP DATABASE`. It reports only safe connection metadata. It does not
use `DROP DATABASE ... WITH (FORCE)` or automatically terminate unknown sessions.

## Restore

The low-level engine recreates the target, enables TimescaleDB, calls
`timescaledb_pre_restore()`, restores SQL, and calls
`timescaledb_post_restore()`. If SQL restore fails after pre-restore, the
post-restore cleanup is still attempted and reported separately; the original
failure remains the process result.

## Failure behavior

Any restore, cleanup, schema, application-smoke, restart, HTTPS, or freshness
failure leaves ingress and known DB clients stopped. Do not manually reopen
traffic until the cause is understood and all verification gates pass.

## Post-restore verification

Production verification is available only with the internal context supplied by
the orchestrator. It is read-only and checks:

- exact migration history and checksums;
- critical tables, columns, constraints, indexes, hypertables, and aggregates;
- actual production target identity;
- GET `/health` and GET `/checkpoints?include_stale=true`;
- presence of restored observations.

The general migration process is not used to repair an unverified physical
restore.

## Controlled restart and maintenance exit

After verification, the orchestrator completes the migrate gate, starts the DB
clients, starts Caddy last, checks the canonical HTTPS health endpoint, and
waits for a fresh observation. Only then is the operation successful.

## Rollback and escalation

There is no automatic rollback to a partially overwritten database. Keep the
maintenance barrier closed, preserve logs that contain no secrets, select a
known-good artifact, and escalate to the designated database operator. Never
paste database credentials, rclone configuration, crypt passwords, salts, or
decrypted dumps into GitHub or CI logs.

## Existing-database adoption contract

### Current execution boundary

`deploy/postgres-adopt.sh` currently enforces a disposable-only execution
boundary: `AVELREN_TEST_DB=1` is required and `AVELREN_TARGET_DB` must contain
`test` or `ci`. Committed adoption and retirement paths are therefore test
evidence, not a production mutation interface. Never remove or bypass these
guards. A future production adoption still requires separate explicit
authorization and a reviewed production-capable interface.

The exact implemented CLI shape, usable only within that approved disposable
boundary, is:

```bash
bash deploy/postgres-adopt.sh --confirm-adoption AVELREN-POSTGRES-ADOPTION
```

The script reads operator inputs from named environment variables, including
`AVELREN_TARGET_DB`, `AVELREN_ADMIN_DSN`, `AVELREN_EXPECTED_COMMIT`,
`AVELREN_RECOVERY_PREFLIGHT_FILE`, `AVELREN_EVIDENCE_DIR`, and, for committed
test paths, `AVELREN_ADOPTION_SUCCESS_GATE_RUNNER`. Values must come from the
authorized environment and must not be placed on the command line or in
evidence.

### Preflight and pre-mutation evidence

Before mutation, the script proves the exact repository HEAD, a clean worktree,
an admin-authenticated connection, protected evidence paths, recovery readiness,
and a catalog ownership allowlist. `AVELREN_RECOVERY_PREFLIGHT_FILE` must be a
regular non-symlink owned by the operator, mode `0400` or `0600`, with exactly:

```text
status=PASS
backup_recovery=PASS
exact_commit=<same 40-character lowercase hexadecimal commit>
```

`AVELREN_EVIDENCE_DIR` is protected mode `0700`; evidence files are mode `0600`.
The script captures the pre-mutation manifest as `original.tsv`, validates the
allowlist, generates `forward.sql` and `inverse.sql`, and proves their parse and
round-trip against `after-plan-validation.tsv` before mutation. The plans are
derived from validated catalog rows; operators do not hand-edit either plan.
Unknown ownership, an unexpected running service, a malformed plan, or a
fingerprint mismatch aborts before the maintenance mutation boundary.

### Maintenance and rollback state machine

Maintenance stops and verifies stopped `caddy`, `api`, `collector`, `notifier`,
and `watchdog`; only `db` may remain running. Runtime remains stopped on every
unverified path.

- `before_commit` executes the forward plan inside a transaction, rolls it back,
  and verifies the exact original manifest fingerprint before exit.
- A failure after committed forward adoption runs the validated `inverse rollback`
  in one transaction and compares the exact original fingerprint. `Previous runtime`
  may restart only after that proof.
- A corrupt or incomplete inverse plan is fail-closed: maintenance stays active,
  old runtime is not restarted, and manual intervention is required.
- Production restore is never an automatic adoption rollback action.

After commit, the success runner must pass the implemented gates in order:
`migrate`, `privilege_contracts`, `compose_credential_switch`, `smoke`,
`collector_freshness`, and `environment_isolation`. A successful cutover writes
the protected `stage` evidence with exactly these fields:

```text
exact_commit=<same exact commit>
stage=cutover_complete
original_fingerprint=<64-character lowercase hexadecimal fingerprint>
target_fingerprint=<64-character lowercase hexadecimal fingerprint>
inverse_verified=NOT_RUN
privilege_contract_result=PASS
environment_isolation_result=PASS
smoke_result=PASS
freshness_result=PASS
accepted_cutover=PASS
```

The committed target marker is `committed-forward.marker` containing only
`FORWARD_TARGET_VERIFIED`. Evidence must contain no credential material.

### Accepted soak and legacy retirement

Legacy retirement is a separate invocation and is forbidden until all cutover
evidence exists, current ownership matches the accepted target, backup/admin
tooling is proven, and an externally accepted soak marker is supplied through
`AVELREN_ACCEPTED_SOAK_FILE`. That protected file has exactly four lines:

```text
accepted_soak=PASS
exact_commit=<same exact commit>
target_fingerprint=<same target fingerprint as cutover stage>
accepted_at_epoch=<current Unix epoch>
```

The script rejects a future timestamp or a marker older than `86400` seconds.
Creating the marker is an external authorized decision; the script does not
invent acceptance.

Within the disposable-only boundary, the exact retirement CLI is:

```bash
bash deploy/postgres-adopt.sh --confirm-adoption AVELREN-POSTGRES-ADOPTION --retire-legacy
```

It also requires `AVELREN_RETIREMENT_GATE_RUNNER`. The transaction applies
`ALTER ROLE "avelren" NOLOGIN`, verifies the database value
`rolcanlogin = false`, rechecks owner/ACL fingerprints, reruns privilege and
environment-isolation gates, and only then publishes `legacy-retirement`
evidence. This is the verified legacy NOLOGIN gate.

The implemented retirement command does **not** perform `REVOKE CONNECT`.
Any legacy REVOKE CONNECT operation is a separate production change requiring
its own explicit authorization; neither successful tests nor merge authorize it.

## Key escrow evidence

Complete the external evidence procedure in `docs/backup-key-escrow.md`. A
repository test proves safeguards and disposable restore behavior only; it does
not prove that real recovery material exists outside the server.
