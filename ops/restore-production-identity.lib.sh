#!/usr/bin/env bash
# Source-only, read-only production Compose identity gate.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "DENIED: production Compose identity gate is source-only" >&2
    exit 2
fi

avelren_verify_compose_identity() {
    local stack_dir=${1:?stack directory is required}
    local compose_file=${2:?Compose file is required}
    local compose_project_dir=${3:?Compose project directory is required}
    local compose_env_file=${4:?Compose env file is required}
    local compose_project=${5:?Compose project is required}
    local db_service=${6:?database service is required}
    local raw project_label service_label working_dir_label extra

    [ "$compose_file" = "$stack_dir/docker-compose.yml" ] || {
        echo "DENIED: production Compose file must belong to the canonical stack" >&2
        return 2
    }
    [ "$compose_project_dir" = "$stack_dir" ] || {
        echo "DENIED: production Compose project directory must be the canonical stack" >&2
        return 2
    }
    [ "$compose_env_file" = "$stack_dir/.env" ] || {
        echo "DENIED: production Compose env file must be the canonical stack .env" >&2
        return 2
    }
    [ -f "$compose_file" ] && [ -f "$compose_env_file" ] || {
        echo "DENIED: canonical production Compose files are unavailable" >&2
        return 2
    }

    # Docker Compose owns these labels. Read only the three identity fields;
    # never inspect environment, mounts, or arbitrary metadata from production.
    raw=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}|{{ index .Config.Labels "com.docker.compose.service" }}|{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' \
        "$compose_project-$db_service-1") || {
        echo "DENIED: expected production database container is unavailable" >&2
        return 2
    }
    IFS='|' read -r project_label service_label working_dir_label extra <<<"$raw"
    if [ -n "${extra:-}" ] || [ "$project_label" != "$compose_project" ] || \
       [ "$service_label" != "$db_service" ] || [ "$working_dir_label" != "$stack_dir" ]; then
        echo "DENIED: running database container does not match the canonical production Compose identity" >&2
        return 2
    fi
}

avelren_verify_production_compose_identity() {
    avelren_verify_compose_identity \
        /opt/avelren \
        /opt/avelren/docker-compose.yml \
        /opt/avelren \
        /opt/avelren/.env \
        avelren \
        db
}
