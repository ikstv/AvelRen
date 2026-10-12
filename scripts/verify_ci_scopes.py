"""Регресійні приклади поділу CI; перевіряємо YAML, не запускаємо збірки."""

import re
import sys
from pathlib import Path

import yaml

if __package__:
    from .ci_scopes import classify_paths, load_manifest
else:
    from ci_scopes import classify_paths, load_manifest

CALLS = {
    "backend_core": ("backend-core.yml", {"core"}),
    "api": ("api.yml", {"api"}),
    "database": ("database.yml", {"database"}),
    "watchdog": ("watchdog.yml", {"watchdog"}),
    "android": ("android.yml", {"android"}),
    "repository": ("repository.yml", {"repository"}),
    "monitor_contracts": ("external-monitor-checks.yml", {"monitor-contracts"}),
    "supply_chain": ("supply-chain.yml", {"source-sbom", "image-sbom"}),
}
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
PYTHON_CHECK = (
    "python3 -c 'import sys; assert sys.version_info >= (3, 12), \"Python >=3.12 required\"'"
)


def verify_workflow_contracts(root: Path) -> list[str]:
    """Перевірити весь локальний граф; та сама перевірка для CLI і mutations."""
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    def load(filename):
        try:
            result = yaml.load(
                (root / ".github/workflows" / filename).read_text(encoding="utf-8"),
                Loader=yaml.BaseLoader,
            )
            if not isinstance(result, dict):
                raise ValueError("Expected workflow object")
            return result
        except (OSError, ValueError, yaml.YAMLError) as error:
            errors.append(f"{filename}: {error}")
            return {}

    try:
        manifest = load_manifest(root / ".github/ci-scopes.json")
        require(
            {key: item["workflow"] for key, item in manifest["components"].items()}
            == {key: item[0] for key, item in CALLS.items()},
            "Manifest/callee mismatch",
        )
    except (OSError, ValueError) as error:
        errors.append(f"Manifest: {error}")

    ci = load("ci.yml")
    require(ci.get("name") == "CI", "Dispatcher name must be CI")
    require(
        ci.get("on")
        == {
            "pull_request": {
                "types": ["opened", "synchronize", "reopened", "ready_for_review", "edited"]
            },
            "push": {"branches": ["main"]},
        },
        "Dispatcher events must include all PR targets/drafts/edited and only main pushes",
    )
    require(
        ci.get("concurrency")
        == {
            "group": "ci-${{ github.event_name }}-"
            "${{ github.event.pull_request.number || github.run_id }}",
            "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
        },
        "Concurrency must cancel by PR number and preserve unique main runs",
    )
    jobs = ci.get("jobs", {})
    require(set(jobs) == {"scope", "gate", *CALLS}, "Dispatcher must contain exactly ten jobs")
    for component, (filename, _) in CALLS.items():
        require(
            jobs.get(component)
            == {
                "needs": "scope",
                "if": f"needs.scope.outputs.{component} == 'true'",
                "uses": f"./.github/workflows/{filename}",
            },
            f"{component}: call must depend only on the scope flag and exact local workflow",
        )
    scope, gate = jobs.get("scope", {}), jobs.get("gate", {})
    require(
        scope.get("runs-on") == "ubuntu-latest" and scope.get("timeout-minutes") == "5",
        "Scope runner/timeout mismatch",
    )
    require(
        scope.get("outputs")
        == {key: f"${{{{ steps.plan.outputs.{key} }}}}" for key in ["plan", *CALLS]},
        "Scope must expose the compact plan and exactly eight producer flags",
    )
    require(
        gate.get("name") == "CI gate"
        and gate.get("runs-on") == "ubuntu-latest"
        and gate.get("timeout-minutes") == "2",
        "Gate name/runner/timeout mismatch",
    )
    needs = gate.get("needs", [])
    require(
        isinstance(needs, list) and len(needs) == 9 and set(needs) == {"scope", *CALLS},
        "Gate must need scope and all eight calls",
    )
    require(
        gate.get("if") == "${{ always() }}", "Gate must always evaluate failed/skipped dependencies"
    )

    scope_steps, gate_steps = scope.get("steps", []), gate.get("steps", [])
    require(
        len(scope_steps) == 4 and len(gate_steps) == 3, "Scope/gate steps must remain unconditional"
    )
    if len(scope_steps) == 4:
        require(
            scope_steps[0].get("with")
            == {
                "ref": "${{ github.sha }}",
                "persist-credentials": "false",
                "fetch-depth": "0",
            },
            "Scope checkout requires full history at the tested SHA",
        )
        require(scope_steps[1].get("run") == PYTHON_CHECK, "Scope needs stdlib Python >=3.12")
        require(
            scope_steps[2].get("id") == "plan"
            and scope_steps[2].get("run")
            == 'python3 scripts/ci_scopes.py --manifest .github/ci-scopes.json '
            '--plan-file "$RUNNER_TEMP/ci-plan.json"',
            "Scope producer command mismatch",
        )
        require(
            scope_steps[3].get("uses") == UPLOAD
            and scope_steps[3].get("with")
            == {
                "name": "ci-plan-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}",
                "path": "${{ runner.temp }}/ci-plan.json",
                "retention-days": "30",
                "if-no-files-found": "error",
            },
            "Scope artifact must be pinned, uniquely named and required",
        )
    if len(gate_steps) == 3:
        require(gate_steps[1].get("run") == PYTHON_CHECK, "Gate needs stdlib Python >=3.12")
        require(
            gate_steps[2].get("run") == "python3 scripts/verify_ci_gate.py"
            and gate_steps[2].get("env")
            == {
                "CI_PLAN_JSON": "${{ needs.scope.outputs.plan }}",
                "CI_NEEDS_JSON": "${{ toJSON(needs) }}",
            },
            "Gate must evaluate this run's complete needs and plan via env",
        )

    workflows = {filename: load(filename) for filename, _ in CALLS.values()}
    for filename, expected_jobs in CALLS.values():
        workflow = workflows[filename]
        require(
            workflow.get("on") == {"workflow_call": {}},
            f"{filename}: reusable-only without inputs/secrets",
        )
        require(
            set(workflow.get("jobs", {})) == expected_jobs, f"{filename}: internal jobs mismatch"
        )
        require("concurrency" not in workflow, f"{filename}: caller owns concurrency")
    for filename, workflow in {"ci.yml": ci, **workflows}.items():
        require(
            workflow.get("permissions") == {"contents": "read"},
            f"{filename}: read-only permissions required",
        )
        for job_id, job in workflow.get("jobs", {}).items():
            label = f"{filename}/{job_id}"
            if "uses" not in job:
                require(
                    sum(step.get("uses") == CHECKOUT for step in job.get("steps", [])) == 1,
                    f"{label}: exactly one pinned tested-SHA checkout required",
                )
            require(
                "continue-on-error" not in job and "secrets" not in job and "with" not in job,
                f"{label}: error masking, secrets and command inputs forbidden",
            )
            require(
                "if" not in job or (filename == "ci.yml" and job_id != "scope"),
                f"{label}: internal jobs and scope must not skip",
            )
            require(
                "permissions" not in job or job["permissions"] == {"contents": "read"},
                f"{label}: job must not elevate permissions",
            )
            for step in job.get("steps", []):
                require("continue-on-error" not in step, f"{label}: step error masking forbidden")
                require(
                    not re.search(
                        r"\|\|\s*(?:true\b|:)|\bset\s+\+e\b|\bexit\s+0\b",
                        step.get("run", ""),
                    ),
                    f"{label}: shell must propagate errors; "
                    "negative shell assertions remain allowed",
                )
                cleanup = (
                    filename == "supply-chain.yml"
                    and job_id == "source-sbom"
                    and (
                        step.get("if") == "always()"
                        and step.get("run") == "rm -f services/backend/requirements.txt"
                    )
                )
                require("if" not in step or cleanup, f"{label}: required steps must not skip")
                action = step.get("uses", "")
                require(
                    not action or re.fullmatch(r"[^@]+@[0-9a-f]{40}", action),
                    f"{label}: action must be SHA pinned",
                )
                if action.startswith("actions/checkout@"):
                    require(
                        action == CHECKOUT
                        and step.get("with", {}).get("ref") == "${{ github.sha }}"
                        and step.get("with", {}).get("persist-credentials") == "false",
                        f"{label}: checkout must bind tested SHA without credentials",
                    )
    gate_names = sum(
        job.get("name") == "CI gate"
        for path in (root / ".github/workflows").glob("*.yml")
        for job in load(path.name).get("jobs", {}).values()
    )
    require(gate_names == 1, "CI gate name must be unique")
    return errors


