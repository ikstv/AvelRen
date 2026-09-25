# Sanitised deployment evidence format

This is the input contract for `ops/deployment-preflight.py`. It is a record of
read-only observations, not a host script and not a deployment manifest. Keep
the JSON outside Git if it identifies a host; never put a DSN, password, token,
private key or `.env` value in it.

```json
{
  "format_version": 1,
  "captured_at": "YYYY-MM-DDTHH:MM:SSZ",
  "target_commit": "40 lowercase hex characters",
  "server_checkout": {
    "clean": true,
    "commit": "same target commit",
    "migration_files": {"001_init": "sha256 of the host file"}
  },
  "database_journal": {"001_init": "sha256 from schema_migrations"},
  "candidate_images": {
    "api": {"source_commit": "same target commit", "image_digest": "sha256:..."},
    "collector": {"source_commit": "same target commit", "image_digest": "sha256:..."},
    "notifier": {"source_commit": "same target commit", "image_digest": "sha256:..."},
    "watchdog": {"source_commit": "same target commit", "image_digest": "sha256:..."}
  },
  "live_runtime": {
    "api": {"image_digest": "sha256:..."},
    "collector": {"image_digest": "sha256:..."},
    "notifier": {"image_digest": "sha256:..."},
    "watchdog": {"image_digest": "sha256:..."}
  },
  "checks": {
    "backup_verified": true,
    "health_verified": true,
    "schema_verified": true
  },
  "schema_verification": {
    "verifier": "avelren.schema_verify",
    "read_only_session": true,
    "exit_code": 0,
    "migrations": {"001_init": "sha256 of the migration checked"}
  }
}
```

`candidate_images` prove what is proposed for deployment. `live_runtime` is
only the pre-deployment baseline, so it may legitimately be older.

`schema_verification` is the proof behind `checks.schema_verified`: it records
that the source's independent physical verifier (`avelren.schema_verify`) ran
successfully against the exact source migration set in a database session
enforced as read-only. It deliberately records neither a host identity nor a
DSN. A missing, unverified or malformed field fails the preflight.

The capture itself must be performed only after an explicit read-only
production authorisation; a successful preflight is still not authorisation to
run a deployment.
