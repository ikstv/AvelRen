# 3B.2 window card — production adoption of ownership and ACL

> **Performed 2026-08-17 14:07–14:08 UTC, `exit 0`, `stage=committed`.**
> This revision is the one the window ran under. Three previous attempts failed on
> an incomplete environment; sections 2.6a, 4.1 and 4.2 are exactly what closed that.
>
> The result, verified by measurement rather than by the log: ownership of 20 objects →
> `avelren_migrator`; ACLs granted (api 18, backup 14, collector 27,
> migrator 98, notifier 8, watchdog 6); the schema stayed `009_observability`;
> the legacy `avelren` `SUPERUSER+LOGIN` untouched; `db` not recreated;
> `migrate` did not run; the post-commit gate — **25 passed** against 22 failed in
> the dry check. Client downtime ~31 s.

> This is **not** an authorization and not a replacement for `deploy/postgres-adoption-runbook.md`.
> The runbook explains *why*; this card is the exact launch contract, derived from
> `deploy/postgres-adopt.sh` at the prod commit, plus the stop rules.
>
> One command here **mutates the production database**. Everything before it is read-only.

---

## 0. What it does and does not do

**Does:** transfers ownership of application objects to `avelren_migrator`,
applies the ACLs from migration `010`, leaves the legacy `avelren` `SUPERUSER+LOGIN`
untouched, brings clients back on the **unchanged** legacy DSN.

