# Restore rehearsal on an isolated bench (Gate 11, step B2)

> **This document is not an authorization.** It describes a procedure performed on a
> **disposable bench**, and then on the production host. No command below
> touches the `avelren` database, stops any production service, or changes
> anything in `/opt/avelren`. If some step seems to touch it —
> stop and reread: it means I made a mistake in the text, not you in your understanding.

The procedure has been run on disposable benches three times (section 12c), the last time
on a production-class artifact. The fixes after each run are already in the text.
The order stands: **bench before host**.

---

## 0. What this proves and what it does not

The rehearsal answers exactly one question: **can we bring up a working copy of the
database from our nightly encrypted artifact — not "the file unpacked", but
"the application works on it"**.

Proves:

| | |
|---|---|
| the artifact downloads from the remote intact and passes `gzip -t` | step 2 |
| the dump physically loads into TimescaleDB with correct pre/post-restore | step 7 |
| the set of application relations in the dump **exactly** matches the engine's allowlist | step 7 |
| the migration history and the physical schema contract are intact | step 9 |
| a real application reads and writes the restored database (health, auth, devices) | step 9 |

Does **not** prove:

- that the key for the crypt remote exists **outside** this server (that's `docs/backup-key-escrow.md`, a separate procedure);
- that a production restore fits within any time budget (RTO/RPO are not approved — `docs/disaster-recovery.md`);
- that `deploy/restore-production.sh` will work on the production database (it goes a different route: stops ingress, takes a pre-restore snapshot, works over the production compose). The rehearsal checks the **engine and the artifact**, not the orchestrator.

### Correction to a previous statement

I earlier said that "the project has no operator restore procedure at all".
**That was inaccurate.** There is:

- `deploy/restore-production.sh` — the full production-restore orchestrator (maintenance window, session gate, pre-restore snapshot, verify, controlled restart, freshness);
- `docs/disaster-recovery.md` §"Pre-adoption recovery" — a manual timescale-aware path under the legacy `avelren`, until adoption is complete.

What is genuinely missing is the **rehearsal**: the sequence of "how to bring up an isolated
cluster, where the roles in it come from, how to assemble the DSN, and with what exactly to
prove the result". It existed only inside the CI harness
`deploy/restore-integration-test.sh`, which generates its own compose and is not meant
for a production host. This document closes exactly that gap.

---

## 1. Prerequisites — access (a premise, not a step)

The performer must **already have**, before starting:

- `root` or the `docker` group on the host (`docker compose` mandatory, `psql` — inside the container);
- read access to `/opt/avelren` (compose, `deploy/`, `db/`);
- access to the remote's `rclone` config (`/root/.config/rclone/rclone.conf`) — **read-only**;
- `sudo` for `docker` and to read `/opt/avelren/.env` (verified on this host). **The procedure does not assume the operator is root**: run every reference to `$WORK` through `sudo`, otherwise `cd` there silently fails and the checks are skipped;
- the right to create `/var/lib/avelren-restore-rehearsal`;
- **seven bench passwords**, which the performer generates themselves and which **do not match production**. Production passwords are not needed even once in this procedure.

If any of these is missing — **stop**, this is not a "we'll sort it out as we go".

## 1a. Prerequisites — host state

Check (read-only), and **do not continue** if it does not match:

```bash
git -C /opt/avelren rev-parse HEAD                 # must be the prod pin (deploy/PROD_PIN)
git -C /opt/avelren status --porcelain             # must be EMPTY
df -h /var/lib                                     # free space ≥ 3× the dump size
docker image inspect avelren-app:latest \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep AVELREN_GIT_SHA
```

The last line must show the same commit. If `AVELREN_GIT_SHA` is empty
or different — the image was not built from the pin; the bench then verifies **the wrong** application.
This is not a reason to stop, but it must be recorded explicitly in the report.

> Why `git status` must be empty: not because it blocks the rehearsal (it does not
> block it), but because a dirty tree will block `postgres-adopt.sh` later anyway
> — better to find out now. See "Clean-worktree invariant" in
> `postgres-adoption-runbook.md` (private AvelRen-ops).

---

## 2. Step 1 — a working directory outside the checkout

Everything we create lives **outside** `/opt/avelren`. This is not style, it is a requirement:
any file inside the checkout makes the tree dirty and then refuses
adoption.

Two paths are pulled into variables — not for looks, but because without this the procedure
is non-portable, and the first run on a disposable machine fails not through its own fault
(section 12):

| variable | production host | disposable machine |
|---|---|---|
| `STACK` | `/opt/avelren` | path to the repository clone |
| `WORK` | `/var/lib/avelren-restore-rehearsal` | any directory outside the clone |

```bash
umask 077
export STACK=/opt/avelren
export WORK=/var/lib/avelren-restore-rehearsal

# 0701 — only the traverse bit: the container must PASS THROUGH $WORK to
# migrations-009, but has no right to list the contents.
install -d -m 0701 "$WORK"
# 0700 — the container does not enter here: the decrypted dump and the bench passwords.
install -d -m 0700 "$WORK/stand" "$WORK/artifact"
```

> **Why not `0700` on `$WORK`.** The `avelren-app` image runs under an unprivileged
> uid 10001 (`USER avelren` in `app/Dockerfile`), and the procedure is performed by root or
> an operator with sudo. The container cannot open a `0700 root:root` directory, and
> `/migrations` inside looks **empty** — not an access error, but an
> empty directory. Step 9 then fails with `migration 00X recorded, but the file is
> missing` ×9, which reads as a corrupt dump, even though the dump is intact.

> Found only on the production host (2026-08-17). Three benches were green, because
> the Windows filesystem silently did not apply `chmod`, and the warning
> `install: cannot change permissions` was written off as insignificant. The lesson is broader than this
> step: a warning you have explained to yourself is not the same as a warning you
> have verified.

---

## 3. Step 2 — the artifact: fetch, cross-check, **read**

```bash
cd "$WORK/artifact"
rclone lsf gdrive-crypt:avelren/daily/ --files-only | sort | tail -5
```

Choose an artifact (usually the latest `avelren-YYYYmmdd-HHMMSS.sql.gz`), fetch
it together with its sidecar:

```bash
NAME=avelren-<stamp>.sql.gz
rclone copyto "gdrive-crypt:avelren/daily/$NAME" "./$NAME"
chmod 0600 "./$NAME"

gzip -t "./$NAME"                 # must be silent
sha256sum "./$NAME" | tee "./$NAME.local-digest"   # WE RECORD, we don't cross-check
ls -l "./$NAME"
```

> **The `.sha256` sidecar does not exist — and this is not the performer's error.** The
> `/usr/local/sbin/avelren-backup` deployed on prod does not create them; the `deploy/backup.sh`
> version in the repository, which creates and cross-checks the sidecar, is **not deployed** (see section 14).
> Verified 2026-08-17: in `daily/`, `weekly/` and `monthly/` — zero sidecar files.
>
> So step 2 **records** the digest of the downloaded copy instead of cross-checking it
> against a nonexistent reference. This is weaker than a sidecar (it does not catch corruption on
> the remote's side), but it does not fake a proof that does not exist. The real integrity proof here comes
> not from the hash but from step 7: a dump that loaded into PostgreSQL with `ON_ERROR_STOP=1` and
> matched the engine's allowlist cannot be corrupt.
>
> The recorded digest is still needed: in the report it binds all subsequent
> numbers to a specific byte content.

### 2a. Dump reconnaissance — **do not skip**

This is the one step that turns an assumption into a measurement. We **do not know** in advance
under which role the production dump was taken and what ACLs it carries; steps 8 and 9 depend on it.

```bash
zcat "./$NAME" | head -30
zcat "./$NAME" | grep -c '^GRANT '
zcat "./$NAME" | grep -oE '\bavelren[a-z_]*\b' | sort -u
# where exactly the role is mentioned — this matters more than the mere fact of the mention:
zcat "./$NAME" | grep -n 'bgw_job' | head
```

Record in the report:

- the `pg_dump` and server version from the header;
- the number of `GRANT`s (zero — expected for schema 009 before adoption);
- the **full list of role names** that appear in the dump, and **where** exactly.

> Why this is critical. `restore.sh` runs the dump with `ON_ERROR_STOP=1`, so any
> role name in the dump that is not present in the bench brings down the restore in the middle of
> loading. And the names hide **in two different places**: in DDL grants
> (`GRANT ... TO <role>`) and **in the data** — the `owner` column of the
> `_timescaledb_config.bgw_job` table, which records the owners of Timescale background jobs
> (compression policy, refresh continuous aggregate).
>
> The second is more dangerous, because `grep -c '^GRANT '` does not see it. That is exactly how it will be on
> prod: zero grants, but the name `avelren` is present — in the data. So the list of roles
> for step 6a is taken from the **second** command, not the first.

> **NOTE: what follows was measured BEFORE Gate 11 3B.2 (2026-08-17 14:08 UTC).**
> Adoption changed exactly what is described here. Artifacts taken **after** this
> date will carry ACLs from migration `010`, and the application relations on prod belong to
> `avelren_migrator`, not the legacy `avelren`.
>
> What this implies for the steps below:
>
> - **step 2a:** expect **no longer zero** `GRANT`, but the full set from `010`, and the names of all six roles in the ACL — apart from the mention of the legacy `avelren` in `bgw_job`, which remains;
> - **step 6a** — still mandatory: the owner of Timescale background jobs did not change;
> - **step 8** — becomes **redundant**: the grants will come from the dump itself. Running it a second time is idempotent and harmless, but no longer needed; instead, verify that `avelren_api` reads `checkpoints` **before** it;
> - **step 3** (filter 001–009) — **unchanged**: `schema_migrations` was deliberately left at `009`;
> - the ownership handoff — unchanged: the dump is `--no-owner`, restored under `avelren_admin`.
>
> Update this block after 3D, once `010` is stamped.

**What exactly to expect in the production artifact — measured on prod 2026-08-17
(read-only), state BEFORE adoption:**

- the dump is taken by the **legacy `avelren`** (superuser) with `--no-owner`, not `avelren_backup`;
- on prod there are **zero** `table_privileges`, `column_privileges` and default ACLs for `avelren_%` roles;
- all 20 application relations belong to the legacy `avelren`; there are no traces of 3B.2.

Practical consequences, each verified by the commands above:

1. There must be **zero** `GRANT`s in the dump — and this does **not** mean step 6a is unnecessary. The name `avelren` will almost certainly appear in the `bgw_job` data; **step 6a is mandatory** (proven on bench #3: without it `exit=3`).
2. `--no-owner` + restore under `avelren_admin` ⇒ everything becomes admin-owned ⇒ the ownership check before handoff passes.
3. Step 8 (the 010 grant layer) on the production artifact is **mandatory, not optional**: without it `avelren_api` has nothing at all and the smoke test fails with `permission denied` (falsified on bench #3).

> For completeness: the `deploy/backup.sh` from the repository strictly requires the
> `avelren_backup` role, and on schema 009 `pg_dump -U avelren_backup` fails with
> `permission denied for table schema_migrations`, producing zero bytes
> (measured on bench #1). That is, **that** path is fail-closed and does not produce a partial dump.
> But it is not the one running on prod — see section 14.

---

## 4. Step 3 — the filtered set of migrations (001–009)

`python -m avelren.schema_verify` (`app/src/avelren/schema_verify.py`,
`verify_history`) cross-checks the migrations directory against the `schema_migrations` table
**in both directions**: a file without a record is an error, a record without a file is an error, a differing
SHA is an error.

The production database is at **009** deliberately (`010` is stamped only at 3D —
`postgres-adoption-runbook.md` (private AvelRen-ops)). If you mount the full `db/migrations` into the bench,
the check is guaranteed to fail with:

```
is in the files but not recorded as applied
```

This is not bypassing the check: `verify()` is designed for a partial set — the contract
is filtered by the actually-recorded versions (the `verify()` docstring describes this directly).
We give it a directory that matches the state of the database.

```bash
SRC="$STACK/db/migrations"
DST="$WORK/migrations-009"

# 0755/0644 — the directory is read by the container under uid 10001. There are no secrets here:
# these are the same files that live in git.
install -d -m 0755 "$DST"
cp -p "$SRC"/00*.sql "$DST/"      # 00* takes 001–009 and does NOT take 010
chmod 0644 "$DST"/*.sql

# byte-for-byte: checksums are computed over the file text
( cd "$SRC" && sha256sum 00[1-9]_*.sql ) > /tmp/src.sums
( cd "$DST" && sha256sum -c /tmp/src.sums )   # everything must be OK
ls "$DST"                                     # exactly 9 files, no 010
rm -f /tmp/src.sums
```

Immediately prove that the container sees them — otherwise the error surfaces only at step 9
and looks like a corrupt dump:

```bash
docker compose -f "$WORK/stand/compose.yml" -p avelren-rv3-86d3534 \
  run --rm --no-deps -T migrate ls /migrations </dev/null    # 9 files
```

And verify that what was closed stayed closed:

```bash
docker compose -f "$WORK/stand/compose.yml" -p avelren-rv3-86d3534 \
  run --rm --no-deps -T -v "$WORK:/w:ro" migrate ls /w/artifact </dev/null
# must be Permission denied
```

**If, after step 9, it turns out that the production database is already at 010** — then you must copy
all ten and skip step 8. You can check the actual version already
after the restore (step 7 outputs the counters; the version comes from
`SELECT max(version) FROM schema_migrations`).

---

## 5. Step 4 — the bench compose

Write as `$WORK/stand/compose.yml`:

```yaml
# Restore-rehearsal bench. NOT the production compose.
# The project directory for Compose = the directory of this file, so /opt/avelren/.env
# with production DSNs CANNOT be picked up here by accident.
name: avelren-rv3-86d3534

services:
  db:
    # The same digest as in the production docker-compose.yml — otherwise
    # the rehearsal verifies a different PostgreSQL.
    image: timescale/timescaledb:2.17.2-pg16@sha256:4e459e217f00cbb09920c34d245501e63427e6767a495de57ce76823ff280f12
    # The ceiling is below production: the bench has no right to eat into prod's memory.
    mem_limit: 768m
    cpus: 1.0
    environment:
      POSTGRES_USER: avelren_admin
      POSTGRES_PASSWORD: ${STAND_ADMIN_PASSWORD:?stand admin password missing}
      POSTGRES_DB: postgres
      # This marker exists ONLY in the bench .env. Step 5 uses it to prove that
      # the container reads the bench environment, not the production one.
      AVELREN_STAND_GUARD: ${AVELREN_STAND_GUARD:?stand env-file not loaded}
    volumes:
      - stand_db:/var/lib/postgresql/data
      # checkout read-only: the bootstrap script needs db/security/*.sql
      - ${STACK:?STACK not exported}:/workspace:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U avelren_admin -d postgres"]
      interval: 2s
      timeout: 3s
      retries: 30
    # There are deliberately NO ports exposed: the bench is unreachable from the network or from
    # the production project (a different Compose project → a different network).

  # Both services exist only for `restore-verify.sh`, which runs them
  # as `run --rm --no-deps` with a substituted command (verified: the command
  # is substituted at the call site, so `command:` here is only a stub,
  # but both services must be described).
  #
  # On the production host we take the READY image and do NOT build: `build:` would overwrite
  # the avelren-app:latest tag that prod will come up from next time.
  # On a disposable machine there is no such tag — see section 12.
  migrate:
    image: ${STAND_APP_IMAGE:?STAND_APP_IMAGE not exported}
    command: ["python", "-m", "avelren.migrate"]
    mem_limit: 256m
    cpus: 0.5
    volumes:
      - ${WORK:?WORK not exported}/migrations-009:/migrations:ro

  api:
    image: ${STAND_APP_IMAGE:?STAND_APP_IMAGE not exported}
    command: ["python", "-c", "print('stand api placeholder')"]
    mem_limit: 512m
    cpus: 0.5

volumes:
  stand_db:
```

### Bench variables — via the environment, not via `.env`

Write `$WORK/stand/stand.env`, mode `0600`:

```
STACK=/opt/avelren
WORK=/var/lib/avelren-restore-rehearsal
STAND_APP_IMAGE=avelren-app:latest
AVELREN_STAND_GUARD=stand
STAND_ADMIN_PASSWORD=<bench, just generated>
STAND_MIGRATOR_PASSWORD=<bench>
STAND_BACKUP_PASSWORD=<bench>
STAND_COLLECTOR_PASSWORD=<bench>
STAND_NOTIFIER_PASSWORD=<bench>
STAND_WATCHDOG_PASSWORD=<bench>
STAND_API_PASSWORD=<bench>
```

```bash
chmod 0600 "$WORK/stand/stand.env"
```

And **in every session, before every command from the following steps**:

```bash
set -a; . "$WORK/stand/stand.env"; set +a
```

Generate passwords only from `[A-Za-z0-9]` (`openssl rand -hex 24`): they go
into the DSN without escaping, and a special character will silently corrupt the URI.

> **Why via the environment, and not via a `.env` in the bench directory.**
> `deploy/restore.sh` and `deploy/restore-verify.sh` have their own `compose()`
> wrapper, which passes only `-f` and `-p` — **without** `--project-directory`
> and **without** `--env-file`. Meanwhile the engine (`restore-engine.lib.sh`), before the
> call, does `cd "$AVELREN_STACK_DIR"`, i.e. into `/opt/avelren`. Where exactly
> Compose will look for `.env` in such a configuration — the directory of the compose file or the
> current one — depends on the version; you cannot rely on it, because the current one holds
> the **production** `.env`.
>
> Values from the shell environment take priority over any `.env` in any
> version of Compose. So we do not guess — we export. And the `:?` in the compose file
> makes the error loud: if the variables are not exported, Compose stops with
> an explicit message instead of silently substituting something from the production
> `.env`. The `/opt/avelren/.env` has no `AVELREN_STAND_GUARD` or
> `STAND_ADMIN_PASSWORD` keys — so there is nothing to substitute, and the scenario
> "the bench quietly took production values" is structurally impossible.

Verify the model before any run:

```bash
cd "$WORK/stand"
docker compose -f compose.yml -p avelren-rv3-86d3534 config >/dev/null
```

Must pass without warnings about empty variables.

---

## 6. Step 5 — bring up db and **prove isolation**

```bash
cd "$WORK/stand"
docker compose -f compose.yml -p avelren-rv3-86d3534 up --detach --wait db
```

Three proofs in a row (all must pass):

```bash
C="docker compose -f compose.yml -p avelren-rv3-86d3534"

# 1. the container reads the bench environment
$C exec -T db sh -c '[ "$AVELREN_STAND_GUARD" = stand ]' && echo GUARD-OK

# 2. no production variables in it
$C exec -T db sh -c '[ -z "$ECHERHA_DEVICE_ID" ] && [ -z "$AVELREN_API_DSN" ]' && echo NO-PROD-ENV

# 3. the production containers are untouched (none recreated)
docker ps --filter label=com.docker.compose.project=avelren \
          --format '{{.Names}}\t{{.Status}}'
```

The third output must show the same uptime as before the start. If any
production container is seconds old — **stop immediately**: this is a recurrence of the
2026-08-14 incident.

---

## 7. Step 6 — roles in the bench

We run `postgres-bootstrap.sh` **inside** the db container: `psql` is there, and
the checkout is mounted there too.

```bash
cd "$WORK/stand"
set -a; . ./stand.env; set +a

AVELREN_ADMIN_DSN="postgresql://avelren_admin:$STAND_ADMIN_PASSWORD@localhost:5432/postgres" \
AVELREN_ADMIN_PASSWORD="$STAND_ADMIN_PASSWORD" \
AVELREN_MIGRATOR_PASSWORD="$STAND_MIGRATOR_PASSWORD" \
AVELREN_BACKUP_PASSWORD="$STAND_BACKUP_PASSWORD" \
AVELREN_COLLECTOR_PASSWORD="$STAND_COLLECTOR_PASSWORD" \
AVELREN_NOTIFIER_PASSWORD="$STAND_NOTIFIER_PASSWORD" \
AVELREN_WATCHDOG_PASSWORD="$STAND_WATCHDOG_PASSWORD" \
AVELREN_API_PASSWORD="$STAND_API_PASSWORD" \
docker compose -f compose.yml -p avelren-rv3-86d3534 exec -T \
  -e AVELREN_ADMIN_DSN -e AVELREN_ADMIN_PASSWORD \
  -e AVELREN_MIGRATOR_PASSWORD -e AVELREN_BACKUP_PASSWORD \
  -e AVELREN_COLLECTOR_PASSWORD -e AVELREN_NOTIFIER_PASSWORD \
  -e AVELREN_WATCHDOG_PASSWORD -e AVELREN_API_PASSWORD \
  -e AVELREN_DB_NAME=restore_test -e AVELREN_TEST_DB=1 \
  db bash /workspace/deploy/postgres-bootstrap.sh fresh
```

Expected tail of the output: `migrate_handoff`, then
`postgres bootstrap complete: fresh`.

What exactly happens here and why it is the same **ownership topology** that
`restore-engine.lib.sh` talks about:

- `db/security/bootstrap.sql` creates 7 roles; `avelren_admin` — `LOGIN SUPERUSER`, the rest — `NOINHERIT NOBYPASSRLS`, **without any membership** between them (the script also checks this and fails if a membership appeared);
- `create_database` creates `restore_test` with `OWNER avelren_admin`;
- `provision_extension` installs `timescaledb` **as `avelren_admin`** → the extension owner is `avelren_admin`;
- `apply_acl` makes `avelren_admin` the owner of the database and the `public` schema, removes rights from `PUBLIC` and grants `CONNECT`/`USAGE` to the seven roles;
- `verify_owners` fails if the owner of the database, schema or extension is not `avelren_admin`.

These three owners — the database, `public`, `timescaledb` — are exactly the precondition without
which `restore_application_owners` throws an exception. The bench does not "have seven roles";
the bench **reproduces the topology**.

> Step 7 will now drop and recreate `restore_test` from scratch. This is not wasted work:
> the engine does `createdb`/`CREATE EXTENSION` as `avelren_admin` too, so the
> topology is preserved, and the roles and their passwords — the thing this step
> exists for — survive the recreation of the database.

### 6a. The legacy role — mandatory on the production artifact

If step 2a showed the name `avelren` in the dump (without a suffix) — and on the production
artifact it will show it — create the role in the bench **before** the restore:

```bash
PGPASSWORD="$STAND_ADMIN_PASSWORD" \
docker compose -f compose.yml -p avelren-rv3-86d3534 exec -T -e PGPASSWORD db \
  psql -U avelren_admin -d postgres -v ON_ERROR_STOP=1 -c \
  "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='avelren')
   THEN CREATE ROLE avelren NOLOGIN; END IF; END \$\$;"
```

> **The reason is not the grants.** It used to say here "otherwise
> `GRANT ... TO avelren` will break the load". That is wrong: there are zero grants in the production
> dump. The real reason is the **data**: in `COPY _timescaledb_config.bgw_job` the
> `owner` column contains the name of the role that owns Timescale background jobs. Without this
> role the load fails:
>
> ```
> CONTEXT:  COPY bgw_job, line 1, column owner: "avelren"
> primary restore failure (exit=3); attempting timescaledb_post_restore
> timescaledb_post_restore cleanup succeeded after primary failure
> ```
>
> The difference is not academic: an operator who read the old reason and saw
> zero grants in step 2a would reasonably decide the step is unnecessary — and
> would catch `exit=3` in the middle of a production window. Proven both ways on
> bench #3: without the role it fails, with the role 7→9 passes completely.

`NOLOGIN` is deliberate: the role is needed only as a bearer of the owner name; no one is supposed
to connect under it. The consequence is that Timescale background jobs in the bench will not
start (an owner without LOGIN). This is irrelevant to the verification; there is no need to
hunt for the cause.

---

## 8. Step 7 — the restore itself

```bash
cd "$WORK/stand"
AVELREN_STACK_DIR="$STACK" \
AVELREN_COMPOSE_FILE="$WORK/stand/compose.yml" \
AVELREN_COMPOSE_PROJECT=avelren-rv3-86d3534 \
AVELREN_DB_SERVICE=db \
AVELREN_ADMIN_PASSWORD="$STAND_ADMIN_PASSWORD" \
bash "$STACK/deploy/restore.sh" \
  "$WORK/artifact/$NAME" --target restore_test
```

`restore.sh` is the public CLI that **structurally** can only do `restore_test`:
any other target gets "direct production restore is forbidden". That is, this
command cannot touch `avelren` even through a typo.

The engine sequence (`deploy/restore-engine.lib.sh`): `dropdb --if-exists` →
`createdb` → `CREATE EXTENSION timescaledb` → `timescaledb_pre_restore()` →
`gunzip -c … | psql` → `timescaledb_post_restore()` → **ownership handoff** →
counters.

The expected tail is a table with four numbers:

```
 observations | checkpoints | hypertables | aggregates
```

Record them in the report. `observations` and `checkpoints` must be close to
production; `hypertables` = 1, `aggregates` = 1.

Immediately after this, record the schema version — it determines whether we
filtered the migrations correctly at step 3:

```bash
PGPASSWORD="$STAND_ADMIN_PASSWORD" \
docker compose -f compose.yml -p avelren-rv3-86d3534 exec -T -e PGPASSWORD db \
  psql -U avelren_admin -d restore_test -At -c \
  'SELECT max(version) FROM schema_migrations;'
```

Expected `009_observability`. If `010_postgresql_least_privilege` —
go back to step 3, put all ten files into `migrations-009`
(renaming the directory), and **skip step 8**.

---

## 9. Step 8 — the 010 grant layer (**bench only**)

The reason this step exists is concrete and verified against the code:

- the engine hands over ownership of application objects to the `avelren_migrator` role, so `schema_verify` under `avelren_migrator` works as the owner;
- but `avelren_api`, after restoring a schema-**009** dump, **has no rights at all** on the application tables — all grants for the runtime roles live in migration `010`;
- `restore_smoke` does `POST /devices`, i.e. an `INSERT` into `devices`. Without 010 it fails with `permission denied`, and this would be a **false red**: the artifact is intact, what is missing is the rights layer, which the production database does not yet have either.

```bash
PGPASSWORD="$STAND_ADMIN_PASSWORD" \
docker compose -f compose.yml -p avelren-rv3-86d3534 exec -T -e PGPASSWORD db \
  psql -U avelren_admin -d restore_test -v ON_ERROR_STOP=1 \
  -f /workspace/db/migrations/010_postgresql_least_privilege.sql
```

`avelren_admin` runs it; it is `SUPERUSER` — so it has the right to issue grants on
objects that already belong to `avelren_migrator`.

**This is `psql -f`, not `python -m avelren.migrate`.** The difference is fundamental:
`migrate` would record `010` into `schema_migrations`, and then the history would diverge
from the `migrations-009` directory. We deliberately apply the grants **without a stamp** —
exactly the combination that makes the bench suitable for verification without distorting
the history.

What this means for interpreting the result: step 9 proves that
**the data and the schema are intact, and the application works on them under the rights set that
3B.2 will bring**. It does **not** prove that the current production database already has these rights —
it does not have them, by design.

---

## 10. Step 9 — verification with the project's own tools

```bash
cd "$WORK/stand"
AVELREN_STACK_DIR="$STACK" \
AVELREN_COMPOSE_FILE="$WORK/stand/compose.yml" \
AVELREN_COMPOSE_PROJECT=avelren-rv3-86d3534 \
AVELREN_VERIFY_SCHEMA_SERVICE=migrate \
AVELREN_VERIFY_API_SERVICE=api \
AVELREN_VERIFY_MIGRATIONS_DIR=/migrations \
AVELREN_VERIFY_MIGRATOR_DSN="postgresql://avelren_migrator:$STAND_MIGRATOR_PASSWORD@db:5432/restore_test" \
AVELREN_VERIFY_API_DSN="postgresql://avelren_api:$STAND_API_PASSWORD@db:5432/restore_test" \
bash "$STACK/deploy/restore-verify.sh" restore_test
```

The host in the DSN is `db`, the service name: `run --rm` containers live in the network of the same
Compose project.

> The bench passwords are substituted into the URI without escaping, so they must be generated
> only from `[A-Za-z0-9]` (for example `openssl rand -hex 24`). A password with a
> special character will silently corrupt the DSN, and the error will look like "role does not exist".

Expected output:

```
>>> schema verification against restore_test
>>> disposable API smoke against restore_test
restore-verify OK: restore_test
```

What actually happened here:

- `restore-verify.sh` would refuse to work if `AVELREN_COMPOSE_PROJECT` were empty or equal to `avelren` — this is a structural safeguard after 2026-08-14, and here it works in our favor;
- both runs go with `--no-deps`, so `db` is not re-reconciled;
- `schema_verify` cross-checks the migration history (the list + SHA of each file) and the physical contract: tables, columns, partial unique indexes together with their predicates, named constraints, hypertables, continuous aggregates;
- `restore_smoke` brings up a real FastAPI application and passes `GET /health` (with an explicit requirement `last_observation != null`), `401` without authorization, `POST /devices` → **201**, and only then `GET /active-alerts`
with the obtained pair → `200`. Before all this, `restore_identity` cross-checks `current_database`, `current_user`, `session_user` and `system_user` — you cannot swap the target via URI parameters.

---

## 11. Step 10 — cleanup

```bash
cd "$WORK/stand"
docker compose -f compose.yml -p avelren-rv3-86d3534 down --volumes --remove-orphans

# the decrypted dump contains the fcm_token and secret_hash of all devices
rm -f "$WORK/artifact/$NAME" "$WORK/artifact/$NAME.sha256"

docker volume ls | grep avelren-rv3     # must be empty
docker ps -a   | grep avelren-rv3       # must be empty
git -C "$STACK" status --porcelain      # must be empty
```

`--volumes` here is not cosmetic: without it the `stand_db` volume stays on disk with
a full copy of the production data.

Next — what stays on disk after "cleanup", if it is not stated
explicitly:

```bash
shred -u "$WORK/stand/stand.env"   # the SEVEN bench passwords
rm -rf "$WORK/migrations-009"      # otherwise the directory outlives the bench and everyone forgets it
ls -la "$WORK" "$WORK/stand"       # only compose.yml must remain
```

> **This is `stand.env`, not `.env`.** A `.env` file in the bench directory is deliberately
> **not created** — precisely so that Compose has nothing to pick up from there (step 4).
> `shred -u` on a nonexistent file only complains to stderr and returns a
> nonzero code, while the seven passwords quietly stay put. Found by the run of
> bench #1.

---

## 12. Order: disposable bench → production host

1. **First** — on a disposable machine (where `docker compose` exists and there are no production containers by definition). Mistakes are allowed there.
2. Take the artifact **small and synthetic**: bring up a source DB with the same scripts and take a dump from it. The goal of the first run is to catch errors in the text, not to verify production data.
3. Record every divergence between the text and reality. Fix the document.
4. **Only then** — on the production host with the production artifact.

### 12a. What changes on a disposable machine

Three differences, and all three are in `stand.env`, not in the procedure text:

```
STACK=<path to the repository clone>
WORK=<directory outside the clone>
STAND_APP_IMAGE=avelren-app:stand
```

The `avelren-app:latest` image does not exist on such a machine — it must be built
**under a separate tag**, to avoid confusing it with the production one:

```bash
docker build -t avelren-app:stand "$STACK/app"
```

Step 1a (`docker image inspect avelren-app:latest`) is skipped there: it
verifies that the production image matches the prod pin, and locally that is pointless.

### 12b. The source DB for the synthetic artifact

`postgres-bootstrap.sh fresh` creates the roles, database, extension and ACLs — but
**does not apply the migrations**. The `migrate_handoff` in its output is literally
a `printf`, not an action. To have something to take a dump from, the migrations must be applied
separately:

```bash
docker compose -f compose.yml -p <bench-project> run --rm --no-deps -T \
  -e DATABASE_URL="postgresql://avelren_migrator:$STAND_MIGRATOR_PASSWORD@db:5432/<source_DB>" \
  migrate python -m avelren.migrate /migrations
```

On the production run this step is **absent** — there the schema comes from the dump.

### 12c. The runs — what each proved (2026-08-17)

| bench | question | result |
|---|---|---|
| **prod** | does the **production** artifact restore | **green**; found an access-rights defect that three benches missed |
| #1 | is the procedure executable at all | green; found 3 text defects (passwords not cleaned up, non-portability, `201` instead of `200`) |
| #2 | does the corrected revision work | green; the `:?` safeguards were falsified one variable at a time — all five refuse with an exact location |
| #3 | is step 8 enough on a **production-class** artifact (0 `GRANT`) | green; **`bgw_job` found** — step 6a is mandatory, the reason in the document was wrong |

Bench #3 answered the two questions that the production GO was being held up for:

- **step 8 alone is enough.** On an artifact with zero `GRANT`/`REVOKE`, step 7 loaded (242/2/1/1), 010 applied `rc=0`, and after it `avelren_api` reads `checkpoints`.
- **`USAGE` on `public` is present, and this is a measurement, not a theory.** `has_schema_privilege('avelren_api','public','USAGE')` = `t`; the source is inheritance from `PUBLIC` in the database the engine creates anew after `dropdb`. There is no need to extend 010.

Step 8 was falsified red on purpose: between 7 and 8 `avelren_api` gives
`ERROR: permission denied for table checkpoints`. The step is not decorative.

### 12d. Production run 2026-08-17 ~11:10–11:30 UTC

Artifact `avelren-20260817-032103.sql.gz`, 2,391,593 bytes, `gzip -t OK`,
digest `84af8c5df6fb9fb8e424b5a553cc21bdf47d6b35e43cdedaf5383e0fb692b8e2`,
sidecar missing (issue #93).

**The answer the rehearsal existed for:** `allowlist mismatch` did **not**
happen. The restore produced 522,082 observations, 38 checkpoints,
1 hypertable, 1 aggregate. A production restore today would have worked.

An independent check of the dump's completeness against the live database at the same moment:
540,246 observations, 38 checkpoints, the last at 11:20:03Z. The difference of 18,164 at
479 min × 38 checkpoints = 18,202 — a discrepancy of exactly 38, i.e. one polling cycle at
the edge of the interval. The dump is complete, the collector has no gaps.

Step 2a: 0 `GRANT`, 0 `REVOKE`, exactly two mentions of `avelren` — both in the `bgw_job`
data. Step 6a was needed, for exactly this reason.

Step 8 was falsified on real data: before it `avelren_api` →
`permission denied for table checkpoints`, after it — reads. The history stayed
`009_observability` / 9 records. Step 9: `schema is consistent: 9 migrations,
contract intact`, `restore-verify OK: restore_test`.

Prod was not touched: 6/6 containers with unchanged `CreatedAt` and uptime,
`avelren-db-1` id + `StartedAt` (`3428ddde…` / `2026-08-14T06:23:59.222Z`)
bit-for-bit the same before the bench came up, after it, and after the restore;
`git status` empty three times; health ok. No stop rule fired.
The decrypted dump and `stand.env` were destroyed with `shred` at step 10.

Recorded deviations in the prerequisites: `deploy/PROD_PIN` = `c84f531` while HEAD is
`86d3534` (PR #92 open); `AVELREN_GIT_SHA` in the image is empty — i.e. the
match of the production image to the pin is **unprovable**.

### 12e. Details of run #1

The finish was green:

```
schema_verify: schema is consistent: 9 migrations, contract intact
restore_smoke: prod-guard, health+observations, auth loop, devices/secret, protected request
restore-verify OK: restore_test
```

The restore produced 242 observations, 2 checkpoints, 1 hypertable, 1 aggregate — exactly
as in the source; the engine's allowlist matched, the ownership handoff worked.
Step 8 applied 010 without a stamp: the history stayed `009_observability`, 9 records.
The cleanup was clean.

Additionally — **falsification of the safeguards** (the procedure did not require this, but
before a production run it is the main thing): empty `AVELREN_COMPOSE_PROJECT` →
`REFUSED`, `rc=2`; project `avelren` → `REFUSED`, `rc=2`;
`restore.sh --target avelren` → `DENIED: direct production restore is forbidden`.
All three refuse correctly.

Minor: the Python 3.14 image emits a `StarletteDeprecationWarning` (httpx in
`starlette.testclient`) on the `restore_smoke` path. It does not appear on prod —
`restore_smoke` does not run there.

---

## 13. When it's red — what it means

| Message | Cause | What to do |
|---|---|---|
| `restore application relation allowlist mismatch: unexpected public.X` | there is an object in the production database that is not in the engine's allowlist | **A real finding.** The same would break a production restore too. Both `expected(...)` blocks in `restore-engine.lib.sh` and `_TABLES_V` in `schema_verify.py` must be reconciled; drift is caught by `deploy/restore-allowlist-contract-test.py` |
| `… mismatch: missing public.X` | the dump is incomplete, or the dump role did not have `SELECT` on X | **The worst possible result**: the backup is silently incomplete. Stop everything, sort out the `avelren_backup` rights |
| `restored application relations must be owned by avelren_admin before handoff` | the dump was not taken with `--no-owner`, or the restorer is not `avelren_admin` | cross-check step 2a and `AVELREN_ADMIN_PASSWORD` |
| `timescaledb extension owner must remain avelren_admin` | the extension was installed not by `avelren_admin` | step 6 was not performed fully (`provision_extension`) |
| `is in the files but not recorded as applied` | step 3 was skipped or the directory is wrong | rebuild `migrations-009` |
| `migration NNN: SHA in the DB does not match the file` | the migration file was edited **after** it was applied | a separate incident; stop the rehearsal |
| `permission denied for table devices` in the smoke test | step 8 was skipped | apply 010 and repeat step 9 |
| `REFUSED: disposable restore verification requires an explicit non-production Compose project` | `AVELREN_COMPOSE_PROJECT` not set | this is intended; set the bench project |
| `REFUSED: restore verification must not run in the production Compose project` | the project was named `avelren` | rename it; this is the 2026-08-14 safeguard |
| `DENIED: direct production restore is forbidden` | `--target` is not `restore_test` | this is intended |
| `/health returns last_observation=null` | the schema is intact, there is no data | the dump is empty or only structures were restored |
| `primary restore failure … timescaledb_post_restore cleanup succeeded` | the dump did not load, but Timescale was cleaned up correctly | look at the root cause higher up in the log; the cleanup itself worked correctly |
| `is recorded but the file is missing (foreign/future version)` ×9 | `/migrations` in the container is **empty**: the `$WORK` directory is inaccessible to uid 10001 | not the dump. Fix the modes (`$WORK` → `0701`, `migrations-009` → `0755`, files `0644`) and repeat **step 9 only** — there is no need to redo the restore |
| `CONTEXT: COPY bgw_job, line N, column owner: "<role>"`, then `exit=3` | the bench has no role that owns Timescale background jobs | step 6a was skipped. Create the role, repeat step 7 from the start |
| the script "breaks off" after the very first `compose exec -T` | `-T` passes stdin through, and `exec` eats the rest of the script that bash reads from the same stdin | add `</dev/null` to every `compose exec -T` that should not receive input (all except loading the dump). Found on prod 2026-08-17 |

---

## 14. Backup-script drift — measured 2026-08-17

The question this started from: `backup.sh:36` requires the `avelren_backup` role,
the grants for it are introduced only by `010`, prod is at `009` — yet the nightly run at
03:21Z is successful and produced 2,391,593 bytes. There were three hypotheses: a manual grant of rights,
a role attribute, a leftover of the 14 August forward.

**All three refuted.** A read-only look at prod showed: `avelren_backup` is not
`SUPERUSER` and not `BYPASSRLS`; there are zero memberships between the `avelren%` roles; there are
no grants at all. In particular this means that the **14 August inverse rollback came off
completely** — the canonical graph is intact.

The real cause is in a different layer. The systemd unit runs not the repository's
`deploy/backup.sh`, but a separate `/usr/local/sbin/avelren-backup` (root:root 750, from
7 August), which takes the dump under the legacy `avelren`. The `avelren_backup` role is
**not involved at all** in the production backup path.

What is missing in the deployed version compared to the repository one:

| | repo `deploy/backup.sh` | deployed `/usr/local/sbin/avelren-backup` |
|---|---|---|
| role | `avelren_backup` (fails if another) | legacy `avelren` |
| `.sha256` sidecar | creates and cross-checks via `rclone cat` | **does not create** |
| `gzip -t` after the dump | yes | no (only "≥ 10240 bytes") |
| digest/size cross-check after upload | yes | no |
| guarantee that the remote is of type `crypt` | preflight, fail-closed | **does not check** |

Why this matters here specifically: `AVELREN_RECOVERY_PREFLIGHT_FILE` contains the line
`backup_recovery=PASS`, and until it is clear what exactly it attests — the repository
script or the deployed one — this is a signature under an assumption. This section removes the
assumption: it must be signed knowing that the **deployed** version, with the
listed relaxations, is what works.

What this does **not** call into question: the backups are healthy and running. 16.08 is Sunday
(`DOW=7`), so the artifact went to `weekly/`, there is no gap. The sizes grow
plausibly (1.65 MB 14.08 → 2.39 MB 17.08). The absence of `monthly/`
is explained by the calendar, not by a defect: the script was installed on 7 August, and the first
of the month has not occurred since then — the first opportunity will be 1 September.

Fixing the drift is a separate task, not part of this procedure.

---

## 15. What next for this document

After a successful run **on the production host** — fold it into
`docs/disaster-recovery.md` as a separate "Restore rehearsal" section, with the actual
numbers of the run. Until then the document lives separately: folding into the canonical runbook
a procedure that no one has performed yet is exactly the mistake through which B2
failed last time.

Next on the plan is B3 (evidence), and only then 3B.2.
