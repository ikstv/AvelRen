#!/usr/bin/env bash
#
# Captures host state into a single JSON file for the API container.
#
# The goal is to pull the API out of the host's trust boundary. Previously the public
# FastAPI container mounted /secrets, /proc and /run so that /admin/telemetry could show
# load and disk usage; as a side effect, an RCE or path traversal in the API would gain
# access to the Firebase service-account.json (audit SEC-1 / A-01).
#
# Now root on the host takes the snapshot, and the API only reads the already-assembled JSON.
# No secrets, no /proc, no /run inside the container.
#
# The file is written atomically (write to .tmp → rename), so a reader never sees a
# half-written state. Time is ISO-8601 UTC; the API checks freshness and shows
# "stale" if the snapshot is older than 5 min.
#
set -euo pipefail

OUT_DIR=/var/lib/avelren-telemetry
OUT=$OUT_DIR/host.json
TMP=$OUT.tmp
FS_PROBE=${AVELREN_FS_PROBE:-/opt/avelren}
API_HOST=${AVELREN_CERT_HOST:-api.bordersignal.pp.ua}
# Overridden only in CI, to exercise interface filtering against a
# synthetic file — we must test this script, not a copy of it in the workflow.
NET_DEV=${AVELREN_NET_DEV:-/proc/1/net/dev}
# Overridden only in CI, to exercise the apt-check logic itself (null /
# valid output / nonzero exit) against a synthetic probe.
APT_CHECK=${AVELREN_APT_CHECK:-/usr/lib/update-notifier/apt-check}
# The compose stack and the migration pin the override is expected to mount
# (issue #160). Both overridable so the check can be exercised in CI against a
# synthetic stack instead of the real one.
STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
MIGRATE_PIN_PATH=${AVELREN_MIGRATE_PIN_PATH:-/var/lib/avelren-migrate-pin-009}

mkdir -p "$OUT_DIR"

# --- system ---
read -r load1 load5 _rest < /proc/loadavg
uptime_seconds=$(awk '{print int($1)}' /proc/uptime)
cpu_count=$(nproc)

mem_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
mem_avail_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
swap_total_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
swap_free_kb=$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)

# statvfs of the host itself via df — requires no mounts into the container.
read -r _fs disk_total_1k disk_used_1k disk_avail_1k _rest < <(
    df -Pk "$FS_PROBE" | tail -1
)

reboot_required=false
reboot_pending_days=null
if [ -e /run/reboot-required ]; then
    reboot_required=true
    now=$(date +%s)
    mtime=$(stat -c %Y /run/reboot-required)
    reboot_pending_days=$(( (now - mtime) / 86400 ))
fi

# Available package updates. `reboot_required` only reflects the consequence of an
# already-installed kernel — the pending updates themselves (especially security ones)
# were not visible at all until this point, so the only way to learn about them was to
# log into the host by hand.
#
# We count them via apt-check: it reads the already-downloaded package lists and does
# not go out to the network, so it's safe for a per-minute timer (unlike
# `apt-get update`). Output format is "regular;security" on stderr.
# 0 and null differ here: 0 = checked, no updates; null = the check could not be
# performed (no apt-check, broken output, nonzero probe exit). Showing
# "none" instead of "unknown" would be lying about host state, so the default is null.
updates_pending=null
updates_security=null
if [ -x "$APT_CHECK" ]; then
    # apt-check writes "regular;security" to stderr. `|| raw=""` is the same
    # fail-safe as for openssl below: the probe must not be a single point of failure.
    # Under `set -euo pipefail`, a nonzero exit of apt-check (and update-notifier
    # has had such scenarios) would otherwise bring down the whole snapshot before validation.
    raw=$("$APT_CHECK" 2>&1 | tr -d '[:space:]') || raw=""
    # Only a valid "N;M" yields numbers; anything else leaves null.
    if printf '%s' "$raw" | grep -qE '^[0-9]+;[0-9]+$'; then
        updates_pending=${raw%%;*}
        updates_security=${raw##*;}
    fi
fi

# --- network (RX/TX via host PID 1) ---
#
# Parsed with awk rather than bash substitutions: in /proc/net/dev the interface
# names are space-aligned ("    lo:"), and ${name## } strips exactly one
# space, so the lo/docker*/br-*/veth* filter silently failed and local and
# docker traffic ended up in the external counter.
#
# `index($0, ":")` splits exactly on the colon — this survives even long interface
# names that run into the first number. `split(rest, f, " ")` with a
# single-space separator uses awk's default semantics: it trims the
# edges and splits on runs of whitespace. f[1]=rx_bytes, f[9]=tx_bytes.
rx_total=0
tx_total=0
if [ -r "$NET_DEV" ]; then
    read -r rx_total tx_total < <(
        awk 'NR > 2 {
            idx = index($0, ":")
            if (idx == 0) next
            name = substr($0, 1, idx - 1)
            gsub(/[ \t]/, "", name)
            if (name == "lo") next
            if (name ~ /^docker/ || name ~ /^br-/ || name ~ /^veth/) next
            rest = substr($0, idx + 1)
            n = split(rest, f, " ")
            if (n < 9) next
            rx += f[1]
            tx += f[9]
        }
        END { printf "%d %d\n", rx + 0, tx + 0 }' "$NET_DEV"
    )
