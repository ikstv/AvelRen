# Source-only deployment preflight

`ops/deployment-preflight.py` is an **offline evidence gate**, not a deploy
tool. It never connects to a server, invokes Docker/Compose, reads `.env`, or
accepts credentials. Its input is a sanitised JSON file produced by a separate,
read-only capture procedure.

It passes only when that evidence proves all of the following against one
reviewed Git commit:

- the server checkout is clean and at that commit;
- the migration files in the checkout and the DB migration journal both exactly
  match the SHA-256 of every source migration;
- candidate images for API, collector, notifier and watchdog each name the
  same source commit and an immutable image digest;
- the four currently running services are captured as a healthy baseline with
  immutable image digests. They are deliberately **not** required to be the
  candidate images before deployment;
- backup, schema and health checks are explicitly verified;
- the schema claim is backed by a successful, read-only run of the independent
  `avelren.schema_verify` physical-contract verifier against the exact source
  migration set;
- the evidence contains no credential-shaped keys.

Example with synthetic evidence only:

```sh
python3 ops/deployment-preflight.py \
  --source-commit "$(git rev-parse HEAD)" \
  --evidence /safe/path/sanitised-evidence.json
```

`PASS` means only that the reviewed evidence is internally consistent. It does
not authorise a deployment. A real production operation still requires a fresh
read-only capture, review of its plan and an explicit GO for the exact host
commands.

The current production evidence intentionally fails this gate: its checkout is
dirty and lacks migration files 011–013. That is the desired fail-closed
result, not a reason to alter production.

## Future physical-schema capture

This repository does not include a production command that can be run by
accident. When a separate, explicit GO is granted for a read-only capture, the
approved command must run `python -m avelren.schema_verify /migrations` against
the reviewed migration directory with the database session enforced read-only.
It must stop on a non-zero exit status. The resulting sanitised evidence records
only `verifier`, `read_only_session`, `exit_code`, and the migration SHA-256
mapping under `schema_verification`; it must never include the command output,
a host name, a DSN, or any secret.

The offline preflight verifies that this attestation matches the reviewed
source. It still cannot make a production operation authorised: the exact host
command and its read-only scope require their own GO.
