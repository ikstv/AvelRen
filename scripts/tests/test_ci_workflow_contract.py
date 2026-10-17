"""Граф CI має вимагати потрібні jobs і зберігати відмови перевірок."""

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
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


def load(name, root=ROOT):
    path = root / ".github/workflows" / name
    return (
        yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader) if path.exists() else {}
    )


def test_paired_backup_root_contract_callers_and_guard_wiring():
    steps = load("database.yml")["jobs"]["database"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps).splitlines()
    assert "sudo bash ops/collector-runtime-control-contract-test.sh" in commands
    assert "sudo python3 ops/collector-runtime-control-contract-test.py" not in commands
    assert "sudo bash ops/maintenance-window-contract-test.sh" in commands
    assert "bash -n ops/paired-backup-guard-contract-test.sh" in commands
    assert "sudo bash ops/paired-backup-guard-contract-test.sh" in commands


def test_database_runs_legacy_alert_hotfix_contracts():
    steps = load("database.yml")["jobs"]["database"]["steps"]
    commands = [step.get("run", "") for step in steps]
    assert (
        "python3 -B -m unittest discover -s ops/eta-legacy-hotfix "
        "-p 'test_legacy_*.py' -v"
    ) in commands


def test_database_runs_recovery_handoff_contracts():
    steps = load("database.yml")["jobs"]["database"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps).splitlines()
    assert "sudo python3 ops/collector-recovery-handoff-contract-test.py" in commands
    assert "python3 ops/collector-recovery-handoff-daemon-contract-test.py" in commands


def test_events():
    assert load("ci.yml").get("on") == {
        "pull_request": {
            "types": ["opened", "synchronize", "reopened", "ready_for_review", "edited"]
        },
        "push": {"branches": ["main"]},
    }


def test_edited_reruns():
    jobs = load("ci.yml").get("jobs", {})
    assert jobs, "Dispatcher is missing"
    assert "if" not in jobs["scope"]
    assert "if" not in jobs["gate"].get("steps", [{}])[-1]
    for component in CALLS:
        assert jobs[component]["if"] == f"needs.scope.outputs.{component} == 'true'"
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    for shortcut in ("github.event.action", ".changes", ".draft", ".title", ".body"):
        assert shortcut not in text


def test_graph():
    jobs = load("ci.yml").get("jobs", {})
    assert set(jobs) == {"scope", "gate", *CALLS}
    gate = jobs["gate"]
    assert gate["name"] == "CI gate"
    assert set(gate["needs"]) == {"scope", *CALLS}
    assert len(gate["needs"]) == 9
    assert gate["if"] == "${{ always() }}"
    assert gate["timeout-minutes"] == "2"
    for component, (filename, _) in CALLS.items():
        assert jobs[component] == {
            "needs": "scope",
            "if": f"needs.scope.outputs.{component} == 'true'",
            "uses": f"./.github/workflows/{filename}",
        }
    assert (
        sum(
            job.get("name") == "CI gate"
            for path in (ROOT / ".github/workflows").glob("*.yml")
            for job in load(path.name).get("jobs", {}).values()
        )
        == 1
    )


def test_permissions_refs():
    ci = load("ci.yml")
    assert ci.get("permissions") == {"contents": "read"}
    for filename in ["ci.yml", *(item[0] for item in CALLS.values())]:
        workflow = load(filename)
        assert workflow["permissions"] == {"contents": "read"}
        for job in workflow["jobs"].values():
            assert "secrets" not in job and "with" not in job
            if "permissions" in job:
                assert job["permissions"] == {"contents": "read"}
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("actions/checkout@"):
                    assert step["uses"] == CHECKOUT
                    assert step["with"]["ref"] == "${{ github.sha }}"
                    assert step["with"]["persist-credentials"] == "false"
    scope = ci["jobs"]["scope"]
    assert scope["timeout-minutes"] == "5"
    assert scope["steps"][0]["with"]["fetch-depth"] == "0"
    upload = scope["steps"][-1]
    assert upload["uses"] == UPLOAD
    assert upload["with"] == {
        "name": "ci-plan-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}",
        "path": "${{ runner.temp }}/ci-plan.json",
        "retention-days": "30",
        "if-no-files-found": "error",
    }


@pytest.mark.parametrize("filename,expected_jobs", CALLS.values())
def test_reusable_jobs(filename, expected_jobs):
    workflow = load(filename)
    assert workflow["on"] == {"workflow_call": {}}
    assert set(workflow["jobs"]) == expected_jobs
    for job in workflow["jobs"].values():
        assert "if" not in job and "continue-on-error" not in job
        for step in job["steps"]:
            assert "continue-on-error" not in step
            assert "if" not in step or (
                filename == "supply-chain.yml"
                and step["if"] == "always()"
                and "rm -f services/backend/requirements.txt" in step.get("run", "")
            )


