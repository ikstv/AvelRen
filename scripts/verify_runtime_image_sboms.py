"""Перевіряє покриття Python та OS пакетів у runtime image SBOMs."""

import json
import re
import sys
from pathlib import Path

sbom_dir = Path(sys.argv[1])
lock_path = Path(sys.argv[2])
expected_files = {
    "avelren-candidate.cdx.json": ("deb", "avelren-candidate.deb.txt"),
    "timescaledb.cdx.json": ("apk", "timescaledb.apk.txt"),
    "caddy.cdx.json": ("apk", "caddy.apk.txt"),
}

expected_python = set()
requirement = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)")
for line in lock_path.read_text(encoding="utf-8").splitlines():
    match = requirement.match(line.strip())
    if match:
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        expected_python.add((name, match.group(2)))
if not expected_python:
    raise SystemExit("Python requirements lock has no exact name==version pins")


def installed_inventory(path: Path, ecosystem: str) -> set[tuple[str, str]]:
    packages = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if ecosystem == "deb":
            fields = line.split("\t")
            if len(fields) != 3 or fields[0].strip() != "ii":
                continue
            name, version = fields[1], fields[2]
        else:
            match = re.fullmatch(r"(.+)-(\d[^ ]*)", line.strip())
            if not match:
                continue
            name, version = match.groups()
        packages.add((re.sub(r"[-_.]+", "-", name).lower(), version))
    if not packages:
        raise SystemExit(f"Package-manager inventory is empty: {path.name}")
    return packages

for filename, ecosystem in expected_files.items():
    ecosystem, inventory_filename = ecosystem
    path = sbom_dir / filename
    if not path.is_file():
        raise SystemExit(f"Missing runtime image SBOM: {filename}")
    sbom = json.loads(path.read_text(encoding="utf-8"))
    if sbom.get("bomFormat") != "CycloneDX":
        raise SystemExit(f"{filename} is not CycloneDX")
    components = sbom.get("components", [])
    actual_os = {
        (
            re.sub(r"[-_.]+", "-", component.get("name", "")).lower(),
            component.get("version", ""),
        )
        for component in components
        if component.get("purl", "").startswith(f"pkg:{ecosystem}/")
    }
    expected_os = installed_inventory(sbom_dir / inventory_filename, ecosystem)
    missing_os = sorted(expected_os - actual_os)
    if missing_os:
        formatted = ", ".join(f"{name}=={version}" for name, version in missing_os[:10])
        raise SystemExit(
            f"{filename} omits {len(missing_os)} of {len(expected_os)} installed "
            f"{ecosystem} packages: {formatted}"
        )
    if filename == "avelren-candidate.cdx.json":
        actual_python = {
            (
                re.sub(r"[-_.]+", "-", component.get("name", "")).lower(),
                component.get("version", ""),
            )
            for component in components
            if component.get("purl", "").startswith("pkg:pypi/")
        }
        missing = sorted(expected_python - actual_python)
        if missing:
            formatted = ", ".join(f"{name}=={version}" for name, version in missing)
            raise SystemExit(f"Candidate image SBOM is missing locked Python packages: {formatted}")
    print(f"{filename}: all {len(expected_os)} installed {ecosystem} packages are present")

print(f"Runtime image SBOMs: all {len(expected_python)} locked Python packages are present")
