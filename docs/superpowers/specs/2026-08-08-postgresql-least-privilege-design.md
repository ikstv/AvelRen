# PostgreSQL Least-Privilege Design (#15)

Date: 2026-08-08  
Status: Frozen  
Scope: repository implementation and deployment procedure; no production deployment

## Goal

Replace the single PostgreSQL owner credential used by every backend service with
separate operational, migration, backup, and runtime roles. A compromised service
must be unable to perform unrelated business writes, change the schema or migration
history, manage PostgreSQL roles, or recover a more privileged credential from its
container environment.

This design preserves the existing service behavior. It does not add endpoints,
change the collector cadence, change backup retention, or authorize a production
restore or deployment.

## Roles and trust boundaries

The canonical model has seven login roles, four of which are long-running
application runtime roles:

| Role | Purpose |
|---|---|
| `avelren_admin` | Database/schema ownership, role lifecycle, extension provisioning, bootstrap and restore |
| `avelren_migrator` | Application DDL, application-object ownership, migration history and grants |
| `avelren_backup` | Daily read-only `pg_dump`; no administration, DDL, temporary objects or role membership |
| `avelren_collector` | Source observations and threshold/ETA evaluation |
| `avelren_notifier` | Ordinary notification and cancellation delivery lifecycle |
| `avelren_watchdog` | Health detection and health-notification lifecycle |
| `avelren_api` | Public API reads and endpoint-authorized device/subscription/ETA writes |

The migrator, backup, and four runtime roles are
`NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION`. No runtime or backup role is
a member of the admin or migrator role. `avelren_admin` is the controlled elevated
operational role: it has only the installation-specific privileges required for
database and role lifecycle, TimescaleDB provisioning, and restore. In the current
self-hosted PostgreSQL deployment that may include superuser capability; reducing
it further is allowed only after disposable extension and restore tests prove the
smaller capability set. The migrator credential is available only to the one-shot
`migrate` service. The admin credential is available only to operational
bootstrap/restore tooling and never to an application container.

`avelren_admin` owns the database and `public` schema. It provisions and owns the
TimescaleDB extension. `avelren_migrator` receives `USAGE, CREATE` on `public` and
owns application objects it creates; it does not own the database, schema, or
extension.

## Database and schema boundary

Bootstrap establishes an explicit deny-by-default boundary:

```sql
REVOKE ALL PRIVILEGES ON DATABASE avelren FROM PUBLIC;
GRANT CONNECT ON DATABASE avelren TO
    avelren_admin, avelren_migrator, avelren_backup,
    avelren_collector, avelren_notifier, avelren_watchdog, avelren_api;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO
    avelren_backup, avelren_collector, avelren_notifier,
    avelren_watchdog, avelren_api;
GRANT USAGE, CREATE ON SCHEMA public TO avelren_migrator;
```

Runtime and backup roles receive neither database `CREATE` nor `TEMPORARY`.
Application tables and sequences are also revoked from `PUBLIC` before explicit
grants are applied.

