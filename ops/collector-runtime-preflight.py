"""Перевірки collector-only runtime. Секретні значення не виводяться."""

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path

SPOOL_DIR = "/var/lib/avelren/collector-spool"

FIELDS = {
    "source_commit",
    "image_id",
    "env_file",
    "compose_file",
    "project",
    "container_name",
    "network",
    "volume",
    "state_dir",
}
PRODUCTION = {
    "project": "avelren-collector-runtime",
    "container_name": "avelren-collector-1",
    "network": "avelren_default",
    "volume": "avelren_collector_spool_v1",
}


def private_path(path: Path, *, directory=False, test_mode=False):
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("unsafe_path")
    info = path.stat()
    if directory != stat.S_ISDIR(info.st_mode) or (
        not directory and not stat.S_ISREG(info.st_mode)
    ):
        raise ValueError("wrong_path_type")
    if os.name != "posix":
        if not test_mode:
            raise ValueError("linux_required")
        # Windows mode bits cannot establish Unix private permissions.
        if info.st_mode & 0o077:
            raise ValueError("private_permissions_unverified")
    elif info.st_mode & 0o077:
        raise ValueError("unsafe_permissions")
    if not test_mode:
        for ancestor in (path, *path.parents):
            parent = ancestor.stat()
            if parent.st_uid != 0 or parent.st_mode & 0o022:
                raise ValueError("untrusted_path_owner")


def load_manifest(path: Path, *, test_mode: bool = False) -> dict:
    private_path(path, test_mode=test_mode)
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError):
        raise ValueError("invalid_manifest") from None
    if (
        not isinstance(value, dict)
        or set(value) != FIELDS
        or not all(isinstance(v, str) for v in value.values())
    ):
        raise ValueError("invalid_manifest_fields")
    if not re.fullmatch("[0-9a-f]{40}", value["source_commit"]) or not re.fullmatch(
        "sha256:[0-9a-f]{64}", value["image_id"]
    ):
        raise ValueError("invalid_image_identity")
    for key, expected in PRODUCTION.items():
        if test_mode:
            if not re.fullmatch("avelren-runtime-test-[a-z0-9-]+", value[key]):
                raise ValueError("unsafe_test_resource")
        elif value[key] != expected:
            raise ValueError("unexpected_production_resource")
    private_path(Path(value["env_file"]), test_mode=test_mode)
    private_path(Path(value["state_dir"]), directory=True, test_mode=test_mode)
    compose = Path(value["compose_file"])
    if not compose.is_absolute() or not compose.is_file() or compose.is_symlink():
        raise ValueError("invalid_compose_path")
    if not test_mode:
        for ancestor in (compose, *compose.parents):
            info = ancestor.stat()
            if ancestor.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("untrusted_compose")
    return value


def is_collector(item: dict) -> bool:
    config = item.get("Config") or {}
    labels = config.get("Labels") or {}
    command = config.get("Cmd") or []
    entrypoint = config.get("Entrypoint") or []
    tokens = [str(token) for token in [*command, *entrypoint]]
    return (
        labels.get("com.docker.compose.service") == "collector"
        or "collector" in item.get("Name", "").lower()
        or any("avelren.collector" in token for token in tokens)
    )


