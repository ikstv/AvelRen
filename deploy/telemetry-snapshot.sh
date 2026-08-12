#!/usr/bin/env bash
#
# Знімає стан хоста в один JSON-файл для API-контейнера.
#
# Мета — витягти API з trust boundary хоста. До цього public FastAPI-контейнер
# монтував /secrets, /proc і /run, щоб /admin/telemetry могла показати
# завантаженість і диск; побічним ефектом RCE або path-traversal у API
# отримував доступ до Firebase service-account.json (аудит SEC-1 / A-01).
#
# Тепер snapshot робить root на хості, а API читає лише вже зібраний JSON.
# Ніяких secrets, ніякого /proc, ніякого /run у контейнері.
#
# Файл пишеться атомарно (write to .tmp → rename), тож читач ніколи не бачить
# half-written state. Time — ISO-8601 UTC; API перевіряє свіжість і показує
# "stale", якщо snapshot старше за 5 хв.
#
set -euo pipefail

OUT_DIR=/var/lib/avelren-telemetry
OUT=$OUT_DIR/host.json
TMP=$OUT.tmp
FS_PROBE=${AVELREN_FS_PROBE:-/opt/avelren}
API_HOST=${AVELREN_CERT_HOST:-api.bordersignal.pp.ua}
# Перевизначається лише в CI, щоб прогнати фільтрацію інтерфейсів на
# синтетичному файлі — тестувати треба цей script, а не його копію в workflow.
NET_DEV=${AVELREN_NET_DEV:-/proc/1/net/dev}
# Перевизначається лише в CI, щоб прогнати саму логіку apt-check (null /
# валідний вивід / ненульовий вихід) на синтетичному probe.
APT_CHECK=${AVELREN_APT_CHECK:-/usr/lib/update-notifier/apt-check}

mkdir -p "$OUT_DIR"

# --- system ---
read -r load1 load5 _rest < /proc/loadavg
uptime_seconds=$(awk '{print int($1)}' /proc/uptime)
cpu_count=$(nproc)

mem_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
mem_avail_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
swap_total_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
swap_free_kb=$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)

# statvfs самого хоста через df — не потребує монтувань у контейнер.
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

# Доступні оновлення пакетів. `reboot_required` показує лише наслідок уже
# встановленого ядра — самі непоставлені оновлення (і особливо security) до
# цього моменту не було видно взагалі, тож дізнатися про них можна було тільки
# зайшовши на хост руками.
#
# Рахуємо через apt-check: він читає вже завантажені списки пакетів і не
# ходить у мережу, тож безпечний для щохвилинного таймера (на відміну від
# `apt-get update`). Формат виводу — "звичайні;безпекові" у stderr.
# 0 і null тут різні: 0 = перевірено, оновлень немає; null = перевірити не
# вдалося (немає apt-check, зламаний вивід, ненульовий вихід probe). Показувати
# «немає» замість «невідомо» — брехати про стан хоста, тож default = null.
updates_pending=null
updates_security=null
if [ -x "$APT_CHECK" ]; then
    # apt-check пише "звичайні;безпекові" у stderr. `|| raw=""` — той самий
    # fail-safe, що нижче для openssl: probe не має бути single point of failure.
    # Під `set -euo pipefail` ненульовий вихід apt-check (а в update-notifier
    # такі сценарії траплялися) інакше поклав би ввесь snapshot ще до валідації.
    raw=$("$APT_CHECK" 2>&1 | tr -d '[:space:]') || raw=""
    # Лише валідний "N;M" дає числа; будь-що інше лишає null.
    if printf '%s' "$raw" | grep -qE '^[0-9]+;[0-9]+$'; then
        updates_pending=${raw%%;*}
        updates_security=${raw##*;}
    fi
fi

# --- network (RX/TX через host PID 1) ---
#
# Парситься через awk, а не bash-підстановки: у /proc/net/dev назви
# інтерфейсів вирівняні пробілами ("    lo:"), і ${name## } зрізає рівно один
# пробіл, тож фільтр lo/docker*/br-*/veth* мовчки не спрацьовував і локальний
# та docker-трафік потрапляв у лічильник зовнішнього.
#
# `index($0, ":")` ріже саме на двокрапці — це переживає і довгі назви
# інтерфейсів, що зливаються з першим числом. `split(rest, f, " ")` з
# однопробільним роздільником використовує дефолтну семантику awk: зрізає
# краї і ділить по групах пробілів. f[1]=rx_bytes, f[9]=tx_bytes.
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
# Диск за байтами може бути на 20%, а за inode на 100% — і create() почне
# віддавати ENOSPC, хоча df -h нічого не підозрює. Тому окрема секція.
inodes_total=null
inodes_used=null
inodes_used_percent=null
if inodes_line=$(df -Pi "$FS_PROBE" 2>/dev/null | tail -1); then
    # `df -Pi` формат: Filesystem Inodes IUsed IFree IUse% Mounted
    read -r _fs inodes_total inodes_used _ifree ipct _rest <<< "$inodes_line"
    inodes_used_percent=${ipct%\%}
    # Якщо будь-яке з чисел не число (наприклад "-" для tmpfs) — залишаємо null.
    case "$inodes_total" in ''|*[!0-9]*) inodes_total=null ;; esac
    case "$inodes_used"  in ''|*[!0-9]*) inodes_used=null  ;; esac
    case "$inodes_used_percent" in ''|*[!0-9]*) inodes_used_percent=null ;; esac
fi

# --- docker daemon / compose version ---
# `docker version --format` не має форматного варіанту, який би повернув
# лише один рядок серверної версії; --format '{{.Server.Version}}' — точно
# те, що треба. Ненульовий вихід (docker daemon не працює) → null, а не
# півронути весь snapshot.
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

# --- services (per-container status) ---
# `docker inspect --format` тягне ТІЛЬКИ поля з whitelist. Не використовуємо
# `docker inspect ... | jq`: jq на живому snapshot може випадково витягти
# зайве поле (env/mounts), а тут кожне поле іменоване явно — helper 'field'
# нижче збирає безпечний JSON рядок для одного контейнера. Health може бути
# порожнім (немає healthcheck) — тоді null. exit_code для running теж null:
# 0 у running ≠ «успішно завершено».
#
# COMPOSE_PROJECT дозволяє нам ловити контейнери, які docker-compose назвав
# як `<project>-<service>-<n>`. Дефолт — `avelren` (див. docker-compose.yml).
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
        # exit_code має сенс лише для контейнерів, які завершились: `docker
        # inspect` у running-стані повертає 0, який виглядає як «успіх», хоча
        # це просто default. Показуємо null для активних — інакше клієнт
        # неправильно інтерпретує «0» на живому сервісі.
        if [ "$s" = "running" ]; then exit_code="null"; else exit_code="$ec"; fi
        if [ "$oom" = "true" ]; then oom_killed="true"; else oom_killed="false"; fi
        # image містить лише tag (напр. avelren-app:latest), без env/mounts.
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
# Раніше API робив синхронний ssl-connect із async-хендлера. Тепер це robить
# host-таймер: event loop API не блокується, а мережева поверхня API — ні.
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
        # Витягнути organizationName, якщо є.
        org=$(printf '%s' "$issuer_line" | grep -oE 'O = [^,]+' | head -1 | sed 's/^O = //')
        [ -n "$org" ] && cert_issuer="\"$org\""
    fi
else
    cert_error='"handshake failed"'
fi

collected_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Атомарний запис. Читач ніколи не бачить half-written файл.
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
    "compose_version": $docker_compose_version
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
