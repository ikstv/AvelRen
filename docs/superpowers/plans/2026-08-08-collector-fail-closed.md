# Collector Fail-Closed Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject unsafe collector configuration before any database or upstream side effect.

**Architecture:** Keep general settings loadable by all services and expose a pure collector-specific validator from `avelren.config`. Call it at the first executable boundary in `collector.main()` so invalid configuration cannot reach signal registration, pool construction/opening, HTTP client creation, or a fetch.

**Tech Stack:** Python 3.12, Pydantic Settings, asyncio, pytest, Ruff, Docker Compose CI.

## Global Constraints

- Only collector may contact `back.echerha.gov.ua`.
- Source must be exactly `https://back.echerha.gov.ua/api`.
- Vehicle type must be integer `1`; buses remain out of scope.
- Polling remains exactly 60 seconds start-to-start with no catch-up retry.
- HTTP timeout must be an integer from 1 through 30 seconds inclusive.
- Invalid startup must make no DB or upstream network attempt.
- No schema, API, forecast, retry, or deployment behavior changes.

---

### Task 1: Pure collector configuration contract

**Files:**
- Modify: `app/src/avelren/config.py`
- Create: `app/tests/test_collector_config.py`

**Interfaces:**
- Consumes: `Settings` values loaded by Pydantic.
- Produces: `CollectorConfigurationError` and `validate_collector_settings(candidate: Settings) -> None`.

- [ ] **Step 1: Write table-driven failing tests**

Create settings with `_env_file=None`; assert production defaults pass. Parametrize rejected `echerha_base_url` values covering HTTP, alternate host, explicit port, alternate path, trailing slash, query, fragment, and userinfo. Parametrize vehicle type `0`/`2`, cadence `59`/`61`, and timeout `0`/`31`. Assert `CollectorConfigurationError` identifies only the field name.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest app/tests/test_collector_config.py -q -p no:cacheprovider`

Expected: collection failure because the validator interface does not exist.

- [ ] **Step 3: Implement the minimal pure validator**

Add the canonical URL constant, exception class, and ordered checks:

```python
ECHERHA_COLLECTOR_BASE_URL = "https://back.echerha.gov.ua/api"

class CollectorConfigurationError(RuntimeError):
    pass

def validate_collector_settings(candidate: Settings) -> None:
    if candidate.echerha_base_url != ECHERHA_COLLECTOR_BASE_URL:
        raise CollectorConfigurationError("invalid collector setting: echerha_base_url")
    if candidate.echerha_vehicle_type != 1:
        raise CollectorConfigurationError("invalid collector setting: echerha_vehicle_type")
    if candidate.poll_interval_seconds != 60:
        raise CollectorConfigurationError("invalid collector setting: poll_interval_seconds")
    if not 1 <= candidate.http_timeout_seconds <= 30:
        raise CollectorConfigurationError("invalid collector setting: http_timeout_seconds")
```

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest app/tests/test_collector_config.py -q -p no:cacheprovider`

Expected: all pure validation cases pass.

### Task 2: Startup-before-side-effects gate

**Files:**
- Modify: `app/src/avelren/collector.py`
- Modify: `app/tests/test_collector_config.py`

**Interfaces:**
- Consumes: global collector `settings` and `validate_collector_settings`.
- Produces: non-zero collector startup failure before pool/client access.

- [ ] **Step 1: Write a failing startup-order test**

Monkeypatch collector settings to an invalid cadence. Replace `get_pool` and `httpx.AsyncClient` with sentinels that fail if called. Await `collector.main()` and assert `CollectorConfigurationError` plus zero sentinel calls.

- [ ] **Step 2: Run focused startup test and confirm RED**

Run: `python -m pytest app/tests/test_collector_config.py -q -p no:cacheprovider`

Expected: test fails because `main()` reaches a side effect before validation.

- [ ] **Step 3: Add the startup hook**

Import `validate_collector_settings` and call it immediately after `logging.basicConfig(...)`, before `asyncio.get_running_loop()`, signal handlers, `get_pool()`, or `httpx.AsyncClient`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest app/tests/test_collector_config.py -q -p no:cacheprovider`

Expected: all validator and startup-order tests pass.

### Task 3: Verification, review, and integration

**Files:**
- Verify: `.env.example`, `docker-compose.yml`, collector/config source and tests.

**Interfaces:**
- Consumes: Tasks 1–2 implementation.
- Produces: reviewed branch, PR linked to #17, exact-head CI, and integrated main.

- [ ] **Step 1: Run local static and focused verification**

Run Ruff on `app/src` and `app/tests`, the focused test file, strict UTF-8 decode, and `git diff --check`.

- [ ] **Step 2: Run canonical backend workflow**

Run `bash scripts/backend-test.sh` when Docker is available. If the local Docker daemon is unavailable, require the identical exact-head CI job and do not claim local integration evidence.

- [ ] **Step 3: Request independent code review**

Review the exact base-to-head diff against issue #17 and this plan. Fix all Critical/Important findings and rerun relevant verification.

- [ ] **Step 4: Push and open a Ready PR**

Use branch `codex/issue-17-collector-invariants`, link issue #17 without auto-closing before merge, and include exact local evidence.

- [ ] **Step 5: Require exact-head CI and merge**

Require `completeness`, `backend-tests`, and `android-build` success on the exact PR head. Merge only after review; verify issue #17 state and close it only when implementation evidence is integrated.
