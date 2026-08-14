# AvelRen — Project Status Snapshot

Snapshot date: 2026-08-14. Purpose: single canonical document to resume work
from another PC without replaying prior sessions. **This document grants no
production authorization.** See README "Межа операційної авторизації",
`docs/disaster-recovery.md`, and `AGENTS.md` for the hard operational boundary.

## Canonical baseline

- Repository: `https://github.com/ikstv/AvelRen.git`
- Main branch: `main`; head at snapshot: **`faf1ed2`**.
- No long-lived feature branch is "the" dev branch anymore — work is one
  short-lived branch + draft PR per task (see the work plan).

Recover exact state on any machine:

```bash
git fetch --all --prune
git rev-parse origin/main        # expect faf1ed2 or later
gh pr list --state open
gh issue list --state open
```

## What changed since the 2026-08-13 snapshot (READ THIS)

The previous snapshot said "PR #37 DRAFT, do not merge". **That is now stale.**
PR #37 (the `--production-adopt` code) was reviewed, got a conditional technical
GO, and was **squash-merged into main** (`dcf1edf`). Merging the *code* did NOT
authorize any production operation — see the boundary below.

Merged since then (all in `main`): #37 (production adoption path), #41 (status
refresh), #42 (allowlist contract wired into CI), #44 (privacy/retention docs),
#45 (full 2026-08-14 audit + pre-adoption DR procedure), #46 (H-1: async OAuth
refresh off the event loop), #47 (MED: throttle `last_seen` writes to 1/hour),
#48 (H-5: SHA-pin GitHub Actions), #49 (MED: compose memory/CPU limits).
Closed: #30 (superseded by #31), #13/#14/#17/#20/#21/#24 (implemented + tested;
closed with justification).

**Open PR:** **#50** (`test/production-failure-rollback-case`) — OPEN (not
draft), CI GREEN. Adds the production-mode **failure → inverse rollback → exact
original** integration case (all three production sub-cases green:
drift-abort, failure-rollback, happy-path). Awaiting human review/merge.

## Production rollout state (least-privilege, issue #15)

Real production database state (host `averlen-helsinki`):

- **Stage 3A** (fresh verified backup) — done. Backup proven restorable live
  (346k rows restored under legacy `avelren` into a disposable target,
  2026-08-14).
- **Stage 3B.1** (role provisioning) — **DONE ON PROD (2026-08-14)**:
  `bootstrap.sql` created the 7 least-privilege roles. Verified: `avelren_admin`
  SUPERUSER; 6 workers LOGIN NOINHERIT NOBYPASSRLS NOSUPERUSER; legacy `avelren`
  **untouched** (SUPERUSER+LOGIN); ownership **unchanged** (still single-role);
  `schema_migrations` = 009. Evidence on host under `/opt/avelren/evidence/`.
- **Stage 3B.2** (ownership/ACL adoption) and **3C–3F** — **NOT STARTED**,
  require a separate explicit human GO. Prod is still single-role: `avelren`
  owns everything, migrations at 009.

Prod git checkout is at `a5d642a`; an uplift to current `main` is needed before
3B.2 (for `--production-adopt`), as a read-only step under the runbook.

## Open issues

- **#15** least-privilege — in progress (3B.1 done). Closes only after full
  authorized rollout (3B.2–3F) + legacy retirement. Do NOT close.
- **#18** Android API 36 — hard Google Play deadline ~2026-08-31; compileSdk/
  targetSdk still 35. Highest calendar priority.
- **#19** FCM ownership / device+collector_runs retention — design gate.
- **#22** external black-box monitor — not started.
- **#23** supply-chain — partially: SHA-pin done (#48); mypy + pip-audit remain.
- **#25** — privacy docs done (#44); release/signing runbook remains.
- **#26** audit aggregator — held until #15/#18.

## What is authorized right now

- Backend, deploy, Android, docs code changes on feature branches.
- Local disposable Docker Compose runs via `scripts/backend-test.sh`; slow
  gates per `docs/backend-testing.md`.
- Opening / updating draft PRs.

## What is NOT authorized (hard boundary)

- Any production operation on ECHERHA / PostgreSQL beyond the completed 3A/3B.1:
  no 3B.2–3F adoption, no DSN cutover, no restore, no credential generation or
  rotation, no legacy NOLOGIN / `REVOKE CONNECT`, no new prod deploy.
- **Merging any PR** — human decision (agent stops at draft/green).
- Closing issue #15 (and #25 until its runbook lands).
- Force-push/history rewrite, with one exception: rebasing a feature branch onto
  `main` + `git push --force-with-lease` of that branch only.

Merging the #37 *code* did not lift any of this. Production execution stays
gated on explicit human authorization, per operation.

## Secrets and machine-local state

- Tracked template: `.env.example` — all password/DSN slots intentionally empty.
- Never committed: `.env`, `secrets/`, `*service-account*.json`,
  `google-services.json`, `android/local.properties`, `/data/`, build outputs,
  virtualenvs, IDE state. Enforced by `.gitignore`.

## Bring-up on a new PC

```bash
git clone https://github.com/ikstv/AvelRen.git
cd AvelRen
cp .env.example .env             # placeholders only; leave secret fields empty
bash scripts/backend-test.sh     # canonical fast backend gate (Docker)
```

## Next reasonable actions

Follow the sequential work plan (T-01 … T-14): status refresh (this) → land
PR #50 (review, human merge) → **Android API 36 (#18, deadline)** → Android
release config → Caddy body-limit → watchdog /run scope → compose healthchecks
→ backup RPO → collector/watchdog tests → Android notification tests → CI split
(mypy/pip-audit/coverage) → retention + FCM-ownership design → external monitor
→ release-signing runbook. One branch + draft PR per task; do not chain without
an explicit request.

Anything in Phase F — 3B.2–3F production rollout, PR merges, issue closures —
requires fresh explicit human authorization, not this document.
