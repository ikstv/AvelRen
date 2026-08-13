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
- Prod checkout is at the exact expected commit, clean worktree.

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
them manually (`compose up -d`) and verify health; non-`0`/non-`3` = refused or
rolled back, see the log.

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
