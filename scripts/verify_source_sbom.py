"""Перевіряє, що source SBOM містить усі hash-locked Python-пакети."""

import json
import re
import sys
from pathlib import Path


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


sbom_path = Path(sys.argv[1])
lock_path = Path(sys.argv[2])
sbom = json.loads(sbom_path.read_text(encoding="utf-8"))

expected = set()
requirement = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)")
for line in lock_path.read_text(encoding="utf-8").splitlines():
    match = requirement.match(line.strip())
    if match:
        expected.add((normalize_name(match.group(1)), match.group(2)))

actual = {
    (normalize_name(component.get("name", "")), component.get("version", ""))
    for component in sbom.get("components", [])
    if component.get("purl", "").startswith("pkg:pypi/")
}

missing = sorted(expected - actual)
if missing:
    formatted = ", ".join(f"{name}=={version}" for name, version in missing)
    raise SystemExit(f"Source SBOM is missing {len(missing)} locked Python packages: {formatted}")

if sbom.get("bomFormat") != "CycloneDX":
    raise SystemExit("Source SBOM is not CycloneDX")

print(f"Source SBOM: all {len(expected)} locked Python packages are present")
