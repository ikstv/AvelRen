"""Перевіряє покриття Python та OS пакетів у runtime image SBOMs."""

import json
import re
import sys
from pathlib import Path


sbom_dir = Path(sys.argv[1])
lock_path = Path(sys.argv[2])
expected_files = {
    "avelren-candidate.cdx.json": "deb",
    "timescaledb.cdx.json": "deb",
    "caddy.cdx.json": "apk",
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

for filename, ecosystem in expected_files.items():
    path = sbom_dir / filename
    if not path.is_file():
        raise SystemExit(f"Missing runtime image SBOM: {filename}")
    sbom = json.loads(path.read_text(encoding="utf-8"))
    if sbom.get("bomFormat") != "CycloneDX":
        raise SystemExit(f"{filename} is not CycloneDX")
    components = sbom.get("components", [])
    if not any(component.get("purl", "").startswith(f"pkg:{ecosystem}/") for component in components):
        raise SystemExit(f"{filename} has no {ecosystem} OS packages")
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

print(
    "Runtime image SBOMs: candidate Python lock and Debian/Alpine OS package coverage passed"
)