fi

# --- inodes ---
# The disk may be at 20% by bytes but 100% by inodes — and create() will start
# returning ENOSPC even though df -h suspects nothing. Hence a separate section.
inodes_total=null
inodes_used=null
inodes_used_percent=null
if inodes_line=$(df -Pi "$FS_PROBE" 2>/dev/null | tail -1); then
    # `df -Pi` format: Filesystem Inodes IUsed IFree IUse% Mounted
    read -r _fs inodes_total inodes_used _ifree ipct _rest <<< "$inodes_line"
    inodes_used_percent=${ipct%\%}
    # If any of the numbers is not a number (e.g. "-" for tmpfs) — leave null.
    case "$inodes_total" in ''|*[!0-9]*) inodes_total=null ;; esac
    case "$inodes_used"  in ''|*[!0-9]*) inodes_used=null  ;; esac
    case "$inodes_used_percent" in ''|*[!0-9]*) inodes_used_percent=null ;; esac
fi

# --- docker daemon / compose version ---
# `docker version --format` has no format variant that returns
# just a single line with the server version; --format '{{.Server.Version}}' is exactly
# what we need. A nonzero exit (docker daemon not running) → null, rather than
# taking down the whole snapshot.
docker_daemon_version=null
docker_compose_version=null
if command -v docker >/dev/null 2>&1; then
    if v=$(docker version --format '{{.Server.Version}}' 2>/dev/null); then
        [ -n "$v" ] && docker_daemon_version="\"$v\""
    fi
    if v=$(docker compose version --short 2>/dev/null); then
        [ -n "$v" ] && docker_compose_version="\"$v\""
    fi
fi

# --- migrate pin still mounted? (issue #160) ---
# The 001-009 pin that keeps `migrate` from seeing 010 lives in
# docker-compose.override.yml on the host — machine-local, outside git. It fell
# out silently during the #88 window, and nothing noticed: the runbook's
# precondition catches it, but that is only ever run during a deploy, so the
# guard was unprotected exactly between the windows where it matters.
#
# `false` here means the model resolves /migrations to something other than the
# pin, which is the state where any profiled `up` stamps 010 out of the 3D order.
# `null` means we could not tell (no docker, no stack dir) — deliberately NOT
# `false`: a snapshot that cannot look must not raise an alarm it has not earned.
#
# Cost is one `docker compose config` per snapshot. It parses two small local
# files; the alternative — grepping the override by hand — would answer about
# the file rather than about the model compose actually uses, and the model is
# what stamps migrations.
migrate_pin_active=null
if command -v docker >/dev/null 2>&1 && [ -d "$STACK_DIR" ]; then
    if model=$(cd "$STACK_DIR" && docker compose --profile migrate config 2>/dev/null); then
        if printf '%s' "$model" | grep -qF "$MIGRATE_PIN_PATH"; then
            migrate_pin_active=true
        else
            migrate_pin_active=false
        fi
    fi
fi

# --- services (per-container status) ---
# `docker inspect --format` pulls ONLY the whitelisted fields. We do not use
# `docker inspect ... | jq`: jq on a live snapshot could accidentally pull out
# an extra field (env/mounts), whereas here every field is named explicitly — the 'field'
# helper below assembles a safe JSON string for a single container. Health may be
# empty (no healthcheck) — then null. exit_code for running is also null:
# 0 while running ≠ "completed successfully".
#
# COMPOSE_PROJECT lets us catch containers that docker-compose named
# as `<project>-<service>-<n>`. The default is `avelren` (see docker-compose.yml).
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-avelren}
SERVICE_NAMES="db api collector notifier watchdog caddy"

services_json_parts=""
for svc in $SERVICE_NAMES; do
    container="${COMPOSE_PROJECT}-${svc}-1"
    status="null"; health="null"; started_at="null"
    restart_count="null"; exit_code="null"; oom_killed="null"; image="null"

    if command -v docker >/dev/null 2>&1 && \
       raw=$(docker inspect --format \
         '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.StartedAt}}|{{.RestartCount}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.Config.Image}}' \
         "$container" 2>/dev/null); then
        IFS='|' read -r s h st rc ec oom img <<< "$raw"
        status="\"${s}\""
        if [ "$h" = "none" ]; then health="null"; else health="\"${h}\""; fi
        started_at="\"${st}\""
        restart_count="$rc"
        # exit_code only makes sense for containers that have exited: `docker
        # inspect` in the running state returns 0, which looks like "success" even
        # though it's just the default. We show null for active ones — otherwise a client
        # would misread "0" on a live service.
        if [ "$s" = "running" ]; then exit_code="null"; else exit_code="$ec"; fi
        if [ "$oom" = "true" ]; then oom_killed="true"; else oom_killed="false"; fi
        # image contains only the tag (e.g. avelren-app:latest), without env/mounts.
        image="\"${img}\""
    fi

    entry=$(cat <<SVC
    {"name": "$svc", "status": $status, "health": $health, "started_at": $started_at, "restart_count": $restart_count, "exit_code": $exit_code, "oom_killed": $oom_killed, "image": $image}
SVC
)
    if [ -z "$services_json_parts" ]; then
        services_json_parts="$entry"
    else
        services_json_parts="$services_json_parts,
