# AvelRen — Project Status Snapshot

Snapshot date: 2026-08-13 (post PR #40 merge, post PR #37 rebase). Purpose:
single canonical document to resume work from another PC without replaying
prior sessions. This document does not grant any production authorization.
See README section "Межа операційної авторизації" and
`docs/disaster-recovery.md` for the hard operational boundary.

## Canonical baseline

- Repository: `https://github.com/ikstv/AvelRen.git`
- Main branch: `main`
- `main` head at snapshot: `0fd0495` — squash-merge of PR #40
  (adoption fixture chunk pinning + mismatch dump + rationale comment).
- Active development branch: `feat/postgres-production-adopt`
  (PR #37, DRAFT), head `386b897`, rebased onto `0fd0495`, CI GREEN on its
  own merits (all four adoption checks PASS on `--production-adopt` code).

Recover exact SHAs on any machine with:

```bash
git fetch --all --prune
git rev-parse origin/main
git rev-parse origin/feat/postgres-production-adopt
gh pr view 37 --json headRefOid,state,isDraft
```

## Incident record: 2026-08-13 adoption-suite failure (RESOLVED)

From 2026-08-13 the adoption integration suite (`after_commit`) failed on
every run, on `main` as well as branches: "inverse rollback exact manifest
mismatch (39 rows)". Root cause: the fixture seeded `observations` at a fixed
date while runtime gates insert at `now()`; 2026-08-13 00:00 UTC is an exact
epoch-aligned 7-day Timescale chunk boundary (20678 / 7 = 2954), so from that
date the two inserts landed in different chunks and the autonomously created
chunk appeared as ACTUAL_ONLY rows in the exact manifest verification. The
rollback itself was never wrong.

Fix (PR #40, squash-merged as `0fd0495`): pin `chunk_time_interval` to
36500 days before the fixture insert AND seed at `now()`. Do NOT lower the
interval back to 7 days — see the comment block in
`deploy/postgres-adoption-integration-test.sh` (around line 283). Side effect
kept: manifest mismatches now dump the differing rows, not just a count.
Deliberately NOT done: tolerating Timescale chunk objects in exact
verification (would mask real ownership anomalies; separate discussed PR
only).

Post-merge verification: the first direct-push `main` run since 2026-08-12
(run 31712618623, 7m7s) is GREEN — this also retires the push-vs-PR
hypothesis conclusively (the difference was calendar-driven, not
event-driven).

Operational takeaway for the adoption runbook: if a Timescale chunk appears
between capture and mutation in production, the drift check
(`pre-mutation.tsv`) ABORTS adoption. This is fail-safe behaviour, known by
name — not a mystery failure. Operators must know this before 3B.2.

## Open PRs

| PR | Branch | State | Notes |
|---|---|---|---|
| #37 | `feat/postgres-production-adopt` | DRAFT, CI GREEN | Production adoption (`postgres-adopt.sh`, +123/−4). Rebased onto `0fd0495`. Do NOT merge, do NOT convert out of DRAFT — production adoption is not authorized. |
| #30 | `hotfix/echerha-v5-contract` | OPEN, DRAFT | Base is `ci/production-04eaea-hotfix-base` (NOT main). Its content (єЧерга v5 contract) is already forward-ported to main via #31 (`108e4ee`) → factually superseded. Closing it is a human decision; architect recommendation: close with a comment pointing to #31. |

Merged since the 2026-08-12 snapshot: #29 (runtime role split, `f9cc884`),
#31 (єЧерга v5 forward-port, `108e4ee`), #32 (API resource bounds), #33 / #35
(Android Server Dashboard), #36 (Gradle wrapper cache), #40 (CI chunk fix,
`0fd0495`). Closed without merge: #34 (replaced by #35), #38 (baseline
probe), #39 (diagnostics; instrumentation carried into #40).

## Open issues (highest-signal only)

- #15 — PostgreSQL runtime role split. PR #29 is merged, but the issue stays
  OPEN by policy: it closes only after separately authorized production
  rollout AND retirement of the legacy role AND both proven safe.
- Remaining issues: see `gh issue list`. Do NOT start speculative work on
  these without an explicit task.

## What is authorized right now

- Backend, deploy, Android, docs code changes on feature branches.
- Local disposable Docker Compose runs via `scripts/backend-test.sh`.
- Running slow static / contract / integration gates in
  `docs/backend-testing.md`.
- Opening / updating draft PRs against feature branches.

## What is NOT authorized (hard boundary)

- Any production operation on ECHERHA / PostgreSQL: no SSH, no deploy, no
  adoption, no restore, no credential generation or rotation, no legacy
  NOLOGIN, no legacy `REVOKE CONNECT`.
- Merging PR #37; converting PR #37 out of DRAFT.
- Closing issue #15.
- ECHERHA v5 production rollout beyond what #31 already merged as code.
- Force-push or history rewrite on any branch, with a single standing
  exception: rebasing a feature branch onto `main` followed by
  `git push --force-with-lease` of that feature branch only.

## Secrets and machine-local state

- Tracked template: `.env.example`. All password / DSN slots are intentionally
  empty. Real values live only in the authorized host secret store.
- Never-committed: `.env`, `secrets/`, `*service-account*.json`,
  `google-services.json`, `android/local.properties`, `/data/`, build
  outputs, virtualenvs, IDE state. Enforced by `.gitignore`.

## Bring-up on a new PC

Prerequisites: Git, Docker Desktop (with `docker compose`), Git Bash / MSYS
on Windows, JDK 17+ and Android SDK for Android builds, Python 3 only for
local tooling outside the Docker workflow.

```bash
git clone https://github.com/ikstv/AvelRen.git
cd AvelRen
cp .env.example .env             # placeholders only; leave secret fields empty
bash scripts/backend-test.sh     # canonical fast backend gate (Docker)
```

Slow / focused gates (privilege, backup, restore, adoption, allowlist
contract, integration): see `docs/backend-testing.md`. Run only what a task
requires.

## CI parity (canonical checks)

Defined in `.github/workflows/ci.yml`. GREEN on `main` in both PR and push
contexts as of `0fd0495` (push run 31712618623).

Documented follow-ups, not yet wired:

- Negative drift-check case: deliberately create a Timescale chunk between
  capture and mutation in a disposable run and assert the adoption ABORTS
  with the expected message. Turns the runbook claim above into an executable
  guarantee. Separate PR; do not bundle with feature work.

## Next reasonable actions (choose explicitly, do not chain)

1. Resolve PR #30 (recommendation above; human authorization required to
   close).
2. Wire `restore-allowlist-contract-test.py` into `.github/workflows/ci.yml`
   (small, separate PR).
3. Negative drift-check case (separate PR, after item 2).
4. Dedicated production-mode adoption case → review → 3B.1 (bootstrap.sql
   roles) → separate explicit GO for 3B.2.

Anything beyond this — production adoption, PR merges, issue closures,
ECHERHA rollout — requires a fresh explicit authorization, not this document.
