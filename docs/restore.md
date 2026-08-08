# Restore procedure

The public low-level restore target is exclusively the disposable `restore_test`
database. Its source-only engine has no executable production CLI. Production
restore is destructive and is allowed only through
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
engine, runs the migrate gate before exact schema verification (so retained
backups may contain an older contiguous migration prefix), executes a GET-only
application smoke, restarts services in a controlled order, and validates the
canonical `/api/health` JSON endpoint plus a new successful collector run with
rows written after the pre-restore watermark.

On any failure, application DB clients and ingress remain stopped. The operator
must diagnose and explicitly resume; there is no optimistic restart.

CI runs this flow only against isolated disposable databases and fake service
boundaries. It never performs a live production restore.

See [disaster-recovery.md](disaster-recovery.md) for the full operator runbook
and [backup-key-escrow.md](backup-key-escrow.md) for the external key evidence
gate.