$entry"
    fi
done

# --- backup stamp ---
backup_stamp=/run/avelren-backup.stamp
backup_last_run=null
backup_age_hours=null
backup_stale=false
if [ -e "$backup_stamp" ]; then
    now=$(date +%s)
    mtime=$(stat -c %Y "$backup_stamp")
    age=$(( now - mtime ))
    backup_last_run=$mtime
    backup_age_hours=$(awk -v a=$age 'BEGIN {printf "%.1f", a/3600}')
    if [ "$age" -gt "$((36 * 3600))" ]; then
        backup_stale=true
    fi
fi

# --- TLS certificate ---
# Previously the API did a synchronous ssl-connect from an async handler. Now the
# host timer does it: the API's event loop is not blocked, and the API's network surface stays clean.
cert_days_left=null
cert_issuer=null
cert_error=null
cert_out=$(
    timeout 10 openssl s_client -servername "$API_HOST" -connect "$API_HOST:443" \
        </dev/null 2>/dev/null | openssl x509 -noout -enddate -issuer 2>/dev/null
) || cert_out=""
if [ -n "$cert_out" ]; then
    end_line=$(printf '%s\n' "$cert_out" | awk -F= '/^notAfter=/{print $2}')
    issuer_line=$(printf '%s\n' "$cert_out" | awk -F= '/^issuer=/{sub(/^issuer=/, ""); print}')
    if [ -n "$end_line" ]; then
        end_epoch=$(date -u -d "$end_line" +%s 2>/dev/null || echo "")
        if [ -n "$end_epoch" ]; then
            now=$(date +%s)
            cert_days_left=$(( (end_epoch - now) / 86400 ))
        fi
    fi
    if [ -n "$issuer_line" ]; then
        # Extract organizationName, if present.
        org=$(printf '%s' "$issuer_line" | grep -oE 'O = [^,]+' | head -1 | sed 's/^O = //')
        [ -n "$org" ] && cert_issuer="\"$org\""
    fi
else
    cert_error='"handshake failed"'
fi

collected_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Atomic write. A reader never sees a half-written file.
cat > "$TMP" <<JSON
{
  "collected_at": "$collected_at",
  "system": {
    "uptime_seconds": $uptime_seconds,
    "load_1m": $load1,
    "load_5m": $load5,
    "cpu_count": $cpu_count,
    "memory_total_mb": $(( mem_total_kb / 1024 )),
    "memory_used_mb": $(( (mem_total_kb - mem_avail_kb) / 1024 )),
    "swap_total_mb": $(( swap_total_kb / 1024 )),
    "swap_used_mb": $(( (swap_total_kb - swap_free_kb) / 1024 )),
    "disk_total_gb": $(awk -v k=$disk_total_1k 'BEGIN {printf "%.1f", k/1024/1024}'),
    "disk_free_gb": $(awk -v k=$disk_avail_1k 'BEGIN {printf "%.1f", k/1024/1024}'),
    "disk_used_percent": $(awk -v u=$disk_used_1k -v t=$disk_total_1k \
        'BEGIN {if (t > 0) printf "%d", (u * 100 + t / 2) / t; else print "null"}'),
    "reboot_required": $reboot_required,
    "reboot_pending_days": $reboot_pending_days,
    "updates_pending": $updates_pending,
    "updates_security": $updates_security
  },
  "network": {
    "rx_total_gb": $(awk -v b=$rx_total 'BEGIN {printf "%.2f", b/1024/1024/1024}'),
    "tx_total_gb": $(awk -v b=$tx_total 'BEGIN {printf "%.2f", b/1024/1024/1024}')
  },
  "inodes": {
    "total": $inodes_total,
    "used": $inodes_used,
    "used_percent": $inodes_used_percent
  },
  "docker": {
    "daemon_version": $docker_daemon_version,
    "compose_version": $docker_compose_version,
    "migrate_pin_active": $migrate_pin_active
  },
  "services": [
$services_json_parts
  ],
  "backups": {
    "last_run": $backup_last_run,
    "age_hours": $backup_age_hours,
    "stale": $backup_stale
  },
  "certificate": {
    "days_left": $cert_days_left,
    "issuer": ${cert_issuer:-null},
    "error": ${cert_error:-null}
  }
}
JSON

mv "$TMP" "$OUT"
chmod 644 "$OUT"
