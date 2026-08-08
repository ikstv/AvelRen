# Restore procedure

The default restore target is the disposable `restore_test` database. A
production restore is never enabled by a timeout or an interactive prompt.

Before any database is dropped or created, `deploy/restore.sh` requires:

1. an explicit target;
2. the exact production confirmation token;
3. an existing backup artifact;
4. successful gzip integrity validation.

The production contract is:

```bash
avelren-restore backup.sql.gz \
  --target avelren \
  --confirm-production-restore AVELREN-PRODUCTION-RESTORE
```

To test the full pre-destructive contract without touching a database:

```bash
avelren-restore backup.sql.gz \
  --target avelren \
  --confirm-production-restore AVELREN-PRODUCTION-RESTORE \
  --dry-run
```

Normal development verification uses the disposable target:

```bash
avelren-restore backup.sql.gz --target restore_test
deploy/restore-verify.sh restore_test
```

The restore order is confirmation, target validation, backup validation,
integrity check, restore, then schema and application verification. Production
restore is never executed by CI.
