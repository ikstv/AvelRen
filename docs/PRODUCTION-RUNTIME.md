# Production runtime package

This package records the production Compose runtime in the consolidated private
repository. It was transferred from the old `AvelRen` repository at server
checkout commit `81e5b047f8f18c42ca46a59f86495f71d0681af0` and adapted to the
monorepo paths (`services/backend`, `ops/`). The deployment model has not been
validated by deploying this checkout.

## Host-only configuration

The expected production checkout path is `/opt/avelren`. Host configuration
(`.env`, `docker-compose.override.yml`, Firebase credentials and telemetry
snapshot) is not part of Git. `.env.example` contains empty secret/DSN values
and safe non-secret defaults. Do not copy a production override into Git or
replace it with a default-only Compose invocation: the existing override may
contain a migration pin and compatibility settings needed by the adoption
sequence.

## Migration boundary

The `migrate` service is behind the explicit `migrate` profile. A normal Compose
service start must not apply migrations. At the production comparison on
2026-09-23, the database had migrations 001–009 applied and their checksums
matched this repository. Migrations 010 and 011 are present in the repository
but unapplied on production. This document does not authorize applying them;
follow the private operations runbook and obtain operation-specific approval.

## Runtime scope and outstanding work

Compose defines the database, migration runner, collector, notifier, watchdog,
API and Caddy. Caddy serves the privacy page from `ops/static/`. The host-side
telemetry systemd service/timer and its installation procedure remain a
separate transfer stage. The restore CLI and verifier are available, while the
production restore orchestrator and its runbook remain separate work. No
production server, database, secret, service, or image was changed or validated
by this repository change.

## Local checks

The Compose contract test resolves configuration with sentinels and does not
start services. A successful local contract or image build is not proof of
production deployment readiness; compare the effective host configuration and
run the authorized staged rollout checks before deployment.