**Does not:** does not create roles (that's 3B.1, already done), does not run `migrate`,
does not stamp `010` — `schema_migrations` stays at `009` **by design**, does not
switch the DSN, does not touch `.env`.

After success — `HARD STOP`. The next stage (3C) does not exist as a production mode and
does not launch by accident.

---

## 1. Prerequisites — access

**The window is launched under `root`, and this is not style but arithmetic.** `adopt.sh`
cross-checks the owner of the preflight file, the token and the runner against the `id -u` of whoever launches it.
On the host they are `root`-owned (`600`, `600`, `700`), so the equality holds only
under root — and it could not be otherwise: `docker` needs sudo, `.env` is readable only by
root, the runner `700 root` is not executable for `averlenadmin`.

- `root` or sudo on the production host;
- `/opt/avelren` — a checkout at the prod commit, a **clean** tree;
- `.env` with the production DSNs — read access;
- three files, each with its own permissions (section 2).

None of this is "built up as we go". If it's missing — stop.

---

## 2. Preflight — everything read-only, everything checked, nothing assumed

### 2.1 Commit and tree

```bash
COMMIT=$(git -C /opt/avelren rev-parse HEAD); echo "$COMMIT"
git -C /opt/avelren status --porcelain          # MUST be empty
```

`adopt.sh` compares `AVELREN_EXPECTED_COMMIT` with `git rev-parse HEAD` **exactly**
(40 hex, lowercase) and refuses with `exact commit mismatch`. Any
unaccounted-for file in the checkout → `worktree is dirty`.

### 2.2 Preflight file

```bash
PREFLIGHT=/var/lib/avelren-adoption/recovery-preflight-<stamp>.txt
stat -c '%a %u %F' "$PREFLIGHT"    # 400 or 600, uid = id -u, regular file
wc -l -c "$PREFLIGHT"              # 3 lines
grep -Fxq "exact_commit=$COMMIT" "$PREFLIGHT" && echo PREFLIGHT-COMMIT-OK
```

The script requires **exactly** three lines and cross-checks the third against `EXPECTED_COMMIT`
(`recovery preflight commit mismatch`). The file must not be a symlink, and its owner = whoever
launches adoption.

### 2.3 Token file

```bash
TOKEN=/var/lib/avelren-adoption/prod-adoption-token
stat -c '%a %u' "$TOKEN"           # 400 or 600, uid = id -u
```

The content must be **exactly** `AVELREN-POSTGRES-ADOPTION-PROD`. The token is read
from the file, never from argv — do not pass it on the command line.

### 2.4 Gate runner

```bash
RUNNER=/usr/local/sbin/avelren-privilege-gate     # cross-check the actual path
stat -c '%a %u %F' "$RUNNER"       # 500 or 700, uid = id -u, regular, not a symlink
test -x "$RUNNER" && echo RUNNER-EXECUTABLE
```

**And the image freshness** — the thing that broke on 14 August and nearly broke now:

```bash
sudo docker run --rm --network none --entrypoint sh \
  avelren-privilege-gate:latest -c \
  'grep -c "\"schema_migrations\": {\"SELECT\"}" /workspace/app/tests/test_db_privileges.py'
```

Must be **4**. Not 4 — the image is stale, rebuild it, do not open the window.

### 2.5 The evidence directory — **not a prerequisite, but a parameter**

There is **no need** to create it in advance. `prepare_evidence_dir()`
(`deploy/postgres-ownership.lib.sh`) does the `mkdir -p` itself, sets `chmod 700`
and cross-checks the owner against `id -u`. There is no fixed directory with such a name —
the path is fully defined by `AVELREN_EVIDENCE_DIR` at launch.

```bash
EVID=/var/lib/avelren-adoption/evidence-3b2-$(git -C /opt/avelren rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)
```

There are exactly four requirements on it, and the script checks all of them: **absolute**, **outside
`/opt/avelren`**, **not a symlink**, and its owner will be whoever launches adoption.
Evidence inside the checkout makes the tree dirty and refuses adoption — this already
happened on the previous 3B.1.

> The warning about a "missing evidence directory" is a false alarm. It was raised by my
> own audit, which assumed a static parent path that `adopt.sh`
> does not consume.

### 2.6 The six DSNs for the gate — **cross-check that they exist**

The runner fail-closes on each of: `AVELREN_ADMIN_TOOL_DSN`,
`AVELREN_COLLECTOR_DSN`, `AVELREN_NOTIFIER_DSN`, `AVELREN_WATCHDOG_DSN`,
`AVELREN_API_DSN`, `AVELREN_BACKUP_DSN`.

Four of them compose uses itself, so they are almost certainly present in `.env`.
`AVELREN_ADMIN_TOOL_DSN` and `AVELREN_BACKUP_DSN` compose does **not** use —
check them separately, do not assume:

```bash
sudo grep -c '^AVELREN_ADMIN_TOOL_DSN=' /opt/avelren/.env
sudo grep -c '^AVELREN_BACKUP_DSN='     /opt/avelren/.env
# each must give 1; do NOT print the values
```

If any is missing — **stop**. The gate will fail after the commit, and it will roll back
a correct adoption.

### 2.6a `AVELREN_PSQL_BIN` — mandatory on the production host

`_adoption_psql()` (`postgres-ownership.lib.sh:135`) calls
`"${AVELREN_PSQL_BIN:-psql}"`. On the host `psql` is **not installed** — it lives
only in the `db` container. Without this variable adoption refuses with
`admin connection failed` before any mutation.

Do **not** invent the wrapper: the project has a reference
(`deploy/postgres-adoption-bootstrap-topology-test.sh:132`), and in it — a detail
a homemade version loses: `_adoption_psql` puts the DSN into `PGDATABASE`, and
a real `psql` **does not expand a URI from the `PGDATABASE` variable**, so it must be
passed as a positional conninfo inside the container.

Place it **outside the checkout** (a file inside `/opt/avelren` would make the tree
dirty and refuse adoption):

```bash
cat >/var/lib/avelren-adoption/psql-in-db.sh <<'WRAP'
#!/usr/bin/env bash
cd /opt/avelren
exec docker compose exec -T -e PGDATABASE db \
    sh -c 'exec psql "$PGDATABASE" "$@"' _ "$@"
WRAP
chown root:root /var/lib/avelren-adoption/psql-in-db.sh
chmod 0700     /var/lib/avelren-adoption/psql-in-db.sh
```

What is preserved: the DSN goes **by name** via `-e PGDATABASE`, never in argv;
`-T` passes through the stdin by which adopt.sh feeds the plans; `exec` propagates the exit code.

> **Launch trap.** `docker compose exec -T` reads stdin. If you launch
> `adopt.sh` via an SSH heredoc, the very first psql call will eat the rest of the script.
> Launch **by file** (`bash deploy/postgres-adopt.sh …`), not by stream.

### 2.7 Operational overlay

```bash
ls -l /opt/avelren/docker-compose.override.yml
```

The restart after the commit names this file explicitly, because on prod it supplies
`ECHERHA_*`, which are not in the tracked compose and without which `config.py`
fail-closes. If the file is missing — find out why **before** the window: otherwise the clients
will come up in the second failure mode of 14 August.

### 2.8 Baseline for the stop rules

```bash
sudo docker ps --format '{{.Names}}\t{{.CreatedAt}}\t{{.Status}}'
sudo docker inspect avelren-db-1 --format '{{.Id}} {{.State.StartedAt}}'
curl -fsS https://api.bordersignal.pp.ua/api/health
```

Record it. This is what you will compare against afterwards.

---

## 3. Choosing the moment

Catalog drift is the main cause of a "baseless" refusal. TimescaleDB creates
a new chunk at the 7-day boundary; if it appears between the preflight snapshot and the window,
adoption **will refuse before the first mutation**:

```
ADOPTION REFUSED: catalog drifted between preflight and mutation window
```

This is a safeguard that works, not an incident. To avoid catching it:

- launch **immediately** after preflight, with no coffee breaks;
- not within the nightly backup (03:00–04:00 UTC);
- daytime is better: the collector writes evenly, night is no better in any way.

---

## 4. Launch

The DSN values are taken from `.env` into the environment and **never end up in argv**.

```bash
cd /opt/avelren
set -a; . ./.env; set +a

AVELREN_TARGET_DB=avelren \
AVELREN_ADMIN_DSN="<legacy avelren superuser DSN from .env>" \
AVELREN_EXPECTED_COMMIT="$COMMIT" \
AVELREN_RECOVERY_PREFLIGHT_FILE="$PREFLIGHT" \
AVELREN_EVIDENCE_DIR="$EVID" \
AVELREN_ADOPTION_SUCCESS_GATE_RUNNER="$RUNNER" \
AVELREN_PSQL_BIN=/var/lib/avelren-adoption/psql-in-db.sh \
AVELREN_STACK_DIR=/opt/avelren \
AVELREN_COMPOSE_PROJECT=avelren \
AVELREN_ADMIN_TOOL_DSN="$AVELREN_ADMIN_TOOL_DSN" \
AVELREN_COLLECTOR_DSN="$AVELREN_COLLECTOR_DSN" \
AVELREN_NOTIFIER_DSN="$AVELREN_NOTIFIER_DSN" \
AVELREN_WATCHDOG_DSN="$AVELREN_WATCHDOG_DSN" \
AVELREN_API_DSN="$AVELREN_API_DSN" \
AVELREN_BACKUP_DSN="$AVELREN_BACKUP_DSN" \
bash deploy/postgres-adopt.sh \
  --confirm-adoption AVELREN-POSTGRES-ADOPTION \
  --production-adopt \
  --production-token-file "$TOKEN" \
  2>&1 | tee "$EVID/run.log"
```

### 4.1 Environment closure — fifteen variables, and why exactly that many

Three times in a row the window failed because of an incomplete list. So below is not "what
I remembered", but a **mechanical closure**: everything that `adopt.sh`,
`postgres-ownership.lib.sh` and `postgres-privilege-gate.sh` read together.

> **The root of all three failures is one, and it is methodological.** The environment
> contract was derived from `adopt.sh` — the entry point. But `adopt.sh` **spawns** other
> processes (the psql wrapper, the gate runner) and passes the environment to them by inheritance, not
> by export. So a variable can have a safe default at the entry point and be
> `:?` fail-close in a descendant. That is exactly what happened three times: `AVELREN_PSQL_BIN`
> (default `psql`, which is not on the host), `AVELREN_STACK_DIR` and
> `AVELREN_COMPOSE_PROJECT` (defaults in `adopt.sh`, `:?` in the runner).
>
> **A rule for the future:** the environment contract is computed over the **transitive
> closure of processes**, not over the entry point. For 3C this is critical — there
> five more runners are spawned.
>
> **And a second source of truth worth remembering:** the authoritative thing turned out to be not
> only the code, but the **actual launch script of the previous attempt** on the host
> (`run-3b2-<commit>.sh`). It contained exactly those three variables. Reading the code is
> right; reading the code **and the last real launch** is more complete.

**The trap that cost a commit and a rollback:** `adopt.sh` has defaults for
`AVELREN_STACK_DIR` and `AVELREN_COMPOSE_PROJECT`, while the gate runner fail-closes on
both via `:?`. That is, adopt.sh calmly reaches the commit, while the gate
refuses **without running a single assertion** → an inverse rollback of a correct
adoption. The mechanism is identical to the 2026-08-14 incident.

| # | variable | why it's needed |
|---|---|---|
| 1 | `AVELREN_TARGET_DB=avelren` | exact name, cross-checked |
| 2 | `AVELREN_ADMIN_DSN` | legacy superuser |
| 3 | `AVELREN_EXPECTED_COMMIT` | 40-hex, = HEAD |
| 4 | `AVELREN_RECOVERY_PREFLIGHT_FILE` | |
| 5 | `AVELREN_EVIDENCE_DIR` | fresh path |
| 6 | `AVELREN_ADOPTION_SUCCESS_GATE_RUNNER` | |
| 7 | `AVELREN_PSQL_BIN` | there is no `psql` on the host |
| 8 | **`AVELREN_STACK_DIR`** | **`:?` in the gate runner** |
| 9 | **`AVELREN_COMPOSE_PROJECT`** | **`:?` in the gate runner** |
| 10–15 | `AVELREN_{ADMIN_TOOL,COLLECTOR,NOTIFIER,WATCHDOG,API,BACKUP}_DSN` | six `:?` in the gate runner |

**Do NOT set ANY of these:**

`AVELREN_COMPOSE_FILE` — separately dangerous, and not as a "test variable".
Naming the compose file disables auto-discovery, and then the restart after the commit
**will lose `docker-compose.override.yml`**, which on prod supplies `ECHERHA_*`.
The clients will come up in the second failure mode of 14 August. Leave it empty.

`AVELREN_TEST_DB`, `AVELREN_ADOPTION_FAILPOINT`,
`AVELREN_ADOPTION_POST_COMMIT_GATE`, `AVELREN_ADOPTION_COMMITTED_FAILPOINT`,
`AVELREN_ADOPTION_CORRUPT_INVERSE`, `AVELREN_PRODUCTION_TARGET_OVERRIDE`,
`AVELREN_PRODUCTION_DRIFT_INJECT`, `AVELREN_ALLOW_DIRTY_TEST`,
`AVELREN_CURRENT_DB_USER` — these are all test injections; most the script will reject
itself, but `AVELREN_CURRENT_DB_USER` would silently override the admin-connection check.

The roles (`avelren`, `avelren_admin`, `avelren_migrator`) are `readonly` in the
library, not variables. `AVELREN_DOCKER_BIN`, `AVELREN_GIT_BIN`,
`AVELREN_PRIVILEGE_GATE_{COMPOSE_FILE,SERVICE}` have correct defaults.

### 4.2 Dry check of the gate — **mandatory before launch**

This is the structural fix for what failed twice: not letting the post-commit
path contain a step whose preconditions are not checked under the **same** environment.

Take the **same launch file**, replace the `adopt.sh` call with a direct call to the
runner and run it:

```bash
... the same env block ... \
bash "$RUNNER" privilege_contracts; echo "rc=$?"
```

Expect a failure on `assert actual == expected` of the frozen ACL — the database is not yet
adopted. This is a **success** of the check: the gate reached the assertions, so the environment is complete.

Any other failure — `AVELREN_STACK_DIR is required`, `is required` on a DSN,
a compose error, `--noconftest` — means the environment is still incomplete.
**Do not open the window.**

---

**Do not set** `AVELREN_TEST_DB`, any failpoint, and do not add
`--retire-legacy` — each of these the script rejects with a separate refusal, and correctly.

---

## 5. What happens inside, in order

To read the log rather than guess:

1. check of the token, commit, clean tree, preflight, runner permissions;
2. **read-only** assertion that all 7 roles exist (the script never creates them);
3. snapshot of the preflight ownership/ACL manifest;
4. **entering the window**: stop of `caddy api collector notifier watchdog`; `db` stays;
5. a repeat manifest snapshot, now without clients → comparison with step 3 (this is the drift check);
6. building the forward/inverse plans, proof of their parse and round-trip;
7. **COMMIT** of the forward plan;
8. the `privilege_contracts` gate — introspection-only pytest in a disposable container;
9. assertion that the legacy `avelren` stayed `SUPERUSER+LOGIN`;
10. publication of the evidence `stage=committed`;
11. restart of the clients on the **unchanged** legacy DSN, with `--no-deps`;
12. `HARD STOP`.

The mutation begins only at step 7. Everything before it is a refusal without consequences.

---

## 6. Exit codes — read carefully, it's easy to do harm here

| code | means | what to do |
|---|---|---|
| `0` | adoption committed, clients came up | check health and stop |
| **`3`** | **adoption committed and correct, but the clients did not come up** | **Do NOT roll back.** Bring them up by hand: `docker compose up -d --no-deps caddy api collector notifier watchdog`, then health |
| other | refused or rolled back | read the log; either there was no mutation, or it was undone by the inverse plan |

**About code 3 specifically.** The temptation of "something went wrong → roll back" is mistaken here:
the database is already in the correct state, and a rollback would destroy correct operation. And in the manual
restart **`--no-deps` is mandatory**: without it Compose will pull in `migrate` as a
dependency, and it will see 009, apply and stamp `010` out of sequence —
and while the inverse ACL plan can roll back, the `010` stamp cannot.

Never run a bare `docker compose up -d` at this moment.

---

## 7. Stop rules

Stop **before** launch if anything from section 2 does not match.

After launch the script drives itself: it either finishes the job, or refuses, or
rolls back. Your task is to **not intervene** until an exit code appears. In particular:

- do not restart services by hand while the script is running;
- do not do `docker compose up` in a neighboring terminal;
- do not edit `.env`.

If the process is cut off (network, SSH) — **do nothing**, read the evidence:
`$EVID/stage` says in which state everything stopped.

---

## 8. Known refusals and what they mean

| message | means |
|---|---|
| `exact commit mismatch` | `AVELREN_EXPECTED_COMMIT` ≠ HEAD |
| `worktree is dirty` | a stray file in the checkout; move it **outside** `/opt/avelren`, do not delete evidence |
| `recovery preflight commit mismatch` | the third line of preflight is the wrong commit |
| `production token file mode must be 0400 or 0600` | token permissions |
| `post-commit gate runner mode must be 0500 or 0700` | runner permissions |
| `production adoption requires a privilege-contract gate runner` | `AVELREN_ADOPTION_SUCCESS_GATE_RUNNER` not set |
| `production target must be exactly avelren` | a typo in `AVELREN_TARGET_DB` |
| `admin connection failed` | `AVELREN_PSQL_BIN` not set (there is no `psql` on the host), or the wrapper does not pass the DSN as a positional conninfo. **There was no mutation** — this is the very first check |
| `catalog drifted between preflight and mutation window` | a new chunk between the snapshot and the window; **nothing was mutated**, retry closer to the window |
| `production privilege-contract acceptance failed` | the gate failed **after** the commit → an inverse rollback. Look at what exactly: if it's on the frozen ACL — the gate image is stale (section 2.4) |

---

## 9. After success

State: ownership on the seven roles, ACLs from `010`, `schema_migrations` = `009`,
the legacy `avelren` `SUPERUSER+LOGIN`, the clients on the legacy DSN.

Check and record:

```bash
curl -fsS https://api.bordersignal.pp.ua/api/health
sudo docker ps --format '{{.Names}}\t{{.Status}}'
ls -l "$EVID"                      # stage, original.tsv, forward.sql, inverse.sql, …
git -C /opt/avelren status --porcelain
```

And then — **stop**. This is a valid state of rest; you can sit in it for
months. 3C has no production mode and will not launch on its own.

What **not** to do after 3B.2:

- a bare `docker compose up -d` — it will pull in `migrate` and stamp `010` outside of 3D;
- `deploy/backup.sh` instead of the deployed `/usr/local/sbin/avelren-backup` — the grants for `avelren_backup` exist already now, but replacing the script is a separate change (#93), not a side effect of the window.
