# Production Restore Audit Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining readiness, maintenance-cleanup, and composed restore-test blockers from the exact-head PR #27 audit.

**Architecture:** Keep production restore orchestration in Bash. Parse the public health response with Python inside the already-running API container, make maintenance cleanup preserve the primary status while reporting and verifying secondary stop failures, and extend disposable integration tests at real engine/DB boundaries.

**Tech Stack:** Bash, Docker Compose, Python 3 JSON parser, PostgreSQL/TimescaleDB, GitHub Actions.

## Global Constraints

- Only `collector` may contact eCherha; no client or new proxy path.
- Collector cadence remains exactly 60 seconds start-to-start and truck-only.
- No production restore, deployment, Ready transition, merge, or issue closure.
- Existing migrations are immutable.

---

### Task 1: Strict API health JSON

**Files:**
- Modify: `deploy/restore-production-contract-test.sh`
- Modify: `deploy/restore-production-integration-test.sh`
- Modify: `deploy/restore-production.sh`

**Interfaces:**
- Consumes: response body from `curl $READINESS_URL`.
- Produces: exit zero only for a top-level JSON object containing `status` in `{"ok", "stale"}`, `last_observation`, and `age_seconds`.

- [ ] Add malformed, incidental/nested-status, and valid health response contract cases.
- [ ] Run the contract in Linux CI and confirm current regex behavior fails the negative case.
- [ ] Replace regex matching with JSON parsing inside the running API container.
- [ ] Re-run production orchestrator contracts and integration.

### Task 2: Verifiable fail-closed maintenance cleanup

**Files:**
- Modify: `deploy/restore-production-contract-test.sh`
- Modify: `deploy/restore-production.sh`

**Interfaces:**
- Consumes: primary exit status plus `compose stop`/`compose ps` results.
- Produces: preserved primary status, separate cleanup-error logs, and an explicit final stopped-state check.

- [ ] Add stop-failure and still-running-after-cleanup contract scenarios.
- [ ] Confirm the current cleanup trap falsely claims stopped state.
- [ ] Capture each stop result, log secondary failures, query final running services, and preserve the primary exit code.
- [ ] Re-run contract tests.

### Task 3: Composed actual-engine and migration-prefix regressions

**Files:**
- Modify: `deploy/restore-production-integration-test.sh`
- Modify: `.github/workflows/ci.yml` only if a separate invocation is required.

**Interfaces:**
- Consumes: real restore engine, disposable TimescaleDB, service-boundary fakes.
- Produces: evidence for post-engine readiness failure cleanup and migration prefix `001…008` to current `009`.

- [ ] Add an actual-engine readiness failure after temporary restart and assert a second stop plus final stopped state.
- [ ] Build a disposable backup whose recorded history is the contiguous `001…008` prefix.
- [ ] Run the real migrate suffix gate, assert `009_observability` is applied, then run full verification.
- [ ] Run exact-head CI and require `completeness`, `backend-tests`, and `android-build` success.

