# Off-host rclone crypt key escrow

## Recovery material

Recovery requires the non-secret remote definition plus the secret rclone crypt
parameters used by `gdrive-crypt`: `password` and, when configured,
`password2`/salt. The underlying cloud remote authorization must also be
recoverable. Obscured values from `rclone.conf` are still secrets.

## Storage contract

Store the recovery material outside the production server in an approved
encrypted organizational vault. Access must be possible through two independent
authorized recovery paths (for example, two separately controlled vault
custodians). Do not commit, attach, screenshot, base64-encode, or paste key
material into this repository, GitHub issues, CI, or ordinary chat.

## Recovery exercise

At least on the organization-approved DR exercise cadence:

1. Start from a disposable host that does not read the production server's
   rclone configuration.
2. Obtain recovery material through the documented external process.
3. Configure an ephemeral rclone crypt remote.
4. Download one encrypted backup and sidecar.
5. Verify SHA-256, size, and `gzip -t`.
6. Restore into disposable `restore_test` and run schema/application checks.
7. Destroy the ephemeral configuration and plaintext artifact.

## Non-secret evidence record

Store evidence in the approved operational system, not necessarily in git. A
record is sufficient only if it contains no secret and includes:

```text
exercise_date_utc
operators
external_vault_reference_id
independent_access_paths_verified
backup_reference
sha256_and_gzip_verified
disposable_restore_result
evidence_reviewer
next_review_date
```

CI must not generate this record or mark escrow complete. Issue #14 remains
operationally open until a real authorized evidence record is reviewed. As of
this repository change, real off-host escrow is **not externally verified**.