def validate_runtime(
    manifest: dict, effective: dict, inventory: list[dict], *, require_managed: bool
) -> list[str]:
    errors = []
    services = effective.get("services", {})
    svc = services.get("collector", {})
    if set(services) != {"collector"} or any(
        key in svc for key in ("build", "depends_on", "ports", "mem_limit", "cpus")
    ):
        errors.append("unsafe_compose_services")
    if (
        svc.get("image") != manifest["image_id"]
        or svc.get("container_name") != manifest["container_name"]
        or svc.get("command") != ["python", "-m", "avelren.collector"]
    ):
        errors.append("unsafe_compose_identity")
    if (
        svc.get("user") != "10001:10001"
        or svc.get("read_only") is not True
        or svc.get("cap_drop") != ["ALL"]
        or svc.get("security_opt") != ["no-new-privileges:true"]
        or svc.get("pids_limit") != 128
        or svc.get("restart") != "unless-stopped"
        or svc.get("privileged", False)
        or svc.get("entrypoint")
        or svc.get("tmpfs") != ["/tmp:rw,nosuid,nodev,noexec,size=64m"]
    ):
        errors.append("unsafe_compose_security")
    files = svc.get("env_file", [])
    if (
        len(files) != 1
        or files[0].get("path") != manifest["env_file"]
        or files[0].get("format") != "raw"
        or files[0].get("required", True) is not True
        or svc.get("environment")
    ):
        errors.append("unsafe_compose_env")
    vols = effective.get("volumes", {})
    nets = effective.get("networks", {})
    if (
        set(vols) != {"collector_spool"}
        or set(nets) != {"runtime"}
        or vols.get("collector_spool", {}).get("external") is not True
        or vols.get("collector_spool", {}).get("name") != manifest["volume"]
        or nets.get("runtime", {}).get("external") is not True
        or nets.get("runtime", {}).get("name") != manifest["network"]
        or set(svc.get("networks", {})) != {"runtime"}
    ):
        errors.append("unsafe_compose_resources")
    mounts = svc.get("volumes", [])
    if len(mounts) != 1 or any(
        v.get("type") != "volume"
        or v.get("source") != "collector_spool"
        or v.get("target") != SPOOL_DIR
        or v.get("read_only", False)
        for v in mounts
    ):
        errors.append("unsafe_compose_mounts")
    targets = [
        item
        for item in inventory
        if item.get("Name", "").lstrip("/") == manifest["container_name"]
    ]
    for item in inventory:
        labels = item.get("Config", {}).get("Labels") or {}
        if (
            item not in targets
            and labels.get("com.docker.compose.project") == manifest["project"]
            and labels.get("com.docker.compose.service") == "collector"
        ):
            errors.append("additional_managed_collector")
        if (
            item.get("State", {}).get("Running")
            and is_collector(item)
            and item not in targets
        ):
            errors.append("additional_running_collector")
    if len(targets) != 1:
        errors.append("missing_or_ambiguous_target")
        return errors
    item = targets[0]
    config = item.get("Config") or {}
    host = item.get("HostConfig") or {}
    if item.get("Image") != manifest["image_id"]:
        errors.append("wrong_image")
    if "AVELREN_GIT_SHA=" + manifest["source_commit"] not in (config.get("Env") or []):
        errors.append("wrong_source_commit")
    if config.get("Cmd") != ["python", "-m", "avelren.collector"] or config.get(
        "Entrypoint"
    ):
        errors.append("wrong_command")
    labels = config.get("Labels") or {}
    managed = (
        labels.get("com.docker.compose.project") == manifest["project"]
        and labels.get("com.docker.compose.service") == "collector"
    )
    if require_managed and not managed:
        errors.append("unmanaged_target")
    if not require_managed and labels and not managed:
        errors.append("foreign_target_labels")
    actual_mounts = item.get("Mounts", [])
    if len(actual_mounts) != 1 or any(
        v.get("Type") != "volume"
        or v.get("Name") != manifest["volume"]
        or v.get("Destination") != SPOOL_DIR
        or v.get("RW") is not True
        for v in actual_mounts
    ):
        errors.append("wrong_volume")
    if set(item.get("NetworkSettings", {}).get("Networks", {})) != {
        manifest["network"]
    }:
        errors.append("wrong_network")
    if (
        config.get("User") != "10001:10001"
        or host.get("ReadonlyRootfs") is not True
        or host.get("CapDrop") != ["ALL"]
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or host.get("PidsLimit") != 128
        or host.get("RestartPolicy", {}).get("Name") != "unless-stopped"
        or host.get("Tmpfs") != {"/tmp": "rw,nosuid,nodev,noexec,size=64m"}
    ):
        errors.append("wrong_runtime_security")
    if item.get("State", {}).get("Restarting") or item.get("State", {}).get("Dead"):
        errors.append("unhealthy_container_state")
    return sorted(set(errors))


def run(args: list[str], *, env=None) -> str:
    try:
        result = subprocess.run(
            args, env=env, capture_output=True, text=True, timeout=90, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("command_unavailable_or_timeout") from None
    if result.returncode:
        raise ValueError("command_failed")
    return result.stdout


def compose_command(manifest: dict) -> tuple[list[str], dict]:
    # Ignore shell COMPOSE_FILE/profiles/env influences; always select exact file/project.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("COMPOSE_", "COLLECTOR_"))
    }
    env.update(
        COLLECTOR_IMAGE_ID=manifest["image_id"],
        COLLECTOR_ENV_FILE=manifest["env_file"],
        COLLECTOR_CONTAINER_NAME=manifest["container_name"],
        COLLECTOR_NETWORK=manifest["network"],
        COLLECTOR_VOLUME=manifest["volume"],
    )
    return (
        [
            "docker",
            "compose",
            "--env-file",
            os.devnull,
            "-p",
            manifest["project"],
            "-f",
            manifest["compose_file"],
        ],
        env,
    )


