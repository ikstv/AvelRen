# Rules for agents and developers

## 1. Clients never reach eCherha

Only the `collector` service talks to `echerha.gov.ua` / `back.echerha.gov.ua`.
Never the web front-end, the mobile app, the user's browser, or any third-party
script.

If a client is missing data, we **extend our own API** — we do not let the client
reach out directly. Forbidden: a proxy endpoint that forwards a request to
eCherha; a "temporary" fetch from the front-end; an SDK that talks to it
directly.

Reason: `x-ratelimit-limit: 60` on the government service's side. Distributed
client requests exhaust the limit and lead to IP bans.

## 2. Exactly 60 seconds

The polling interval is 60 seconds between the **starts** of cycles, not
`sleep(60)` after the work is done (otherwise the interval drifts). No more
often: this is a government service, we are guests here. No less often: the data
changes within a minute.

## 3. Do not lose observations

We record every poll, with no deduplication. A gap in the time series cannot be
recovered later — the source of history keeps nothing.

Every cycle is recorded in `collector_runs`, including the failed ones. A silent
failure is worse than a loud one.

## 4. Source errors are not our outage

On `429`/`5xx`/timeout: skip the cycle, record the reason, wait for the next one.
Do not retry aggressively, do not shorten the interval, do not raise concurrency.

## 5. Schema changes only via migration

A new file `db/migrations/NNN_description.sql`, with a sequential number. The
`migrate` service applies them itself before `collector` and `api` start.

**Do not edit an already-applied migration** — the applier compares sha256 and
will stop with an error. If a fix is needed, write a new migration.

## 6. Secrets never land in git

`.env` is in `.gitignore`. The repository holds only `.env.example` with empty
values.

## Scope right now

Trucks only (`/workload/1`, `for_vehicle_type: 1`). Buses (`/workload/2`) are
deliberately left alone until there is a decision.

## 7. A forecast does not replace a measurement

`entry_eta` is a fact from the primary source (the moment of measurement +
`wait_time`), and that is exactly why it can be trusted. When a forecast appears
(see `docs/forecast.md`), it must be a **separate field with a separate name**.
The user must always be able to see where the measurement is and where the guess
is.

## 8. Backups

Daily at 03:20 UTC, via the `systemd` timer `avelren-backup`. The dump is
encrypted before being uploaded (`rclone crypt`) — it contains devices' FCM
tokens, and it travels to someone else's cloud. The key stays on the server.

Schedule: 7 daily, 4 weekly, 3 monthly.

**Restore only via `avelren-restore`.** A plain `psql` on a TimescaleDB dump
throws errors on hypertables and compression: you need
`timescaledb_pre_restore()` before and `timescaledb_post_restore()` after.

By default the script restores into `restore_test`, not into the live database.

## 9. The app's design is ROAD SIGN, and it lives in `main`

The canonical design is **ROAD SIGN** — signal semantics borrowed from road
signs: green `#0E7A4E` "go", yellow `#F5C400` "attention" (the de facto brand
colour), red `#D5382C` "closed". Tokens live in
`android/app/src/main/java/ua/avelren/app/ui/theme/Color.kt`, which is the
source of truth; the HTML under `design-system/` follows it, not the reverse.

If you find `AvelRedLight = 0xFFEC3013` anywhere, you are looking at the old
Modernist design. It was deleted on 2026-08-20 (PR #106) and is not canonical.

**`design-system/ds/screens/` holds one screen out of ten.** The other nine
exist only as Compose code in `ui/AvelRenScreen.kt`. Do not conclude from the
design system alone that you have seen the app. See `docs/design.md`.

Reason: until 2026-08-20 the working design lived in an unmerged branch while
`main` carried a completely different one. That drift cost a full investigation
(comparing an APK pulled off the device by sha256) and nearly cost the wrong
deletion. Keep the design in `main` and the confusion cannot come back.

## 10. Build the device APK only from a clean `main`

The APK installed on a phone must come from the clean tip of `main` — never
from a feature branch:

```
git status          # tree must be clean
cd android && ./gradlew assembleDebug
```

Record what was installed in `dist/BUILD.txt`: sha256, commit, date. Verify by
pulling the installed `base.apk` back off the device and comparing hashes —
"looks the same" is not the same as "is the same".

`dist/` is in `.gitignore` (the APK is ~20 MB), so that record does not travel
between machines. The commit hash in it is what makes the build reproducible
elsewhere.

Reason: the drift described in rule 9 began with an APK built from a branch.
