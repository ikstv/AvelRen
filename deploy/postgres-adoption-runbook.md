# PostgreSQL adoption runbook — Stage 3B (production)

Operational runbook for moving the live `avelren` database from the single
`avelren` SUPERUSER role to the seven least-privilege roles. This document is
procedure only; it grants **no** authorization. Each stage runs under a separate
explicit GO, with a HARD STOP before every mutation.

The mechanics (`deploy/postgres-adopt.sh --production-adopt`, the ownership
library, and the drift check) are proven by
`AVELREN_ADOPTION_SCENARIO=production` in the integration suite; this runbook is
what the operator follows on the real host.

## Preconditions (before 3B.1)

- Stage 3A done: a fresh verified backup exists and is retrievable off-host.
- The 7 role passwords/DSNs are present in the production `.env` (operator's
  hand; Claude never generates or sees them).
- Prod checkout is at the exact expected commit, clean worktree. See
  *Clean-worktree invariant* below — `postgres-adopt.sh` refuses with `worktree
  is dirty` if anything untracked sits in the checkout.

## Clean-worktree invariant (read before 3B.1 and 3B.2)

`postgres-adopt.sh` runs `git status --porcelain=v1 --untracked-files=all` in the
checkout and refuses (`worktree is dirty`) unless it is empty. `AVELREN_ALLOW_DIRTY_TEST`
bypasses this check but is **test-only and must never be set in production**. Two
kinds of operational file have dirtied the live checkout in the past and each
belongs **outside** `/opt/avelren`, not inside it:

- **Adoption evidence.** `AVELREN_EVIDENCE_DIR` must be an absolute path **outside
  the repo checkout** — e.g. `/var/lib/avelren-adoption/evidence/3b2-<UTC>` — never
  under `/opt/avelren`. The test suites already isolate evidence in a temp dir
  outside the repo; production must do the same. An evidence directory written
  inside the checkout dirties the worktree and blocks adoption (this is exactly
  what a prior 3B.1 run did with `/opt/avelren/evidence/3b1-*`).
- **Operator helpers.** Any ad-hoc script the operator places on the host (for
  example a DSN-builder) must live outside the checkout (e.g. `/root` or
  `/usr/local/sbin`), not at the repo root.

Pre-adoption step (operator's hand, read-only to the database): confirm
`git -C /opt/avelren status --porcelain` is empty. If not, relocate the offending
files out of the checkout (do **not** delete evidence — move it) until it is clean.
These are host-local operational artifacts, deliberately **not** tracked and
deliberately **not** `.gitignore`d — hiding them in-tree would only mask a
misplaced file; the fix is to keep them out of the checkout.

## 3B.1 — role provisioning (separate GO)

Run `db/security/bootstrap.sql` under the legacy `avelren` SUPERUSER to create
the 7 roles from the `.env` passwords. This is non-destructive (no ownership or
ACL change) and idempotent. Verify read-only that all 7 roles exist with the
expected LOGIN/attributes, then **HARD STOP**.

## 3B.2 — ownership/ACL adoption (separate GO)

`postgres-adopt.sh --production-adopt --production-token-file <0400/0600 file>`
bootstraps under the legacy `avelren` SUPERUSER, asserts the 7 roles exist,
captures the preflight manifest, enters a maintenance window (stops
caddy/api/collector/notifier/watchdog), re-captures the manifest **after** the
clients are stopped, commits the forward adoption (ownership → migrator/admin,
ACL from migration 010), runs the read-only `privilege_contracts` acceptance,
asserts legacy `avelren` is still SUPERUSER+LOGIN, and restarts the clients on
the **unchanged** legacy DSN. `schema_migrations` intentionally stays at `009`
— 010 is stamped later (3D), not here. No DSN cutover happens in 3B.2.

Exit codes: `0` = adoption committed and clients restarted; **`3` = adoption
committed and correct, but clients did not restart** — do NOT roll back, restart
them manually and verify health; non-`0`/non-`3` = refused or rolled back, see
the log.

The manual restart names the five services **and** passes `--no-deps`:

```bash
docker compose up -d --no-deps caddy api collector notifier watchdog
```

> **Never restart the runtime with a bare `docker compose up -d`.** An explicit
> service list alone does not help: Compose resolves `depends_on` and starts what
> it finds there. `migrate` is behind the `migrate` profile precisely so this
> cannot happen, and `--no-deps` is the second, independent guard at the call
> site.
>
> Both failure modes are real, and which one you get depends only on whether the
> 010 grants exist yet:
>
> * **Un-adopted database** (`avelren_migrator` still powerless): `migrate` exits
>   1 with `permission denied for schema public`, so
>   `service_completed_successfully` is never satisfied and caddy/api/collector/
>   notifier/watchdog **do not start at all**. The site goes down. This is the
>   state production is in today.
> * **After the grants exist**: `migrate` succeeds, finds `009`, and applies and
>   stamps `010` — outside the adoption sequence, contradicting the model above
>   in which 3B.2 leaves `009` and 3D does the stamping. If the restart then
>   fails, the inverse rollback restores the ACLs but cannot unstamp `010`, and
>   no existing guard detects the resulting divergence.

Migrations are applied deliberately and only on request:

```bash
docker compose --profile migrate up migrate
```

### The drift check — read this before the 3 a.m. window

Between the preflight capture and the maintenance window the collector is still
running and writing observations. TimescaleDB creates a new **chunk** whenever a
write crosses a 7-day chunk boundary. If a new catalog object (a chunk, its
index, its composite type) appears in that gap, the in-window recapture will not
match the preflight manifest and adoption **aborts by design** with:

```
ADOPTION REFUSED: catalog drifted between preflight and mutation window
```

**This is the fail-safe working, not a catastrophe.** It means the plan the
tooling built no longer matches reality, and refusing is correct. Operator
procedure:

1. Do **not** treat a `catalog drifted` abort as data loss or corruption —
   nothing was mutated; the adoption stopped before the first change.
2. Diagnose: the overwhelmingly likely cause is a benign new Timescale chunk
   created by the collector between capture and window. Confirm the drift is
   only `_timescaledb_internal` chunk objects, not an unexpected application
   change.
3. Re-run: capture the preflight manifest **as close to the maintenance window
   as possible**, ideally after the collector is already stopped, so no write
   can create a chunk in the gap. Then retry `--production-adopt`.

To minimise the chance of hitting this at all: schedule the window so preflight
and the client-stop happen back-to-back, and prefer running it away from a
7-day chunk boundary if the boundary is near.

## After 3B.2

`schema_migrations` = `009`; ownership on the 7 roles; legacy `avelren` still
SUPERUSER+LOGIN (retirement is 3F, much later). Next gates, each a separate GO:
3C DSN cutover of the services, 3D stamp migration 010, 3E rebuild/restart +
health/ACL verify, 3F soak → retire legacy `avelren`.
