# Collector Fail-Closed Configuration Design

## Goal

Make collector startup fail before any database or upstream access unless its
source, vehicle scope, cadence, and request timeout match AvelRen's production
safety contract.

## Fixed contract

- `echerha_base_url` must equal `https://back.echerha.gov.ua/api` exactly.
  Alternate hosts, schemes, ports, paths, trailing slashes, query strings,
  fragments, and userinfo are rejected rather than normalized.
- `echerha_vehicle_type` must equal integer `1` (trucks).
- `poll_interval_seconds` must equal integer `60`; the existing collector loop
  continues to schedule start-to-start and never catches up aggressively.
- `http_timeout_seconds` must be an integer from `1` through `30`, inclusive.

## Architecture

Add a pure `validate_collector_settings(candidate: Settings) -> None` boundary
in `avelren.config`. It raises `CollectorConfigurationError` with a safe,
field-specific message on the first violated invariant and otherwise returns
`None`. `collector.main()` calls it immediately after logging setup and before
signal registration, pool lookup/open, HTTP client construction, or a fetch.

Validation remains collector-specific: importing settings for API, notifier,
watchdog, migrations, or administrative commands does not apply collector
startup policy to those processes. No client or new service is allowed to call
eCherha.

## Failure behavior

An invalid environment causes collector process startup to exit non-zero via
the uncaught configuration exception. The error identifies the invalid field
but does not print credentials or arbitrary secret values. There is no fallback,
normalization, retry, request, or database connection.

## Tests

Add `app/tests/test_collector_config.py` with table-driven unit coverage for:

- the valid default/production values;
- alternate scheme, host, port, path, trailing slash, query, fragment, and
  userinfo in `echerha_base_url`;
- vehicle types other than integer `1`;
- cadence values other than integer `60`;
- timeout values below `1` or above `30`;
- `collector.main()` rejecting invalid settings before `get_pool()` or
  `httpx.AsyncClient` can be called.

The canonical backend suite, Ruff, restore/backup contracts, and exact-head CI
remain required before review and integration.

## Scope boundary

This change does not alter fetch retry behavior, polling scheduling, response
filtering, database schema, API behavior, buses, forecast, runtime roles, or
resource limits. Issues #15 and #16 remain separate subsequent gates.
