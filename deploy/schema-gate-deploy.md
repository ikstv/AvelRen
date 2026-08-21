# Deploy: schema startup gate (#88)

> **This is the first application deploy documented in the project.** No
> procedure existed: `deploy/` held only the adoption runbook and
> `telemetry-isolation-deploy.md` about one specific change. This document is
> derived from that template, adjusted for what changed after Gate 11 3B.2.
>
> **A merge does not activate the gate. This deploy does.** Before it, prod runs
> the old code and none of the #88 checks work on the live system.
>
> **Version this text describes.** This runbook describes the image built from
> `12ade41` and later. On `2e74ae7` (the currently deployed image, pre-i18n) the
> gate line in the logs is the Ukrainian `схема узгоджена зі стартовою вимогою:
> 009_observability` — grepping `schema meets startup requirement` there returns
> nothing. If the acceptance grep in §6.2a finds no lines, first check which
> commit prod actually runs (`AVELREN_GIT_SHA`, `PROD_PIN`).

---

## 0. What it does and what it risks

**Does:** rebuilds `avelren-app:latest` from a new commit and restarts the four
services, which from then on verify the schema version at startup.

**The risk, and it is total:** the gate is fail-closed and lives in **every** one
of the four services. A wrong gate means not the degradation of one function but
a **refusal of the entire runtime to start**. That is why rollback is decided
**before** the build, not after a failure.

**The code delta is minimal.** Measured 2026-08-17: the last commit touching the
image contents (`app/src`, `app/pyproject.toml`, `app/Dockerfile`) is `9400a8d`
from 08-15 — that is, **earlier** than the current image's build (08-16 07:26Z).
So this deploy adds exactly one change to the running code — the gate itself.

---

## 1. Prerequisites — access

- `root`/sudo on the live host; `docker` under `sudo`;
- `/opt/avelren` — checkout on `main`, **clean tree**;
- there is **no** separate deploy script on the host (measured: `/usr/local/sbin/`
  holds only `avelren-backup`, `avelren-restore`, `avelren-telemetry-snapshot`).
  The deploy is manual — this document is the procedure.

---

## 2. The main trap: `-f docker-compose.yml`

The host holds `docker-compose.override.yml` — **root-owned, outside git**
(`.gitignore`), an artifact of the 2026-08-14 incident. It does two things:

1. forces `DATABASE_URL` (the legacy superuser) for `collector`, `notifier`,
   `watchdog`, `api` — which is why the runtime is still on the legacy connection
   even though ownership is already on seven roles;
2. mounts the `migrate` directory `/var/lib/avelren-migrate-pin-009` as
   `/migrations` (ro) — this is the `001–009` pin, put in place after 3B.2.

**Naming the compose file disables auto-discovery**, and with it the override.
The consequence is twofold and silent: `migrate` would see the repository `010`
and **stamp it out of 3D order**, and the four services would try the per-role
DSN the prod is not switched to yet, and **fail to come up**.

So in all the commands below **`-f` is not used at all** — we rely on the default
auto-load of `base + override`. `--no-deps` is the second belt, not the first.

---

## 3. Baseline — capture and record

```bash
cd /opt/avelren
git rev-parse HEAD; git status --porcelain
sudo docker ps --format '{{.Names}}\t{{.CreatedAt}}\t{{.Status}}'
sudo docker image inspect avelren-app:latest --format '{{.Id}} {{.Created}}'
curl -fsS https://api.bordersignal.pp.ua/api/health
sudo docker compose exec -T db psql -U avelren -d avelren -At \
  -c 'SELECT max(version) FROM schema_migrations'
```

The last line must return `009_observability`. This number is needed at
acceptance: it **must stay the same** after the deploy.

### 3.1 Prove the override is active — before the build

The whole procedure rests on the default auto-load picking up
`docker-compose.override.yml`. But it is machine-local and outside git — i.e. it
disappears **silently**, and none of the safeguards in section 2 catch that:
`--no-deps` will not restore the pin, and the absence of `-f` will not restore
the legacy DSN if there is nothing to restore.

```bash
( set -o pipefail
  sudo docker compose config | grep -E 'avelren-migrate-pin-009|DATABASE_URL' \
    | sed -E 's#(postgresql://[^:]+):[^@]*@#\1:***@#g'
) || echo "STOP: override not active or compose model invalid"
```

Empty → **stop before the build**. This catches a missing override at the
cheapest point — instead of finding out through a restart loop of the four
services or, worse, through a silent `010` stamp.

---

## 4. Rollback — decided NOW, before the build

The `telemetry-isolation-deploy.md` template rolls back by rebuilding from the
old commit. Under pressure that is minutes you do not have, and it moves the
checkout. Instead — save the image:

```bash
sudo docker tag avelren-app:latest avelren-app:pre-88
sudo docker image inspect avelren-app:pre-88 --format '{{.Id}}'   # = Id from the baseline
```

Rollback is then seconds, without a rebuild:

```bash
sudo docker tag avelren-app:pre-88 avelren-app:latest
sudo docker compose up -d --force-recreate --no-deps api collector notifier watchdog
git checkout 86d3534        # move the checkout back too; return to main as an explicit step
```

**Do not skip `git checkout` on rollback.** Otherwise the checkout stays ahead of
the image — exactly the divergence we discussed today, the one that makes
`PROD_PIN` lie.

---

## 5. Deploy

