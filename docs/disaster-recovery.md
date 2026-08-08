# Disaster recovery runbook

## Prerequisites

- Authorized operator access to the production host and external backup vault.
- The exact `AVELREN-PRODUCTION-RESTORE` confirmation phrase.
- A selected encrypted backup and its encrypted SHA-256 sidecar.
- Independently verified access to the off-host rclone crypt recovery material.
- A declared maintenance window and an operator communication channel.

No RTO or RPO is asserted here; neither has been approved.

## Backup selection and integrity

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

## Key escrow evidence

Complete the external evidence procedure in `docs/backup-key-escrow.md`. A
repository test proves safeguards and disposable restore behavior only; it does
not prove that real recovery material exists outside the server.
