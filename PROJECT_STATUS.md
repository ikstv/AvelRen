# AvelRen — Project Status Snapshot

Snapshot date: 2026-08-12. Purpose: single canonical document to resume work
from another PC without replaying prior sessions. This document does not grant
any production authorization. See README section "Межа операційної авторизації"
and `docs/disaster-recovery.md` for the hard operational boundary.

## Canonical baseline

- Repository: `https://github.com/ikstv/AvelRen.git`
- Main branch: `main`
- Active development branch: `codex/issue-15-postgres-least-privilege-impl`
- Long-lived worktrees on the primary workstation (do not delete):
  - `C:/AI/AvelRen` — main worktree, current dev branch.
  - `C:/Users/tanko/AppData/Local/Temp/AvelRen-echerha-v5-hotfix`
    — branch `hotfix/echerha-v5-contract` (PR #30, DRAFT).
  - `C:/Users/tanko/AppData/Local/Temp/AvelRen-echerha-v5-main-forward-port`
    — branch `fix/echerha-v5-main-forward-port`.

Recover exact SHAs on any machine with:

```bash
git fetch --all --prune
git rev-parse origin/main
git rev-parse origin/codex/issue-15-postgres-least-privilege-impl
gh pr view 29 --json headRefOid,state,isDraft
gh pr view 30 --json headRefOid,state,isDraft
```

## Open PRs

| PR | Branch | State | Notes |
|---|---|---|---|
| #29 | `codex/issue-15-postgres-least-privilege-impl` | DRAFT | Split PostgreSQL runtime roles. Implementation DONE, review APPROVED, exact-head CI GREEN. Do NOT merge, do NOT convert to Ready — production adoption is not authorized. |
| #30 | `hotfix/echerha-v5-contract` | DRAFT | ECHERHA v5 contract emergency hotfix. Code implemented, reviewed, pushed. Full local TimescaleDB regression was NOT available during hotfix validation. Production rollout is NOT authorized. |

## Open issues (highest-signal only)

- #15 — PostgreSQL runtime role split. Stays OPEN even after PR #29 merges;
  closes only after separately authorized production rollout AND retirement of
  the legacy role AND both proven safe.
- #14, #16, #18, #19, #20, #21, #22, #23, #24, #25, #26, #13 — see `gh issue list`.
  Do NOT start speculative work on these without an explicit task.

## What is authorized right now

- Backend, deploy, Android, docs code changes on feature branches.
- Local disposable Docker Compose runs via `scripts/backend-test.sh`.
- Running slow static / contract / integration gates in `docs/backend-testing.md`.
- Opening / updating draft PRs against feature branches.

## What is NOT authorized (hard boundary)

- Any production operation on ECHERHA / PostgreSQL: no SSH, no deploy, no
  adoption, no restore, no credential generation or rotation, no legacy NOLOGIN,
  no legacy `REVOKE CONNECT`.
- Merging PR #29 or PR #30.
- Converting PR #29 or PR #30 out of DRAFT.
- Closing issue #15.
- ECHERHA v5 production rollout.
- Force-push or history rewrite on any branch.
- Deleting worktrees or branches listed above.

## Secrets and machine-local state

- Tracked template: `.env.example`. All password / DSN slots are intentionally
  empty. Real values live only in the authorized host secret store.
- Never-committed: `.env`, `secrets/`, `*service-account*.json`,
  `google-services.json`, `android/local.properties`, `/data/`, build outputs,
  virtualenvs, IDE state. Enforced by `.gitignore`.
- Local scratch on the primary workstation: `_to_delete/` (backup copies +
  stale locks; ignored via `.gitignore`) and `.superpowers/` (runtime state,
  already ignored). These do not exist on a fresh clone and are not required.

## Bring-up on a new PC

Prerequisites: Git, Docker Desktop (with `docker compose`), Git Bash / MSYS on
Windows, JDK 17+ and Android SDK for Android builds, Python 3 only for local
tooling outside the Docker workflow.

```bash
git clone https://github.com/ikstv/AvelRen.git
cd AvelRen
cp .env.example .env             # placeholders only; leave secret fields empty
bash scripts/backend-test.sh     # canonical fast backend gate (Docker)
```

Android build uses the Gradle wrapper under `android/`. `android/local.properties`
is machine-local (`sdk.dir=...`) and must be created locally.

Slow / focused gates (privilege, backup, restore, adoption, allowlist contract,
integration): see `docs/backend-testing.md`. Run only what a task requires.

## CI parity (canonical checks)

Defined in `.github/workflows/ci.yml`:

- `completeness` — critical files present in git.
- Backend fast gate — `scripts/backend-test.sh` (Ruff + migrations + pytest).
- Shell/script static gates and deploy contract tests as listed in
  `docs/backend-testing.md`.
- Android build and unit tests.

The restore allowlist contract test (`deploy/restore-allowlist-contract-test.py`)
lives in the tree; wiring it into the workflow is a documented follow-up.

## Recent commit of note

- `de396d7` on the active branch — audit remediation batch
  (H-1/H-4 + M-4/M-7/M-9/M-10/M-11/M-12/M-13/M-16 + read-rate-limit).
  Draft PR body: `PR-audit-2026-08-12.md`. Not yet opened as a separate PR.

## Next reasonable actions (choose explicitly, do not chain)

1. Push local branch state to `origin` and confirm `local == origin`.
2. Open the audit-remediation PR from `PR-audit-2026-08-12.md` (DRAFT).
3. Wire `restore-allowlist-contract-test.py` into `.github/workflows/ci.yml`.

Anything beyond this — production adoption, PR merges, issue closures, ECHERHA
rollout — requires a fresh explicit authorization, not this document.

<!-- ci probe: baseline adoption suite on pull_request event -->