Default privileges are attached to the role that actually creates future objects:

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE USAGE ON TYPES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM PUBLIC;
```

The function and type revokes are global defaults: a per-schema revoke cannot
cancel the standard global `PUBLIC` default. Existing built-in and TimescaleDB
function privileges are not revoked indiscriminately. A migration that creates an
application function or type must explicitly grant only the runtime access it needs.
Future tables receive no runtime access automatically.

## Runtime permission matrix

### Collector

The collector may read and write `countries`, `checkpoints`, `observations`, and
`collector_runs`. Its derived phase may read `subscriptions`,
`subscription_state`, `alerts`, `eta_targets`, and `eta_alerts`, and perform the
current threshold/ETA lifecycle writes on those tables.

On `notification_cancels` it has `INSERT` plus `SELECT (kind, alert_id)`, solely
for the explicit `ON CONFLICT (kind, alert_id) DO NOTHING` target. It has no
`SELECT` on any other column and no `UPDATE` or `DELETE`; delivery belongs to
notifier. It receives `USAGE` on exactly:

- `alerts_id_seq`;
- `eta_alerts_id_seq`;
- `notification_cancels_id_seq`.

It has no access to `devices` or `health_alerts`.

### Notifier

Notifier may read pending `alerts` and `eta_alerts`, their `subscriptions` or
`eta_targets`, checkpoint titles, and only the required `devices.id` and
`devices.fcm_token` columns. It may update only delivery columns on `alerts` and
`eta_alerts`, and only `devices.fcm_token` for dead-token cleanup.

For `notification_cancels` it receives required `SELECT`, column-level `UPDATE`
for `attempt_count`, `last_attempt_at`, `accepted_at`, and `abandoned_at`, and
table-wide `DELETE`. PostgreSQL cannot constrain `DELETE` to particular columns or
rows; cleanup predicates remain an application invariant and are tested as such.
Notifier receives no sequence privileges and cannot access health lifecycle state
or observation writes.

### Watchdog

Watchdog may read `observations`, `collector_runs`, and `health_alerts`, plus only
`devices.id`, `devices.is_admin`, and `devices.fcm_token`. It may insert and update
only `health_alerts` and receives `USAGE` on `health_alerts_id_seq`. It cannot write
ordinary alerts, ETA state, subscriptions, devices, observations, or collector
runs, and cannot read `devices.secret_hash`.

### API

API is not database read-only. It may read the public checkpoint/history objects,
including `observations_hourly`, and the subscription/ETA state needed by current
endpoints and admin telemetry. It may perform only existing endpoint-authorized
device registration/authentication, subscription, ETA target, alert expiry/ack,
and cancellation-outbox writes.

Device privileges are column-scoped to the fields used by registration and
authentication (`id`, `fcm_token`, `platform`, `secret_hash`, `is_admin`, and
`last_seen`). Column-level `SELECT` includes columns referenced by `WHERE` clauses
and update expressions, as PostgreSQL requires.

API receives `USAGE` on exactly:

- `subscriptions_id_seq`;
- `eta_targets_id_seq`;
- `notification_cancels_id_seq`.

`devices.id` uses `gen_random_uuid()` and has no sequence.

On `notification_cancels` API has `INSERT` plus `SELECT (kind, alert_id)`, solely
for the explicit `ON CONFLICT (kind, alert_id) DO NOTHING` target. It has no
`SELECT` on any other column and no `UPDATE` or `DELETE` on that table.

### Backup

`avelren_backup` receives `CONNECT`, schema `USAGE`, and the read privileges needed
by the repository's `pg_dump --no-owner` flow on all application tables and
sequences. It receives no write, DDL, database `TEMPORARY`, role membership, or
application-container access. Daily backup must use this credential; restore uses
`avelren_admin`.

### Migrator and migration history

Migrator owns application objects and can apply DDL and update
`schema_migrations`. No runtime or backup role can insert, update, or delete
`schema_migrations`. New privilege changes use a new sequential migration; existing
migration files, including `001_init.sql`, are never edited because their SHA-256
is part of the migration contract.

## TimescaleDB contract

TimescaleDB provisioning is an admin bootstrap responsibility. Because
`001_init.sql` contains `CREATE EXTENSION IF NOT EXISTS timescaledb`, a disposable
test must prove that the existing statement succeeds under `avelren_migrator` after
admin provisioning, without granting migrator superuser or role-management rights.
If it does not, a separate compatibility/pre-migration gate must satisfy the old
migration without weakening migrator.

Extension ownership is a hard adoption gate. Evidence must include `pg_extension`
owners. Before legacy-role retirement, `timescaledb` must be owned by admin. The
production-like disposable adoption test must cover TimescaleDB hypertables,
continuous aggregates, extension ownership, backup, and restore verification.

## Container credential isolation

Backend services must not use the shared `env_file: .env`. Host configuration may
remain the source for Compose interpolation, but each service receives only its own
`DATABASE_URL` and the non-secret settings it requires. Runtime containers receive
neither admin, migrator, backup, nor sibling-service DSNs. The one-shot migrator
receives only its own DSN. Backup/restore tooling receives its operational
credential outside application containers.

Repository and integration tests inspect resolved service environments and fail if
a forbidden credential variable or DSN is present. Secrets, resolved Compose
output, passwords, and DSNs are never printed as evidence.

## Contract tests

Positive tests execute real service SQL paths under each service DSN rather than
surrogate queries:

- collector primary and derived writes;
- notifier selection, delivery updates, dead-token cleanup, cancellation delivery,
  and closed-row cleanup;
- watchdog checks and complete health lifecycle;
- API registration, authentication, subscription, ETA, history, and telemetry;
- backup dump and admin restore on a disposable database;
- migrator on clean, current, and production-like restored databases.

Negative tests prove at minimum:

```text
all runtime roles:
  CREATE ROLE / CREATE TABLE / ALTER TABLE / DROP TABLE       DENIED
  INSERT/UPDATE/DELETE schema_migrations                      DENIED
  SET ROLE admin or migrator                                  DENIED

api:
  UPDATE observations / collector_runs / health_alerts        DENIED

collector:
  any devices access / UPDATE health_alerts                   DENIED
  SELECT device_id/created_at/attempt_count or SELECT * /
  UPDATE/DELETE notification_cancels                          DENIED

notifier:
  UPDATE observations / collector_runs / health_alerts        DENIED
  SELECT devices.secret_hash / devices.is_admin                DENIED

watchdog:
  UPDATE alerts / eta_alerts / subscriptions                   DENIED
  SELECT devices.secret_hash                                   DENIED

