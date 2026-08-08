# Restore procedure

The default low-level restore target is the disposable `restore_test` database.
Production restore is destructive and is allowed only through
`deploy/restore-production.sh`; never invoke the low-level engine directly as
an operational production procedure.

## Disposable verification

```bash
avelren-restore backup.sql.gz --target restore_test
deploy/restore-verify.sh restore_test
```

The engine validates the target, exact production confirmation (when relevant),
artifact existence, and gzip integrity before destructive work. Once
`timescaledb_pre_restore()` succeeds, every failing exit attempts
`timescaledb_post_restore()` without masking the primary restore status.

## Production entrypoint

```bash
deploy/restore-production.sh backup.sql.gz \
  --confirm-production-restore AVELREN-PRODUCTION-RESTORE
```

The orchestrator stops public ingress first, stops all known PostgreSQL clients,
and aborts if unknown target sessions remain. It then invokes the restore
engine, verifies migration history and physical schema, executes a GET-only
application smoke, restarts services in a controlled order, and validates the
canonical HTTPS endpoint and a fresh collector observation.

On any failure, application DB clients and ingress remain stopped. The operator
must diagnose and explicitly resume; there is no optimistic restart.

CI runs this flow only against isolated disposable databases and fake service
boundaries. It never performs a live production restore.

See [disaster-recovery.md](disaster-recovery.md) for the full operator runbook
and [backup-key-escrow.md](backup-key-escrow.md) for the external key evidence
gate.
