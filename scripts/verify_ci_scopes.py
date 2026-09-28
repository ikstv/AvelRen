"""Регресійні приклади поділу CI; перевіряємо YAML, не запускаємо збірки."""

import re
from fnmatch import fnmatchcase
from pathlib import Path

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

image_job = supply_chain["jobs"].get("image-sbom")
if image_job is None:
    raise SystemExit("Supply-chain workflow must scan runtime image candidates")
if image_job.get("permissions") != {"contents": "read"}:
    raise SystemExit("Runtime image SBOM job must use contents: read only")
image_steps = image_job["steps"]
image_uses = [step.get("uses", "") for step in image_steps]
for action in image_uses:
    if action and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", action):
        raise SystemExit(f"Runtime image action is not pinned to a full SHA: {action}")

image_checkout = next(
    step for step in image_steps if step.get("uses", "").startswith("actions/checkout@")
)
if image_checkout.get("with", {}).get("persist-credentials") != "false":
    raise SystemExit("Runtime image checkout must not persist credentials")
build = next(step for step in image_steps if "docker build" in step.get("run", ""))
build_run = build["run"]
for required in (
    "SOURCE_COMMIT=${GITHUB_SHA}",
    "avelren-candidate:${GITHUB_SHA}",
    "services/backend",
    'test "$embedded_commit" = "$GITHUB_SHA"',
):
    if required not in build_run:
        raise SystemExit(f"Runtime image candidate build must include {required}")

image_scans = [
    step for step in image_steps
    if step.get("uses", "").startswith("anchore/sbom-action@")
]
build_index = image_steps.index(build)
candidate_scan_indices = [
    image_steps.index(step)
    for step in image_scans
    if step.get("with", {}).get("image", "").startswith("avelren-candidate:")
]
if any(index <= build_index for index in candidate_scan_indices):
    raise SystemExit("Build and attest the app candidate before scanning it")
expected_images = {
    "avelren-candidate:${{ github.sha }}",
    "timescale/timescaledb:2.30.1-pg16@sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9",
    "caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b",
}
actual_images = set()
image_sbom_paths = set()
for step in image_scans:
    image_with = step.get("with", {})
    if image_with.get("format") != "cyclonedx-json":
        raise SystemExit("Runtime image SBOMs must be CycloneDX JSON")
    if image_with.get("syft-version") != "v1.51.1":
        raise SystemExit("Runtime image SBOMs must use pinned Syft v1.51.1")
    if image_with.get("upload-artifact") != "false" or image_with.get("upload-release-assets") != "false":
        raise SystemExit("Anchore image scans must not upload their own artifacts")
    if image_with.get("image"):
        actual_images.add(image_with["image"])
    output_file = image_with.get("output-file", "")
    if not output_file.startswith("${{ runner.temp }}/runtime-image-sbom/"):
        raise SystemExit("Each runtime image SBOM must be written to the runner temp directory")
    image_sbom_paths.add(output_file)
if actual_images != expected_images:
    raise SystemExit(f"Runtime image scans mismatch: {actual_images} != {expected_images}")
if len(image_scans) != 3 or len(image_sbom_paths) != 3:
    raise SystemExit("Each runtime image must have one uniquely named SBOM output")

verify_index = next(
    index for index, step in enumerate(image_steps)
    if "scripts/verify_runtime_image_sboms.py" in step.get("run", "")
)
upload_index = next(
    index for index, step in enumerate(image_steps)
    if step.get("uses", "").startswith("actions/upload-artifact@")
)
scan_indices = [image_steps.index(step) for step in image_scans]
if not max(scan_indices) < verify_index < upload_index:
    raise SystemExit("Generate all image SBOMs, validate them, then upload the artifact")
verify_images = image_steps[verify_index]
if not verify_images.get("run", "").startswith("python3 scripts/verify_runtime_image_sboms.py"):
    raise SystemExit("Runtime image SBOMs must be checked for package coverage")
inventory_indices = [
    index for index, step in enumerate(image_steps)
    if "dpkg-query" in step.get("run", "")
]
if not inventory_indices:
    raise SystemExit("Runtime image SBOM validation must compare installed package-manager inventories")
inventory_index = inventory_indices[0]
inventory_run = image_steps[inventory_index]["run"]
for required in (
    "--entrypoint apk",
    "--network=no",
    "info -v",
    "avelren-candidate.deb.txt",
    "timescaledb.apk.txt",
    "caddy.apk.txt",
):
    if required not in inventory_run:
        raise SystemExit(f"Runtime image package-manager inventory must include {required}")
if not max(scan_indices) < inventory_index < verify_index:
    raise SystemExit("Compare package-manager inventory after scans and before validation")
if "runtime-image-sbom" not in verify_images["run"]:
    raise SystemExit("Runtime image verifier must read package-manager inventory artifacts")
image_upload = image_steps[upload_index]
image_upload_with = image_upload.get("with", {})
if image_upload_with.get("retention-days") != "30" or image_upload_with.get("if-no-files-found") != "error":
    raise SystemExit("Runtime image SBOM artifact must fail if absent and expire after 30 days")
if image_upload_with.get("name") != "runtime-image-sbom-${{ github.sha }}":
    raise SystemExit("Runtime image SBOM artifact name must include the source commit SHA")
if image_upload_with.get("path") != "${{ runner.temp }}/runtime-image-sbom/*.cdx.json":
    raise SystemExit("Runtime image SBOM artifact must contain the generated CycloneDX files")
if any("docker push" in step.get("run", "") for step in image_steps):
    raise SystemExit("Candidate image job must not publish container images")

print(f"CI scopes: {len(cases) * 2} examples passed; supply-chain workflow contract passed")
