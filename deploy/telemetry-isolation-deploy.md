# Deploy: telemetry isolation (SEC-1 / A-01)

This PR removes the public API container's access to `/secrets`, `/proc`, `/run`.
Instead, a host timer writes a JSON snapshot to `/var/lib/avelren-telemetry/host.json`,
which the API mounts read-only.

`telemetry.py` deliberately **has no fallback** to the old paths: the API survives
a missing snapshot by showing `stale: true` and a synthetic problem
`telemetry_snapshot_stale` in the problem list. This means a broken timer is a
visible but **non-critical** situation: it can be fixed without restoring the
dangerous mounts.

## Deploy order (on the live server)

**The order of the steps matters.** Before `git pull`, the `deploy/telemetry-*` files
do not physically exist on the server — they arrive with this very PR. So the pull comes first;
it changes only the checkout and does not touch running containers.

```bash
cd /opt/avelren

# 1. First fetch the PR itself — otherwise the install below won't find the files.
git pull --ff-only origin main

# 2. Host-side snapshot pipeline.
sudo install -o root -g root -m 0755 \
    deploy/telemetry-snapshot.sh /usr/local/sbin/avelren-telemetry-snapshot
sudo install -o root -g root -m 0644 deploy/avelren-telemetry.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/avelren-telemetry.timer   /etc/systemd/system/

sudo mkdir -p /var/lib/avelren-telemetry
sudo systemctl daemon-reload
sudo systemctl enable --now avelren-telemetry.timer

# 3. First run synchronously, so the file exists BEFORE the new API starts.
sudo systemctl start avelren-telemetry.service
sudo systemctl status --no-pager avelren-telemetry.service
test -s /var/lib/avelren-telemetry/host.json && echo "snapshot OK"

# 4. Rebuild the image and bring up the API with the new mounts.
#    SOURCE_COMMIT is baked into the image as AVELREN_GIT_SHA and ends up in
#    /admin/telemetry.version.git_sha (Server Dashboard, PR-B). Without this
#    line the client will forever see "⚪ unknown" in "Server commit".
#    `sudo -E` is required — without it sudo strips the env.
export SOURCE_COMMIT=$(git rev-parse HEAD)
sudo -E docker compose build migrate       # the same avelren-app:latest image
sudo docker compose up -d --force-recreate api

# 5. Prove that the isolation actually happened.
sudo docker compose exec api ls -la /telemetry            # host.json must be here
sudo docker compose exec api ls /secrets 2>&1 || echo "no secrets — exactly right"
curl -sS https://api.bordersignal.pp.ua/api/health
```

Step 5 is the PR's acceptance test: a shell inside the API container no
longer sees the Firebase service-account.

## If the snapshot does not update

**A security rollback is not needed for this.** The API works with a stale snapshot:
queues, subscriptions, ETA and notifications do not depend on host metrics. `/admin/telemetry`
will show the `telemetry_snapshot_stale` problem. So the timer can be fixed calmly:

```bash
systemctl list-timers avelren-telemetry.timer   # is there a next run
journalctl -u avelren-telemetry.service -n 50 --no-pager
sudo /usr/local/sbin/avelren-telemetry-snapshot && echo "manual run ok"
```

Restoring `./secrets`, `/proc`, `/run` into the public container for the sake of telemetry
is exactly the trade-off this PR undoes. Do not do it.

## Full release rollback

Needed only if the new image breaks the API itself (not the telemetry). Reverting
**docker-compose.yml alone is not enough**: the image has already been rebuilt with the new
`telemetry.py`, which reads only `/telemetry`. The old compose would restore the
dangerous mounts and still not restore telemetry — worse than either state.

You have to roll back the whole release, together with the image:

```bash
cd /opt/avelren
sudo systemctl disable --now avelren-telemetry.timer

git checkout be67641bae82a71151d0693eaee3e6b46f684b3d   # base of this PR
sudo docker compose build migrate                        # image with the old code
sudo docker compose up -d --force-recreate api

sudo docker compose exec api ls /secrets                 # visible again — expected
```

After this, `main` and the server diverge, so make returning to the current `main`
an explicit step (`git checkout main && git pull`), rather than forgetting it.

## What is NOT part of this PR

Deliberately out of scope (separate PRs in their own order):

- `notifier`/`watchdog` `./secrets:/secrets:ro` — stays, because they genuinely need the
  Firebase service-account for FCM. This is a legitimate use, not cruft.
- A-02 notification lifecycle (ongoing notifications after a server-side expire).
- OBS-1/2 secondary pipeline observability.
- DR + A-07 fail-closed migration bootstrap.
- DB least privilege.
- HTTP-1 Caddy :80 cleartext.
