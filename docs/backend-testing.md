# Backend checks

## Fast canonical backend gate

The canonical local backend workflow uses Docker Compose, so system Python and
manual dependency installation are not required.

```bash
bash scripts/backend-test.sh
```

The fast command builds an isolated test image, starts a disposable TimescaleDB,
runs Ruff, applies migrations, and runs the primary backend suite. Its database
credential is repository-owned disposable test configuration; no credential
value is documented or printed. It does not read production `.env` or production
secrets.

Expected result is exit code 0, Ruff green, and at least the baseline backend
test total. CI runs this same script for its primary backend workflow.

Do not add the slow PostgreSQL privilege, backup/restore, or adoption suites to
`scripts/backend-test.sh`. It remains the fast Ruff/migrations/pytest path.

## Focused static and contract gates

Run these separately from the fast workflow:

```bash
bash -n deploy/postgres-bootstrap.sh deploy/postgres-adopt.sh deploy/postgres-ownership.lib.sh
bash deploy/postgres-bootstrap-contract-test.sh
bash deploy/compose-security-contract-test.sh
bash deploy/postgres-adoption-contract-test.sh
```

## Slow local and CI security/DR/adoption gates

These commands are separate slow gates. They use disposable databases and must
never receive production `.env`, production volumes, external production
credentials, or production state:

```bash
bash deploy/postgres-roles-integration-test.sh

bash deploy/backup-contract-test.sh
bash deploy/restore-contract-test.sh
bash deploy/restore-engine-contract-test.sh
bash deploy/restore-production-contract-test.sh

bash deploy/restore-integration-test.sh
bash deploy/restore-production-integration-test.sh

AVELREN_ADOPTION_SCENARIO=before_commit bash deploy/postgres-adoption-integration-test.sh
AVELREN_ADOPTION_SCENARIO=after_commit bash deploy/postgres-adoption-integration-test.sh
AVELREN_ADOPTION_SCENARIO=success bash deploy/postgres-adoption-integration-test.sh
```

The three adoption scenarios are cold independent runs, not retries of one warm
environment. Every integration must retain its unique Compose project, bounded
readiness, `AVELREN_TEST_DB=1` guard where required, and guaranteed teardown of
containers, networks, and volumes on success or failure.

CI runs the fast command first and then the focused and slow gates sequentially
inside `backend-tests`; destructive integrations are not parallelized. The
workflow file `.github/workflows/ci.yml` is the source of truth for CI gates.
Running `bash scripts/backend-test.sh` alone is not evidence that the slow
security, DR, and adoption gates passed.