def inspect_inventory() -> list[dict]:
    identifiers = run(["docker", "ps", "-aq"]).split()
    return json.loads(run(["docker", "inspect", *identifiers])) if identifiers else []


def require_legacy_restore_topology(inventory: list[dict]) -> list[str]:
    candidates = [x for x in inventory if is_collector(x)]
    canonical = [x for x in candidates if x.get("Name") == "/avelren-collector-1"]
    if len(canonical) != 1:
        return ["unsupported_restore_topology"]
    labels = canonical[0].get("Config", {}).get("Labels") or {}
    if (
        labels.get("com.docker.compose.project") != "avelren"
        or labels.get("com.docker.compose.service") != "collector"
    ):
        return ["unsupported_restore_topology"]
    if any(
        x.get("State", {}).get("Running") and x not in canonical for x in candidates
    ):
        return ["additional_running_collector"]
    # A stopped independent spool container still represents a separate recovery state.
    if any(
        x not in canonical
        and any(m.get("Destination") == SPOOL_DIR for m in x.get("Mounts", []))
        for x in candidates
    ):
        return ["unsupported_restore_spool"]
    if any(m.get("Destination") == SPOOL_DIR for m in canonical[0].get("Mounts", [])):
        return ["unsupported_restore_spool"]
    return []


def preflight(manifest: dict, *, require_managed=True) -> tuple[dict, dict]:
    command, env = compose_command(manifest)
    effective = json.loads(
        run([*command, "config", "--format", "json", "--no-env-resolution"], env=env)
    )
    inventory = inspect_inventory()
    errors = validate_runtime(
        manifest, effective, inventory, require_managed=require_managed
    )
    for kind in ("network", "volume"):
        found = json.loads(run(["docker", kind, "inspect", manifest[kind]]))
        if len(found) != 1 or found[0].get("Name") != manifest[kind]:
            errors.append("missing_external_resource")
    image = json.loads(run(["docker", "image", "inspect", manifest["image_id"]]))
    if (
        len(image) != 1
        or image[0].get("Id") != manifest["image_id"]
        or "AVELREN_GIT_SHA=" + manifest["source_commit"]
        not in image[0].get("Config", {}).get("Env", [])
    ):
        errors.append("image_source_mismatch")
    if errors:
        raise ValueError(",".join(sorted(set(errors))))
    target = next(
        x for x in inventory if x["Name"].lstrip("/") == manifest["container_name"]
    )
    # Compare private env literally to the actual container; no values leave this process.
    desired = {}
    for line in Path(manifest["env_file"]).read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if (
            not sep
            or not re.fullmatch("[A-Z][A-Z0-9_]*", key)
            or key in desired
            or "\x00" in value
        ):
            raise ValueError("invalid_private_env")
        desired[key] = value
    actual = dict(
        line.split("=", 1) for line in target["Config"].get("Env", []) if "=" in line
    )
    if not desired or any(actual.get(k) != v for k, v in desired.items()):
        raise ValueError("runtime_env_mismatch")
    return manifest, target


def status(manifest: dict, target: dict) -> dict:
    value = {
        "container_id": target["Id"],
        "image_id": target["Image"],
        "source_commit": manifest["source_commit"],
        "running": target["State"]["Running"],
        "restart_count": target["RestartCount"],
    }
    if target["State"]["Running"]:
        value["spool"] = json.loads(
            run(
                [
                    "docker",
                    "exec",
                    manifest["container_name"],
                    "python",
                    "-m",
                    "avelren.collector_control",
                    "capture-only",
                    "status",
                ]
            )
        )
    else:
        value["spool"] = "unavailable_stopped"
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--restore-topology", action="store_true")
    parser.add_argument(
        "--phase", choices=["config", "status", "managed"], default="managed"
    )
    args = parser.parse_args()
    try:
        if args.restore_topology:
            if require_legacy_restore_topology(inspect_inventory()):
                raise ValueError("unsupported_restore_topology")
            print(json.dumps({"status": "legacy_restore_topology_verified"}))
            return 0
        if args.manifest is None:
            raise ValueError("manifest_required")
        manifest, target = preflight(
            load_manifest(args.manifest), require_managed=args.phase != "config"
        )
        print(
            json.dumps(
                status(manifest, target)
                if args.phase == "status"
                else {"status": "verified"}
            )
        )
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({"status": "denied", "reason": "runtime_verification_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
