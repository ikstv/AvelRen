"""Регресійні приклади поділу CI; перевіряємо YAML, не запускаємо збірки."""

from fnmatch import fnmatchcase
from pathlib import Path
import re

import yaml

root = Path(__file__).resolve().parents[1]
names = ("backend-core", "api", "database", "watchdog", "android")
workflows = {
    name: yaml.load(
        (root / ".github/workflows" / f"{name}.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    for name in names
}
backend = {"backend-core", "api", "database", "watchdog"}
cases = {
    "apps/android/app/src/main/java/ua/avelren/app/ui/AvelRenScreen.kt": {"android"},
    "docs/ANDROID-PROVENANCE.json": {"android"},
    "services/backend/src/avelren/watchdog.py": backend,
    "services/backend/src/avelren/api.py": backend | {"android"},
    "services/backend/src/avelren/maintenance.py": backend | {"android"},
    "docs/API-PROVENANCE.json": backend,
    "docs/RELEASE-READINESS.md": set(),
}
for event in ("pull_request", "push"):
    for file, expected in cases.items():
        actual = {
            name for name, workflow in workflows.items()
            if any(fnmatchcase(file, pattern) for pattern in workflow["on"][event]["paths"])
        }
        if actual != expected:
            raise SystemExit(f"CI scope mismatch: {event} {file}: {actual} != {expected}")

supply_chain = yaml.load(
    (root / ".github/workflows/supply-chain.yml").read_text(encoding="utf-8"),
    Loader=yaml.BaseLoader,
)
if set(supply_chain["on"]) != {"pull_request", "push"}:
    raise SystemExit("Supply-chain workflow must run on PRs and pushes")
if supply_chain["on"]["pull_request"]["branches"] != ["main"]:
    raise SystemExit("Supply-chain PR scan must target main")
if supply_chain["on"]["push"]["branches"] != ["main"]:
    raise SystemExit("Supply-chain push scan must be limited to main")
if supply_chain["permissions"] != {"contents": "read"}:
    raise SystemExit("Supply-chain workflow must use contents: read only")

steps = supply_chain["jobs"]["source-sbom"]["steps"]
uses = [step.get("uses", "") for step in steps]
for action in uses:
    if action and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", action):
        raise SystemExit(f"Action is not pinned to a full SHA: {action}")

checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
if checkout.get("with", {}).get("persist-credentials") != "false":
    raise SystemExit("Supply-chain checkout must not persist credentials")

generate = next(step for step in steps if step.get("uses", "").startswith("anchore/sbom-action@"))
prepare_index = next(
    index for index, step in enumerate(steps)
    if "cp services/backend/requirements.lock services/backend/requirements.txt"
    in step.get("run", "")
)
generate_index = steps.index(generate)
if prepare_index >= generate_index:
    raise SystemExit("Python lock must be exposed before Syft scans the source tree")
generate_with = generate.get("with", {})
if generate_with.get("path") != "." or generate_with.get("format") != "cyclonedx-json":
    raise SystemExit("Source SBOM must scan the repository as CycloneDX JSON")
if generate_with.get("syft-version") != "v1.51.1":
    raise SystemExit("Syft version must be explicitly pinned")
if generate_with.get("upload-artifact") != "false" or generate_with.get("upload-release-assets") != "false":
    raise SystemExit("Anchore artifact and release uploads must remain disabled")

validate_index = next(
    index for index, step in enumerate(steps)
    if "scripts/verify_source_sbom.py" in step.get("run", "")
)
cleanup_index = next(
    index for index, step in enumerate(steps)
    if "rm -f services/backend/requirements.txt" in step.get("run", "")
)
if not generate_index < validate_index < cleanup_index:
    raise SystemExit("Validate the Python lock from the SBOM before cleaning the temporary alias")
if steps[cleanup_index].get("if") != "always()":
    raise SystemExit("Temporary Python requirements alias must be cleaned even after scan failures")

upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
upload_with = upload.get("with", {})
if upload_with.get("retention-days") != "30" or upload_with.get("if-no-files-found") != "error":
    raise SystemExit("SBOM artifact must fail if absent and expire after 30 days")
if upload_with.get("name") != "source-sbom-${{ github.sha }}":
    raise SystemExit("SBOM artifact name must include the source commit SHA")
if upload_with.get("path") != "${{ runner.temp }}/avelren-source.cdx.json":
    raise SystemExit("SBOM artifact must upload the generated file from runner temp")

print(f"CI scopes: {len(cases) * 2} examples passed; supply-chain workflow contract passed")
