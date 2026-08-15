# AvelRen — Project Status Snapshot

Snapshot date: 2026-08-15 (post AUDIT-2026-08-15; post 3B.2 attempt + recovery;
post supply-chain wave #62–#77). Purpose: single canonical document to resume
work from another PC without replaying prior sessions. This document does not
grant any production authorization. See README section "Межа операційної
авторизації" and `docs/disaster-recovery.md` for the hard operational boundary.

The full current-state analysis lives in `AUDIT-2026-08-15.md` — this snapshot
is the short index over it.

## Canonical baseline

- Repository: `https://github.com/ikstv/AvelRen.git`
- Main branch: `main`; recover the exact head with `git rev-parse origin/main`.
- Merged this wave (all squash, CI-green on exact heads): #61 bootstrap-superuser
  topology (Decision B), #62 unexpected-database refusal, #63 completeness
  semantics, #64 Dependabot+CodeQL, #68 privilege-gate `--noconftest`, #69
  Dependabot major/minor split, #70 collector eCherha identity in compose, #72
  eCherha egress guard, #73 Android version bumps parked, #74 image digest
  pinning, #75 gitignored compose override, #60 Android Modernist theme, #77
  setup-gradle re-pin.
- Open and deliberately held: **PR #80** (F1/F2 — legacy-DSN restart in
  adopt.sh; CI green incl. all adoption scenarios; awaiting human diff review),
  **PR #78** (this audit as a doc), user drafts #51–#55, Dependabot #65
  (python 3.12→3.14 — needs an explicit decision, not an auto-merge).

## Incident record: 2026-08-14 Stage 3B.2 production attempt (RESOLVED)

First production adoption attempt: forward adoption committed and verified,
post-commit privilege gate failed, verified inverse rollback restored the exact
owner/ACL fingerprint — zero data loss. Runtime restart then failed and the
site was down ~20 minutes until an operator supplied a legacy-DSN override.
Three root-cause classes, all fixed with regression tests: leftover
`restore_test` database (now refused by name pre-mutation, #62), a privilege
gate that could not run anywhere (`--noconftest`, contract now executed in CI,
#68), and the adopt.sh-vs-compose DSN model split (legacy-DSN restart overlay,
PR #80). Full narrative and findings: `AUDIT-2026-08-15.md` §1.

## Production state (informational, changes only via explicit GO gates)

- Prod repo, recovery evidence and gate-runner copy are all pinned to one
  commit (`8b8eed2`) — intentionally behind main; the Gate 11 guard binds
  evidence↔repo↔runner to a single commit, so re-prep is one atomic step.
- Runtime runs on the legacy DSN via a gitignored `docker-compose.override.yml`
  (matches adopt.sh's documented 3B.2 model); `schema_migrations = 009`
  (010's ACL is applied by adoption, stamped at 3D).
- Least-privilege rollout (#15) resumes with: review+merge PR #80 → atomic
  Gate 11 re-prep (repo update, gate copy refresh, fresh isolated
  restore-verify evidence) → quiet window → explicit GO → 3B.2.

## Open issues (6)

- **#15** least-privilege — code/tooling complete and CI-proven; blocked only
  by PR #80 review + Gate 11 re-prep.
- **#18** Android API 36 — draft #52 exists; land together with the
  AGP 9 / Gradle 9 / Kotlin 2.4 toolchain migration, then un-park Dependabot
  gradle updates.
- **#19** FCM token ownership — needs a human design gate before code.
- **#23** supply-chain — remaining: pip hashed locks, SBOM, Gradle locking,
  python base index digest, Kotlin CodeQL.
- **#25** runbooks — signing runbook remains.
- **#26** umbrella — closes with its children.

## What is authorized right now

- Backend, deploy, Android, docs code changes on feature branches.
- Local disposable Docker Compose runs via `scripts/backend-test.sh`.
- Running slow static / contract / integration gates in
  `docs/backend-testing.md`.
- Opening / updating draft PRs against feature branches.

## What is NOT authorized (hard boundary)

- Any production mutation without an explicit, per-action operator GO given in
  the session: no deploy, no adoption (`--production-adopt`), no restore into
  the production cluster, no credential generation/rotation, no legacy NOLOGIN
  or `REVOKE CONNECT`. Read-only inspection may be separately authorized.
- Merging PR #80 without human diff review (it edits the production-mutation
  code that caused the 2026-08-14 outage).
- Closing issue #15 before 3B.2 actually succeeds with evidence.
- Hand-editing recovery-preflight evidence — it is only ever produced by a
  real isolated restore-verify.
- Force-push or history rewrite on any branch, with a single standing
  exception: rebasing a feature branch onto `main` followed by
  `git push --force-with-lease` of that feature branch only.

## Secrets and machine-local state

- Tracked template: `.env.example`. All password / DSN slots are intentionally
  empty. Real values live only in the authorized host secret store.
- Never-committed: `.env`, `secrets/`, `*service-account*.json`,
  `google-services.json`, `android/local.properties`, `/data/`, build
  outputs, virtualenvs, IDE state, `docker-compose.override.yml`. Enforced by
  `.gitignore`.

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

Three required checks on every PR: `completeness` (critical files, secrets,
eCherha egress guard), `backend-tests` (canonical workflow + the full
contract/integration ladder incl. all four adoption scenarios and the
bootstrap-superuser topology suite), `android-build`. Plus `CodeQL / Analyze
(python)`. Branch protection requires up-to-date branches; expect a re-sync
before merge after main moves.

## Next reasonable actions (choose explicitly, do not chain)

1. Human review of PR #80 (F1/F2) → merge → atomic Gate 11 re-prep → quiet
   window → 3B.2 (closes #15).
2. Decide Dependabot #65 (python 3.12→3.14 on the prod image base).
3. Land or close user drafts #51–#55 before they rot (two are security fixes).
4. #23 remainder: SBOM, pip hashed locks, Gradle locking.
5. #22 remainder: external black-box monitor (audit F8).