```bash
cd /opt/avelren
git pull                      # main -> new head
git rev-parse HEAD            # record: this is the future PROD_PIN
git status --porcelain        # MUST be empty

export SOURCE_COMMIT=$(git rev-parse HEAD)
sudo -E docker compose build migrate     # the same avelren-app:latest image
```

> **`sudo -E` is mandatory.** Without it sudo strips the env, `SOURCE_COMMIT` does
> not reach it, and `AVELREN_GIT_SHA` stays empty — exactly what we measured on
> the current image (empty both in env and in the layers: provenance
> unrecoverable).

**Check provenance BEFORE the restart** — this is the cheapest failure point:

```bash
sudo docker image inspect avelren-app:latest \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep AVELREN_GIT_SHA
```

Must show the full SHA of the new commit. Empty — **stop**, `-E` did not work;
there is no point restarting yet.

Then — the four services:

```bash
sudo docker compose up -d --force-recreate --no-deps api collector notifier watchdog
```

We do not touch `caddy`: none of our code is in it.

---

## 6. Acceptance — five checks, all mandatory

```bash
# 1. no service in a restart loop
sudo docker compose ps

# 2a. the gate ran in the three that configure logging themselves
for s in collector notifier watchdog; do
  echo "== $s"; sudo docker compose logs --no-color --tail 50 "$s" | grep -i 'schema meets startup requirement'
done

# 2b. api — a different proof, stronger than a log line (see below)
curl -fsS https://api.bordersignal.pp.ua/api/health >/dev/null && echo "api serving => gate passed"

# 3. HTTPS alive
curl -fsS https://api.bordersignal.pp.ua/api/health

# 4. 010 NOT stamped — proof that migrate did not run
sudo docker compose exec -T db psql -U avelren -d avelren -At \
  -c 'SELECT max(version) FROM schema_migrations'      # must be 009_observability

# 5. collector still writing
sudo docker compose exec -T db psql -U avelren -d avelren -At \
  -c "SELECT max(time) FROM collector_runs"
```

Check 2 is the key one: it is what distinguishes "the service came up" from "the
gate ran". A missing line in `collector`/`notifier`/`watchdog` means the service
started from the old image — the very silent divergence the gate exists to catch.

> **Why you cannot — and need not — look for the line in `api`.** `api.py` does
> not call `logging.basicConfig`: logging there is configured by uvicorn, which
> configures only its own loggers and leaves root without a handler at INFO. So
> the gate's `log.info` will not appear in `api`'s logs **even when the gate
> ran** — and looking for the line would give a false "stop" on a healthy service.
>
> Instead, for `api` there is a stronger proof: the gate is called in `lifespan`
> **before** `yield`. If it raises, startup fails and uvicorn exits — the
> container goes into a restart loop and check 1 catches it. So **the fact that
> `/api/health` returns 200 by itself means the gate passed**. This is not a
> weakening of the check but a shift from evidence (a log) to a consequence (the
> service serving).

Check 4 is proof that `--no-deps` worked and `migrate` was not pulled in.

---

## 7. Stop rules

Roll back (section 4) immediately if:

- any of the four is in `Restarting` for more than one attempt;
- `/api/health` does not respond for more than 2 min after start;
- `max(version)` became `010_*` — `migrate` did run, and that is no longer only
  about the deploy;
- the gate's logs show `SchemaTooOldError` — the gate considers the schema too
  old, and until the cause is known the runtime matters more than the check.

`docker compose down`, `restart` without `--no-deps`, and any bare `up -d` —
**do not do**, under any circumstances, including panic.

---

## 8. After acceptance

1. **Update `PROD_PIN` to the new commit** — in a separate PR, as #92 did. Not
   before acceptance: a pin ahead of the proven state is worse than a stale one.
2. Keep the `avelren-app:pre-88` image **at least** until the end of the
   observation period. Remove it as a deliberate step, not with `image prune`.
3. Record in the report: the new `AVELREN_GIT_SHA` (now non-empty — this closes
   part of the #93 class), and that `max(version)` stayed `009_observability`.

**What not to do after:** PR 2 (put `migrate` back behind a profile,
`required: false`, remove the `001–009` pin) — a separate decision after the gate
has run on prod for a while. Removing the pin on the same day you first ran what
is meant to replace it is removing the safety net before you are sure of the
replacement.

---

## 9. What this deploy changes for Gate 11

It moves the checkout, and thus `PROD_PIN`, and thus rebinds the
`evidence ↔ repo ↔ runner` triple. The 3B.2 evidence (`evidence-3b2-86d3534-…`)
after this remains valid only as a historical record: any future adoption will
require evidence on the new commit.

**Decision: this deploy is done SEPARATELY from the 3C re-prep, and does not wait
for it.**

The temptation to fold them into one window exists, and the argument for it is
obvious — the pin moves once instead of twice. The argument is weak, and it is
deliberately rejected:

- moving the pin costs one line and one PR — not the kind of saving worth
  coupling anything for;
- coupling ties a **reversible** change (the image; rollback by tag in seconds)
  to an **irreversible** one (the DSN cutover with a catalog mutation), i.e. it
  imports the risk of the second into the first;
- there is no saving on evidence even in theory: 3C will need fresh evidence on
  its then-current commit whenever it happens;
- 3C is weeks of project work (there is no production cutover mode, one of six
  gates is implemented, `collector_freshness` needs a redesign). Waiting for it
  means leaving the gate idle and making the `001–009` pin — a temporary crutch —
  permanent.

The 3B.2 experience says the same: it succeeded because it did one thing.