def verify(root: Path) -> None:
    errors = verify_workflow_contracts(root)
    if errors:
        raise ValueError("\n".join(errors))
    names = ("backend-core", "api", "database", "watchdog", "android")
    manifest = load_manifest(root / ".github/ci-scopes.json")
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
        "ops/collector-runtime-control.py": {"api", "database", "watchdog"},
        "ops/collector-runtime-control.sh": {"api", "database", "watchdog"},
        "ops/collector-runtime-preflight.py": {"api", "database", "watchdog"},
        "ops/compose.collector-runtime.yml": {"api", "database", "watchdog"},
        "ops/collector-runtime-integration-test.sh": {"api", "database", "watchdog"},
        "ops/Dockerfile.collector-runtime-test-controller": {"api", "database", "watchdog"},
    }
    for event in ("pull_request", "push"):
        for file, expected in cases.items():
            selected, _ = classify_paths([file], manifest, event_name=event, target_branch="main")
            actual = {name for name in names if selected[name.replace("-", "_")]}
            if actual != expected:
                raise ValueError(f"CI scope mismatch: {event} {file}: {actual} != {expected}")

    database_runs = "\n".join(
        step.get("run", "") for step in workflows["database"]["jobs"]["database"]["steps"]
    )
    for check in (
        "python3 ops/collector-runtime-contract-test.py",
        "bash ops/collector-runtime-control-contract-test.sh",
        "bash ops/collector-runtime-integration-test.sh",
    ):
        if check not in database_runs:
            raise ValueError("Missing collector runtime CI gate: " + check)

    supply_chain = yaml.load(
        (root / ".github/workflows/supply-chain.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    if supply_chain["permissions"] != {"contents": "read"}:
        raise ValueError("Supply-chain workflow must use contents: read only")

    steps = supply_chain["jobs"]["source-sbom"]["steps"]
    uses = [step.get("uses", "") for step in steps]
    for action in uses:
        if action and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", action):
            raise ValueError(f"Action is not pinned to a full SHA: {action}")

    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    if checkout.get("with", {}).get("persist-credentials") != "false":
        raise ValueError("Supply-chain checkout must not persist credentials")

    generate = next(
        step for step in steps if step.get("uses", "").startswith("anchore/sbom-action@")
    )
    prepare_index = next(
        index
        for index, step in enumerate(steps)
        if "cp services/backend/requirements.lock services/backend/requirements.txt"
        in step.get("run", "")
    )
    generate_index = steps.index(generate)
    if prepare_index >= generate_index:
        raise ValueError("Python lock must be exposed before Syft scans the source tree")
    generate_with = generate.get("with", {})
    if generate_with.get("path") != "." or generate_with.get("format") != "cyclonedx-json":
        raise ValueError("Source SBOM must scan the repository as CycloneDX JSON")
    if generate_with.get("syft-version") != "v1.51.1":
        raise ValueError("Syft version must be explicitly pinned")
    if (
        generate_with.get("upload-artifact") != "false"
        or generate_with.get("upload-release-assets") != "false"
    ):
        raise ValueError("Anchore artifact and release uploads must remain disabled")

    validate_index = next(
        index
        for index, step in enumerate(steps)
        if "scripts/verify_source_sbom.py" in step.get("run", "")
    )
    cleanup_index = next(
        index
        for index, step in enumerate(steps)
        if "rm -f services/backend/requirements.txt" in step.get("run", "")
    )
    if not generate_index < validate_index < cleanup_index:
        raise ValueError(
            "Validate the Python lock from the SBOM before cleaning the temporary alias"
        )
    if steps[cleanup_index].get("if") != "always()":
        raise ValueError(
            "Temporary Python requirements alias must be cleaned even after scan failures"
        )

    upload = next(
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    upload_with = upload.get("with", {})
    if upload_with.get("retention-days") != "30" or upload_with.get("if-no-files-found") != "error":
        raise ValueError("SBOM artifact must fail if absent and expire after 30 days")
    if upload_with.get("name") != "source-sbom-${{ github.sha }}":
        raise ValueError("SBOM artifact name must include the source commit SHA")
    if upload_with.get("path") != "${{ runner.temp }}/avelren-source.cdx.json":
        raise ValueError("SBOM artifact must upload the generated file from runner temp")

    image_job = supply_chain["jobs"].get("image-sbom")
    if image_job is None:
        raise ValueError("Supply-chain workflow must scan runtime image candidates")
    if image_job.get("permissions") != {"contents": "read"}:
        raise ValueError("Runtime image SBOM job must use contents: read only")
    image_steps = image_job["steps"]
    image_uses = [step.get("uses", "") for step in image_steps]
    for action in image_uses:
        if action and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", action):
            raise ValueError(f"Runtime image action is not pinned to a full SHA: {action}")

    image_checkout = next(
        step for step in image_steps if step.get("uses", "").startswith("actions/checkout@")
    )
    if image_checkout.get("with", {}).get("persist-credentials") != "false":
        raise ValueError("Runtime image checkout must not persist credentials")
    build = next(step for step in image_steps if "docker build" in step.get("run", ""))
    build_run = build["run"]
    for required in (
        "SOURCE_COMMIT=${GITHUB_SHA}",
        "avelren-candidate:${GITHUB_SHA}",
        "services/backend",
        'test "$embedded_commit" = "$GITHUB_SHA"',
    ):
        if required not in build_run:
            raise ValueError(f"Runtime image candidate build must include {required}")

    image_scans = [
        step for step in image_steps if step.get("uses", "").startswith("anchore/sbom-action@")
    ]
    build_index = image_steps.index(build)
    candidate_scan_indices = [
        image_steps.index(step)
        for step in image_scans
        if step.get("with", {}).get("image", "").startswith("avelren-candidate:")
    ]
    if any(index <= build_index for index in candidate_scan_indices):
        raise ValueError("Build and attest the app candidate before scanning it")
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
            raise ValueError("Runtime image SBOMs must be CycloneDX JSON")
        if image_with.get("syft-version") != "v1.51.1":
            raise ValueError("Runtime image SBOMs must use pinned Syft v1.51.1")
        if (
            image_with.get("upload-artifact") != "false"
            or image_with.get("upload-release-assets") != "false"
        ):
            raise ValueError("Anchore image scans must not upload their own artifacts")
        if image_with.get("image"):
            actual_images.add(image_with["image"])
        output_file = image_with.get("output-file", "")
        if not output_file.startswith("${{ runner.temp }}/runtime-image-sbom/"):
            raise ValueError("Each runtime image SBOM must be written to the runner temp directory")
        image_sbom_paths.add(output_file)
    if actual_images != expected_images:
        raise ValueError(f"Runtime image scans mismatch: {actual_images} != {expected_images}")
    if len(image_scans) != 3 or len(image_sbom_paths) != 3:
        raise ValueError("Each runtime image must have one uniquely named SBOM output")

    verify_index = next(
        index
        for index, step in enumerate(image_steps)
        if "scripts/verify_runtime_image_sboms.py" in step.get("run", "")
    )
    upload_index = next(
        index
        for index, step in enumerate(image_steps)
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    scan_indices = [image_steps.index(step) for step in image_scans]
    if not max(scan_indices) < verify_index < upload_index:
        raise ValueError("Generate all image SBOMs, validate them, then upload the artifact")
    verify_images = image_steps[verify_index]
    if not verify_images.get("run", "").startswith("python3 scripts/verify_runtime_image_sboms.py"):
        raise ValueError("Runtime image SBOMs must be checked for package coverage")
    inventory_indices = [
        index for index, step in enumerate(image_steps) if "dpkg-query" in step.get("run", "")
    ]
    if not inventory_indices:
        raise ValueError(
            "Runtime image SBOM validation must compare installed package-manager inventories"
        )
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
            raise ValueError(f"Runtime image package-manager inventory must include {required}")
    if not max(scan_indices) < inventory_index < verify_index:
        raise ValueError("Compare package-manager inventory after scans and before validation")
    if "runtime-image-sbom" not in verify_images["run"]:
        raise ValueError("Runtime image verifier must read package-manager inventory artifacts")
    image_upload = image_steps[upload_index]
    image_upload_with = image_upload.get("with", {})
    if (
        image_upload_with.get("retention-days") != "30"
        or image_upload_with.get("if-no-files-found") != "error"
    ):
        raise ValueError("Runtime image SBOM artifact must fail if absent and expire after 30 days")
    if image_upload_with.get("name") != "runtime-image-sbom-${{ github.sha }}":
        raise ValueError("Runtime image SBOM artifact name must include the source commit SHA")
    if image_upload_with.get("path") != "${{ runner.temp }}/runtime-image-sbom/*.cdx.json":
        raise ValueError("Runtime image SBOM artifact must contain the generated CycloneDX files")
    if any("docker push" in step.get("run", "") for step in image_steps):
        raise ValueError("Candidate image job must not publish container images")


def main() -> int:
    try:
        verify(Path(__file__).resolve().parents[1])
    except (ValueError, OSError, KeyError, StopIteration, yaml.YAMLError) as error:
        print(f"CI scopes failed: {error}", file=sys.stderr)
        return 1
    print(
        "CI scopes: 26 examples passed; supply-chain workflow contract passed; "
        "aggregate gate contract passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
