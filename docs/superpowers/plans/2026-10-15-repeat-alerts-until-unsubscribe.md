# Repeat alerts until unsubscribe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make threshold and ETA alerts repeat every five minutes until the user manually removes the related subscription or target.

**Architecture:** ACK becomes a read acknowledgement only: it keeps threshold and ETA rows pending while recording `acknowledged_at`. `active_alert_keys` suppresses an acknowledged alert until notifier records its next successful normal delivery. Collector stops automatically expiring pending threshold and ETA alerts; the existing DELETE transaction remains the sole terminal path.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, PostgreSQL/TimescaleDB, pytest, Docker-backed database test suite.

**Spec:** `docs/superpowers/specs/2026-10-15-repeat-alerts-until-unsubscribe.md`

## Global Constraints

- Keep `alert_resend_seconds=300`, FCM payloads, IDs, collapse keys, TTL, Android 0.1.3 wire contract and collector 60-second cadence unchanged.
- Do not add a migration; use only existing `status`, `acknowledged_at`, `last_sent_at` and `send_count`.
- Do not alter surge/forecast or health-alert lifecycles.
- Preserve DELETE cancel-outbox-before-delete transactions for threshold and ETA.
- Do not revive historical closed alerts or send retrospective production pushes.
- Production packaging, deployment and phone testing require separate approval after source CI.

## Review Focus

- A foreground refresh immediately after ACK must not recreate the locally dismissed alert; Task 1 pins this.
- A send failure after ACK must keep the alert hidden until a successful resend; Task 2 pins this.
- Deleting a subscription between notifier selection and marking sent must not increment a deleted alert; Task 2 preserves the conditional update test.
- Queue fall or target-time passage must not end a pending alert, while an already closed alert stays closed; Task 3 pins both states.
- Surge acknowledgement/expiry must keep its existing terminal semantics; Task 3 runs the surge database regressions unchanged.

---

### Task 1: Preserve pending alerts through threshold and ETA acknowledgement

**Files:**
- Modify: `services/backend/src/avelren/subscriptions_api.py:330-356,484-510`
- Modify: `services/backend/src/avelren/cancels.py:95-139`
- Create: `services/backend/tests/database/test_repeat_alert_ack.py`

**Interfaces:**
- Consumes: existing authenticated `POST /alerts/{alert_id}/ack`, `POST /eta-alerts/{alert_id}/ack` and `GET /active-alerts` routes.
- Produces: ACK rows with `status='pending'` and non-null `acknowledged_at`; `active_alert_keys(conn, device_id) -> dict[str, list[int]]` returns only acknowledged rows whose `last_sent_at > acknowledged_at`.

- [ ] **Step 1: Write failing database tests for threshold and ETA ACK lifecycle**

Create fixtures that insert one owned threshold alert and one owned ETA alert. Assert an ACK keeps each `status='pending'`, stamps `acknowledged_at`, preserves the ETA target as active, and a repeated ACK is idempotent. Assert `/active-alerts` omits both directly after ACK.

- [ ] **Step 2: Run the focused database test to verify it fails**

Run: `bash scripts/test_database.sh`

Expected: FAIL because both endpoints currently set `status='acknowledged'` and active alerts include all pending rows.

- [ ] **Step 3: Change ACK updates and `active_alert_keys`**

In both ACK handlers, update only `acknowledged_at=COALESCE(acknowledged_at,now())` for an owned pending row and retain their existing response contract. In `cancels.active_alert_keys`, add `(acknowledged_at IS NULL OR last_sent_at > acknowledged_at)` to threshold and ETA queries only; leave surge query unchanged.

- [ ] **Step 4: Run the focused database test to verify it passes**

Run: `bash scripts/test_database.sh`

Expected: PASS with pending rows hidden from foreground reconciliation immediately after ACK.

- [ ] **Step 5: Commit**

```bash
git add services/backend/src/avelren/subscriptions_api.py services/backend/src/avelren/cancels.py services/backend/tests/database/test_repeat_alert_ack.py
git commit -m "feat: зберігати alert pending після OK"
```

### Task 2: Re-enable a dismissed alert only after a successful resend

**Files:**
- Modify: `services/backend/tests/database/test_repeat_alert_ack.py`
- Verify: `services/backend/src/avelren/notifier.py:38-134`

**Interfaces:**
- Consumes: Task 1 pending ACK rows and `notifier.run_cycle(client) -> int`.
- Produces: a successful normal resend updates `last_sent_at` and `send_count`, allowing the same ID back into `active_alerts`; failed delivery does neither.

- [ ] **Step 1: Write failing notifier/reconciliation tests**