backup:
  INSERT/UPDATE/DELETE application data / all DDL              DENIED
```

Meta-tests assert for every runtime and backup role that schema `CREATE`, database
`CREATE`, database `TEMPORARY`, and admin/migrator membership are false. A
future-object test has migrator create a disposable application table, function,
and type; runtime roles must receive no table access automatically, and `PUBLIC`
must not receive function execution or type usage. Migrator removes the test
objects afterward.

## Fresh-install rollout

Fresh bootstrap is an idempotent staged procedure, not one transaction:

```text
create roles
-> create database
-> provision extension
-> database/schema ACL
-> migrate
-> contracts
-> start runtime
```

`CREATE DATABASE` and `DROP DATABASE` cannot run inside a transaction. Each stage
therefore detects an already-correct result and is safe to retry. A failure prevents
runtime startup. Transactional rollback is used only where PostgreSQL permits it.
Explicit cleanup is allowed only when the procedure proves that the target is a new,
disposable or empty installation; it never guesses that an existing database is
safe to remove.

## Existing-database adoption

Production adoption is a separately authorized maintenance operation:

```text
encrypted backup and recovery readiness
-> exact-head and catalog preflight
-> capture owner/ACL manifest
-> generate and validate inverse plan
-> stop long-running backend services
-> create roles and provision/verify extension
-> ownership/ACL adoption transaction
-> migrate and run contracts
-> switch Compose DSNs
-> smoke, freshness and environment-isolation gates
-> accepted soak
-> retire legacy credential
```

Preflight enumerates every database, schema, extension, application, TimescaleDB,
and shared object owned by the legacy role. Unknown objects abort adoption.
Controlled `REASSIGN OWNED legacy -> admin` is allowed only after this exhaustive
allowlist passes. The procedure then explicitly transfers allowlisted application
objects from admin to migrator and verifies:

- database owner is admin;
- `public` schema owner and ACL boundary are admin-controlled;
- TimescaleDB extension owner is admin;
- all application object owners are migrator;
- no unexpected object remains owned by legacy.

The exact owner/ACL manifest also produces a validated inverse ownership/ACL plan.
Both forward and inverse operations are tested on a production-like disposable copy
before production authorization.

## Failure handling and rollback

| Failure | Required behavior |
|---|---|
| Fresh-install stage fails | Runtime never starts; completed stages are detected on retry |
| Preflight finds an unknown object/owner | Abort before maintenance mutation |
| Adoption transaction fails | Transaction rollback; verify captured original state |
| Migration or privilege contract fails after adoption commit | Keep maintenance; run tested inverse plan and verify original state before any old-runtime restart |
| New Compose, smoke, freshness, or isolation gate fails | Keep maintenance; run and verify inverse plan before restoring previous Compose and legacy DSN |
| Inverse plan fails | Keep maintenance; do not optimistically restart old runtime; require operator intervention |

The legacy role does not receive broad compatibility grants during the rollback
window. Previous Compose may restart only after the inverse transaction proves that
original ownership and ACLs were restored. Production restore is not an automatic
rollback action.

## Credential generation, rotation, and retirement

Credentials are generated independently with cryptographically secure randomness
and stored only in the authorized secret store and host configuration. They do not
enter git, logs, shell history, PR comments, resolved-Compose evidence, or chat.

Direct LOGIN roles require a short controlled service restart for password rotation.
Zero-downtime dual-credential rotation would require separate capability and login
roles and is outside #15. During an authorized rotation, the previous credential is
retained securely until the restarted service passes smoke; a failed rotation resets
the previous password before recreating the old service.

The legacy owner credential remains available only for the tested inverse rollback
window and is never injected into new containers. After accepted soak, operators:

```text
verify backup and restore tooling use backup/admin roles
-> set legacy role NOLOGIN (and revoke CONNECT where applicable)
-> remove legacy DSN from host configuration
-> recreate and inspect runtime containers
-> verify no legacy/admin/migrator/backup secret is exposed
```

Issue #15 is not operationally complete until this retirement gate passes.

## Non-secret evidence

The deployment record contains only:

```text
exact_commit
bootstrap_or_adoption_script_version
forward_and_inverse_plan_test_result
database_schema_extension_owners
application_object_owner_audit
positive_contract_result
negative_contract_result
future_object_isolation_result
backup_and_disposable_restore_result
container_environment_isolation_result
migration_result
service_smoke_result
collector_freshness
legacy_credential_retired
reviewer
```

No password, DSN, environment dump, token, database dump, or secret-bearing
screenshot belongs in evidence.

## Completion gates

Repository completion requires implementation, tests, documentation, and exact-head
CI. Operational completion additionally requires authorized production adoption,
backup/restore proof, smoke/freshness, environment isolation, accepted soak, and
legacy credential retirement. Merge does not authorize deployment or close the
operational gate automatically.
