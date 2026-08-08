# Backend checks

The canonical local backend workflow uses Docker Compose, so system Python and
manual dependency installation are not required.

```bash
bash scripts/backend-test.sh
```

The command builds an isolated test image, starts a disposable TimescaleDB,
runs Ruff, applies migrations, and runs the full backend suite. It uses only
the explicit `ci-only` database password from
`docker-compose.backend-test.yml`; it does not read production `.env` or
production secrets.

Expected result is exit code 0, Ruff green, and at least the baseline backend
test total. CI runs this same script.