In the database test, freeze or age `last_sent_at` past the configured gap after ACK. Stub `fcm.send` once successfully and assert the same ID is sent, `send_count` increments, and `/active-alerts` returns it again. Add a temporary FCM error case and assert it remains hidden with unchanged send metadata.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `bash scripts/test_database.sh`

Expected: FAIL while acknowledged alerts are terminal in the starting implementation.

- [ ] **Step 3: Keep notifier delivery semantics minimal**

Do not change `_QUERY`, payload creation, `collapse_key`, TTL or `_mark_sent`. Make only any adjustment the failing tests demonstrate is necessary for a pending acknowledged row to use the current normal success path; retain `_mark_sent(... AND status='pending')` race protection.

- [ ] **Step 4: Run focused tests and notifier race regression**

Run: `bash scripts/test_database.sh`

Expected: PASS; a failed send does not reactivate an alert and the deletion race stays safe.

- [ ] **Step 5: Commit**

```bash
git add services/backend/tests/database/test_repeat_alert_ack.py services/backend/src/avelren/notifier.py
git commit -m "test: перевірити повтор після OK"
```

### Task 3: Remove automatic threshold and ETA expiration while preserving manual cancel

**Files:**
- Modify: `services/backend/src/avelren/collector_replay.py:121-127`
- Modify: `services/backend/src/avelren/alerts.py:119-153`
- Modify: `services/backend/src/avelren/eta.py:114-139`
- Modify: `services/backend/src/avelren/cancels.py:1-14`
- Modify: `services/backend/tests/unit/test_collector_replay.py:31-55`
- Modify: `services/backend/tests/database/test_repeat_alert_ack.py`

**Interfaces:**
- Consumes: Task 1 pending alert lifecycle and existing DELETE endpoints.
- Produces: `replay_once(...)` evaluates threshold and ETA but never calls automatic expiration; DELETE retains the only cancel-outbox transition.

- [ ] **Step 1: Write failing collector and database lifecycle tests**

Update the unit mock harness to assert no expiration function is invoked during a fresh replay. In the database test, create pending threshold and ETA alerts, model a below-threshold queue and passed target time, then assert both remain pending. Add manual DELETE assertions for notification-cancel rows and absent alerts. Add an already `acknowledged`/`expired` fixture assertion that collector does not revive it.

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_collector_replay.py -q`

Run: `bash scripts/test_database.sh`

Expected: FAIL because replay currently calls both expiration functions.

- [ ] **Step 3: Remove automatic expiration calls and obsolete helpers**

Remove calls to `alerts.expire_stale` and `eta.expire_passed` from `replay_once`; remove helpers that become unreachable and update `cancels.py` documentation so it names only DELETE endpoints as alert-ending transitions. Do not alter evaluate, forward-crossing, rearm/dedup, DELETE SQL, surge code or schema.

- [ ] **Step 4: Run component regressions**

Run: `python -m ruff check services/backend/src services/backend/tests`

Run: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q`

Run: `bash scripts/test_database.sh`

Expected: all checks PASS, including unchanged surge lifecycle tests.

- [ ] **Step 5: Commit**

```bash
git add services/backend/src/avelren/collector_replay.py services/backend/src/avelren/alerts.py services/backend/src/avelren/eta.py services/backend/src/avelren/cancels.py services/backend/tests/unit/test_collector_replay.py services/backend/tests/database/test_repeat_alert_ack.py
git commit -m "feat: повторювати alert до ручної відписки"
```

### Task 4: Record release readiness and complete source acceptance

**Files:**
- Modify: `docs/RELEASE-READINESS.md`
- Modify: `docs/MIGRATION-REMAINING.md`

**Interfaces:**
- Consumes: merged implementation and successful source CI.
- Produces: explicit separate gates for source CI, production package/rollback, Android phone proof and 1.0.4 publication.

- [ ] **Step 1: Write the intended release-readiness rows before changing status**

Add unchecked rows for both threshold and ETA: initial push, sound, ACK, five-minute repeat, foreground reconciliation, unsubscribe cancel, rollback and exact deployed image. State no Play release occurs in this task.

- [ ] **Step 2: Run documentation consistency checks**

Run: `git diff --check`

Expected: no whitespace errors; no row claims phone or production acceptance.

- [ ] **Step 3: Commit**

```bash
git add docs/RELEASE-READINESS.md docs/MIGRATION-REMAINING.md
git commit -m "docs: додати приймання повторних сповіщень"
```

## Final verification

- [ ] Run the exact-head hosted CI and confirm the strict `CI gate` is successful.
- [ ] Independently review the implementation against the spec, especially ACK/foreground/resend/delete races and surge isolation.
- [ ] Prepare a separate immutable production package with preflight, rollback and a maximum 15-minute window; obtain a fresh specific production GO.
- [ ] Perform the approved phone scenario only after deployment and record the evidence without secrets.
