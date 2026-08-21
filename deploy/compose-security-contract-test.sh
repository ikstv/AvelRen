#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
umask 077
WORK=$(mktemp -d)
RESOLVED=$(mktemp)
COMPOSE_ERROR=$(mktemp)
STACK="$WORK/stack"
trap 'rm -rf "$WORK" "$RESOLVED" "$COMPOSE_ERROR"' EXIT
chmod 600 "$RESOLVED" "$COMPOSE_ERROR"

fail() {
    printf 'compose security contract failed: %s\n' "$*" >&2
    exit 1
}

run_compose_config() {
    mkdir -p "$STACK"
    cp "$ROOT/docker-compose.yml" "$STACK/docker-compose.yml"
    cat >"$STACK/.env" <<'ENV'
DATABASE_URL=LEGACY_SENTINEL
AVELREN_ADMIN_DSN=ADMIN_SENTINEL
AVELREN_ADMIN_PASSWORD=ADMIN_PASSWORD_SENTINEL
AVELREN_MIGRATOR_DSN=MIGRATOR_SENTINEL
AVELREN_BACKUP_DSN=BACKUP_SENTINEL
AVELREN_BACKUP_PASSWORD=BACKUP_PASSWORD_SENTINEL
AVELREN_COLLECTOR_DSN=COLLECTOR_SENTINEL
AVELREN_NOTIFIER_DSN=NOTIFIER_SENTINEL
AVELREN_WATCHDOG_DSN=WATCHDOG_SENTINEL
AVELREN_API_DSN=API_SENTINEL
REARM_FACTOR=REARM_FACTOR_SENTINEL
ECHERHA_VEHICLE_TYPE=ECHERHA_VEHICLE_TYPE_SENTINEL
ECHERHA_API_VERSION=ECHERHA_API_VERSION_SENTINEL
ECHERHA_CLIENT_VERSION=ECHERHA_CLIENT_VERSION_SENTINEL
ECHERHA_DEVICE_ID=ECHERHA_DEVICE_ID_SENTINEL
ECHERHA_DEVICE_NAME=ECHERHA_DEVICE_NAME_SENTINEL
ENV
    (
        cd "$STACK"
        POSTGRES_USER=POSTGRES_USER_SENTINEL \
        POSTGRES_PASSWORD=POSTGRES_PASSWORD_SENTINEL \
        POSTGRES_DB=POSTGRES_DB_SENTINEL \
        DATABASE_URL=LEGACY_SENTINEL \
        AVELREN_ADMIN_DSN=ADMIN_SENTINEL \
        AVELREN_ADMIN_PASSWORD=ADMIN_PASSWORD_SENTINEL \
        AVELREN_MIGRATOR_DSN=MIGRATOR_SENTINEL \
        AVELREN_BACKUP_DSN=BACKUP_SENTINEL \
        AVELREN_BACKUP_PASSWORD=BACKUP_PASSWORD_SENTINEL \
        AVELREN_COLLECTOR_DSN=COLLECTOR_SENTINEL \
        AVELREN_NOTIFIER_DSN=NOTIFIER_SENTINEL \
        AVELREN_WATCHDOG_DSN=WATCHDOG_SENTINEL \
        AVELREN_API_DSN=API_SENTINEL \
        REARM_FACTOR=REARM_FACTOR_SENTINEL \
        ECHERHA_VEHICLE_TYPE=ECHERHA_VEHICLE_TYPE_SENTINEL \
        ECHERHA_API_VERSION=ECHERHA_API_VERSION_SENTINEL \
        ECHERHA_CLIENT_VERSION=ECHERHA_CLIENT_VERSION_SENTINEL \
        ECHERHA_DEVICE_ID=ECHERHA_DEVICE_ID_SENTINEL \
        ECHERHA_DEVICE_NAME=ECHERHA_DEVICE_NAME_SENTINEL \
        docker compose --profile migrate --env-file .env config --format json >"$RESOLVED" 2>"$COMPOSE_ERROR"
    ) || fail 'docker compose config failed'
}

run_compose_config

# The profile is load-bearing since #88 PR 2: it is what keeps a bare
# `docker compose up -d` from applying and stamping the next migration. Guard
# all three properties the profile relies on, each with a distinct failure.
if docker compose -f "$ROOT/docker-compose.yml" config --services 2>/dev/null | grep -qx migrate; then
    fail 'migrate is in the default service set — the #88 profile is gone'
fi
if ! docker compose --profile migrate -f "$ROOT/docker-compose.yml" config --services 2>/dev/null | grep -qx migrate; then
    fail 'migrate is not reachable even with its profile'