def test_preservation():
    android = load("android.yml")["jobs"]["android"]["steps"]
    negative = [step["run"] for step in android if "--dry-run" in step.get("run", "")]
    assert len(negative) == 2
    for run in negative:
        assert "if bash gradlew" in run and "exit 1" in run
        assert "grep -q 'Android test modes are debug-only'" in run
    gradle = next(step for step in android if step.get("uses", "").startswith("gradle/actions/"))
    assert gradle["with"]["cache-read-only"] == (
        "${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.fork }}"
    )
    sbom = load("supply-chain.yml")["jobs"]
    assert set(sbom) == {"source-sbom", "image-sbom"}
    cleanup = next(
        step
        for step in sbom["source-sbom"]["steps"]
        if "rm -f services/backend/requirements.txt" in step.get("run", "")
    )
    assert cleanup["if"] == "always()"


def test_concurrency_outputs():
    ci = load("ci.yml")
    assert ci.get("concurrency") == {
        "group": "ci-${{ github.event_name }}-"
        "${{ github.event.pull_request.number || github.run_id }}",
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }
    assert "concurrency" not in load("android.yml")
    jobs = ci["jobs"]
    assert jobs["scope"]["outputs"] == {
        key: f"${{{{ steps.plan.outputs.{key} }}}}" for key in ["plan", *CALLS]
    }
    producer = next(step for step in jobs["scope"]["steps"] if step.get("id") == "plan")
    assert (
        producer["run"]
        == 'python3 scripts/ci_scopes.py --manifest .github/ci-scopes.json '
        '--plan-file "$RUNNER_TEMP/ci-plan.json"'
    )
    evaluator = jobs["gate"]["steps"][-1]
    assert evaluator["run"] == "python3 scripts/verify_ci_gate.py"
    assert evaluator["env"] == {
        "CI_PLAN_JSON": "${{ needs.scope.outputs.plan }}",
        "CI_NEEDS_JSON": "${{ toJSON(needs) }}",
    }


def verifier():
    module = importlib.import_module("scripts.verify_ci_scopes")
    assert hasattr(module, "verify_workflow_contracts"), "Common graph verifier is missing"
    return module


def test_common_verifier(capsys):
    module = verifier()
    assert capsys.readouterr().out == ""
    assert module.verify_workflow_contracts(ROOT) == []
    assert module.verify(ROOT) is None


def test_package_import_is_safe():
    result = subprocess.run(
        [sys.executable, "-c", "import scripts.verify_ci_scopes"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "" and result.stderr == ""


@pytest.mark.parametrize(
    "mutation",
    [
        "needs",
        "callee",
        "sbom",
        "job_if",
        "job_error",
        "step_error",
        "step_if",
        "unpinned",
        "write",
        "edited_shortcut",
        "scope_skip",
        "gate_skip",
        "output",
        "ref",
        "input",
        "missing_checkout",
        "shell_mask",
        "shell_no_errexit",
        "shell_success",
    ],
)
def test_verifier_rejects_mutations(tmp_path, mutation):
    module = verifier()
    shutil.copytree(ROOT / ".github", tmp_path / ".github")
    filename = "ci.yml"
    workflow = load(filename, tmp_path)
    if mutation == "needs":
        workflow["jobs"]["gate"]["needs"].remove("android")
    elif mutation == "callee":
        (tmp_path / ".github/workflows/api.yml").unlink()
    elif mutation == "output":
        del workflow["jobs"]["scope"]["outputs"]["android"]
    elif mutation == "edited_shortcut":
        workflow["jobs"]["android"]["if"] += " && github.event.action != 'edited'"
    elif mutation == "scope_skip":
        workflow["jobs"]["scope"]["if"] = "github.event.pull_request.draft == false"
    elif mutation == "gate_skip":
        workflow["jobs"]["gate"]["steps"][-1]["if"] = "success()"
    elif mutation == "input":
        workflow["jobs"]["api"]["with"] = {"command": "true"}
    elif mutation == "write":
        workflow["permissions"]["contents"] = "write"
    elif mutation in {"unpinned", "ref"}:
        checkout = workflow["jobs"]["scope"]["steps"][0]
        if mutation == "unpinned":
            checkout["uses"] = "actions/checkout@main"
        else:
            checkout["with"]["ref"] = "${{ github.event.pull_request.head.sha }}"
    else:
        filename = "supply-chain.yml"
        workflow = load(filename, tmp_path)
        job = workflow["jobs"]["source-sbom"]
        if mutation == "sbom":
            del workflow["jobs"]["image-sbom"]
        elif mutation == "missing_checkout":
            del job["steps"][0]
        elif mutation == "shell_mask":
            job["steps"][1]["run"] += " || true"
        elif mutation == "shell_no_errexit":
            job["steps"][1]["run"] = "set +e\n" + job["steps"][1]["run"]
        elif mutation == "shell_success":
            job["steps"][1]["run"] += "; exit 0"
        elif mutation == "job_if":
            job["if"] = "false"
        elif mutation == "job_error":
            job["continue-on-error"] = "true"
        elif mutation == "step_error":
            job["steps"][1]["continue-on-error"] = "true"
        else:
            job["steps"][1]["if"] = "false"
    (tmp_path / ".github/workflows" / filename).write_text(
        yaml.safe_dump(workflow), encoding="utf-8"
    )
    assert module.verify_workflow_contracts(tmp_path), mutation