fi
if ! docker compose -f "$ROOT/docker-compose.yml" config --quiet 2>/dev/null; then
    fail 'model invalid with the profile inactive — required: false is missing'
fi

# M-1: no service may bind-mount the whole host /run (it carries docker.sock);
# watchdog reads host facts (backup-stamp, reboot-required) from the /telemetry
# snapshot instead. Guard against a regression that re-adds the broad mount.
if grep -Eq 'host/run|[^a-z]/run:' "$RESOLVED"; then
    fail 'a service bind-mounts the whole host /run (M-1); use the /telemetry snapshot'
fi

PYTHON_BIN=${PYTHON_BIN:-python3}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN=python
fi
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail 'Python interpreter missing'

"$PYTHON_BIN" - "$RESOLVED" <<'PY' || exit $?
import json
import sys

resolved_path = sys.argv[1]
expected = {
    "migrate": {"MIGRATOR_SENTINEL"},
    "collector": {"COLLECTOR_SENTINEL"},
    "notifier": {"NOTIFIER_SENTINEL"},
    "watchdog": {"WATCHDOG_SENTINEL"},
    "api": {"API_SENTINEL"},
}
all_database_sentinels = {
    "ADMIN_SENTINEL",
    "MIGRATOR_SENTINEL",
    "BACKUP_SENTINEL",
    "COLLECTOR_SENTINEL",
    "NOTIFIER_SENTINEL",
    "WATCHDOG_SENTINEL",
    "API_SENTINEL",
    "LEGACY_SENTINEL",
}
functional_setting_owners = {
    "REARM_FACTOR": ({"collector"}, "REARM_FACTOR_SENTINEL"),
    "ECHERHA_VEHICLE_TYPE": ({"collector", "api"}, "ECHERHA_VEHICLE_TYPE_SENTINEL"),
    # The collector's eCherha device identity. config.py requires these (and
    # aborts at startup if ECHERHA_DEVICE_ID is unset/blank), .env supplies them,
    # but the compose collector service did not forward them — so a container
    # recreated from the current compose failed with "ECHERHA_DEVICE_ID must be a
    # valid UUID" and collected nothing (2026-08-14 adoption incident). Assert the
    # collector — and only the collector — receives each of them.
    "ECHERHA_API_VERSION": ({"collector"}, "ECHERHA_API_VERSION_SENTINEL"),
    "ECHERHA_CLIENT_VERSION": ({"collector"}, "ECHERHA_CLIENT_VERSION_SENTINEL"),
    "ECHERHA_DEVICE_ID": ({"collector"}, "ECHERHA_DEVICE_ID_SENTINEL"),
    "ECHERHA_DEVICE_NAME": ({"collector"}, "ECHERHA_DEVICE_NAME_SENTINEL"),
}
privileged_variable_names = {
    "AVELREN_ADMIN_DSN",
    "AVELREN_ADMIN_PASSWORD",
    "AVELREN_BACKUP_DSN",
    "AVELREN_BACKUP_PASSWORD",
}


def fail(message: str) -> None:
    print(f"compose security contract failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def environment_mapping(service: dict) -> dict[str, str]:
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items() if value is not None}
    if isinstance(environment, list):
        return {
            value.split("=", 1)[0]: value.split("=", 1)[1]
            for value in environment
            if isinstance(value, str) and "=" in value
        }
    fail("invalid resolved environment")


with open(resolved_path, encoding="utf-8") as resolved_file:
    config = json.load(resolved_file)

services = config.get("services")
if not isinstance(services, dict):
    fail("resolved services missing")

for service_name, own_sentinel in expected.items():
    service = services.get(service_name)
    if not isinstance(service, dict):
        fail(f"service {service_name} missing")
    if "env_file" in service:
        fail(f"service {service_name} uses env_file")
    environment = environment_mapping(service)
    forbidden_names = set(environment) & privileged_variable_names
    if forbidden_names:
        fail(f"service {service_name} exposes privileged variables: {sorted(forbidden_names)}")
    seen_database_sentinels = set(environment.values()) & all_database_sentinels
    if seen_database_sentinels != own_sentinel:
        fail(f"service {service_name} has forbidden database credential category")

for setting_name, (expected_owners, sentinel) in functional_setting_owners.items():
    seen_owners = {
        service_name
        for service_name in expected
        if environment_mapping(services[service_name]).get(setting_name) == sentinel
    }
    if seen_owners != expected_owners:
        fail(f"functional setting {setting_name} has forbidden ownership")

print("compose security contract ok")
PY
