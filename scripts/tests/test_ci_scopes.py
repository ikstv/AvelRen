"""Незалежні приклади залежностей і безпечного вибору CI."""

import copy
import json
from pathlib import Path

import pytest

from scripts.ci_scopes import COMPONENT_IDS, classify_paths, load_manifest, match_path

ROOT = Path(__file__).resolve().parents[2]
LEGACY_IDS = {"backend_core", "api", "database", "watchdog", "android"}
BACKEND = {"backend_core", "api", "database", "watchdog"}
LEGACY_CASES = [
    ("apps/android/app/src/main/java/ua/avelren/app/ui/AvelRenScreen.kt", {"android"}),
    ("docs/ANDROID-PROVENANCE.json", {"android"}),
    ("services/backend/src/avelren/watchdog.py", BACKEND),
    ("services/backend/src/avelren/api.py", BACKEND | {"android"}),
    ("services/backend/src/avelren/maintenance.py", BACKEND | {"android"}),
    ("docs/API-PROVENANCE.json", BACKEND),
    ("docs/RELEASE-READINESS.md", set()),
    ("ops/collector-runtime-control.py", {"api", "database", "watchdog"}),
    ("ops/collector-runtime-control.sh", {"api", "database", "watchdog"}),
    ("ops/collector-runtime-preflight.py", {"api", "database", "watchdog"}),
    ("ops/compose.collector-runtime.yml", {"api", "database", "watchdog"}),
    ("ops/collector-runtime-integration-test.sh", {"api", "database", "watchdog"}),
    ("ops/Dockerfile.collector-runtime-test-controller", {"api", "database", "watchdog"}),
]


@pytest.fixture
def manifest():
    return load_manifest(ROOT / ".github/ci-scopes.json")


def selected(paths, manifest, event="pull_request", branch="main"):
    required, reason = classify_paths(paths, manifest, event_name=event, target_branch=branch)
    assert set(required) == set(COMPONENT_IDS)
    assert all(type(value) is bool for value in required.values())
    return {key for key, value in required.items() if value}, reason


@pytest.mark.parametrize("event", ["pull_request", "push"])
@pytest.mark.parametrize("path,expected", LEGACY_CASES)
def test_legacy_26_scopes(manifest, event, path, expected):
    actual, reason = selected([path], manifest, event)
    assert actual & LEGACY_IDS == expected
    assert {"repository", "supply_chain"} <= actual
    assert reason == "matched"


def test_docs_only_and_empty(manifest):
    for paths in (["docs/RELEASE-READINESS.md"], [], ["docs/deep/a.md", "INTEGRATION.md"]):
        assert selected(paths, manifest) == ({"repository", "supply_chain"}, "matched")


def test_non_main_pr(manifest):
    assert selected(["README.md"], manifest, branch="release") == ({"repository"}, "matched")
    assert selected(["apps/android/a.kt"], manifest, branch="release") == (
        {"repository", "android"}, "matched"
    )


@pytest.mark.parametrize("path", ["schemas.py", "surge.py", "surge_policy.py"])
def test_api_contract(manifest, path):
    assert selected(["services/backend/src/avelren/" + path], manifest)[0] == (
        BACKEND | {"android", "repository", "supply_chain"}
    )


@pytest.mark.parametrize("path", [
    "scripts/classify_alert_channel.py", "scripts/tests/test_alert.py"
])
def test_monitor(manifest, path):
    assert selected([path], manifest) == (
        {"monitor_contracts", "repository", "supply_chain"}, "matched"
    )


@pytest.mark.parametrize("path,expected", [
    ("docs/ASSETS.md", {"android"}),
    ("docs/CORE-PROVENANCE.json", BACKEND),
    ("docs/DB-PROVENANCE.json", BACKEND),
    ("docs/WATCHDOG-PROVENANCE.json", BACKEND),
])
def test_provenance_precedes_docs(manifest, path, expected):
    assert selected([path], manifest)[0] == expected | {"repository", "supply_chain"}


@pytest.mark.parametrize("path", ["scripts/new-tool.py", "new.config", "docs/new.json"])
@pytest.mark.parametrize("branch", ["main", "release"])
def test_unknown_path(manifest, path, branch):
    assert selected([path], manifest, branch=branch) == (set(COMPONENT_IDS), "unknown_path")


@pytest.mark.parametrize("path", [
    ".github/workflows/android.yml", ".github/workflows/nested/new.yml",
    ".github/ci-scopes.json", "scripts/ci_scopes.py", "scripts/verify_ci_gate.py",
    "scripts/verify_ci_scopes.py", "scripts/tests/test_ci_scopes.py",
    "scripts/tests/test_ci_gate.py", "scripts/tests/test_ci_workflow_contract.py",
])
@pytest.mark.parametrize("branch", ["main", "release"])
def test_control_change(manifest, path, branch):
    assert selected([path], manifest, branch=branch) == (set(COMPONENT_IDS), "control_change")


def test_docs_do_not_suppress_code_or_controls(manifest):
    assert selected(["README.md", "apps/android/a.kt"], manifest)[0] == {
        "android", "repository", "supply_chain"
    }
    assert selected(["new.config", ".github/ci-scopes.json"], manifest)[1] == "control_change"


@pytest.mark.parametrize("path,pattern,expected", [
    ("docs/a.md", "docs/**/*.md", True),
    ("docs/a/b.md", "docs/**/*.md", True),
    ("docs/a/b.md", "docs/*.md", False),
    ("a/b/c", "**/c", True), ("c", "**/c", True),
    ("docs", "docs/**", True), ("docs/a/b", "docs/**", True),
    ("surge.py", "surge*.py", True), ("surge/a.py", "surge*.py", False),
    ("docs/aXmd", "docs/a.md", False),
])
def test_glob(path, pattern, expected):
    assert match_path(path, pattern) is expected


@pytest.mark.parametrize("pattern", ["!docs/**", "/docs/**", "../a", "docs/../a",
    "C:/a", "docs\\a", "docs//a", "docs/?", "docs/[ab]", "docs/{a,b}",
    "docs/a**b", "docs/", "", "./a", "docs/a\n"])
def test_invalid_glob(pattern):
    with pytest.raises(ValueError):
        match_path("docs/a", pattern)


@pytest.mark.parametrize("path", ["/a", "../a", "docs/../a", "a\\b", "a//b", "", "a\n"])
def test_invalid_paths(manifest, path):
    with pytest.raises(ValueError):
        selected([path], manifest)


@pytest.mark.parametrize("event,branch", [("workflow_dispatch", "main"), ("push", "")])
def test_invalid_event(manifest, event, branch):
    with pytest.raises(ValueError):
        selected([], manifest, event, branch)


@pytest.mark.parametrize("mutation", ["version", "extra", "component", "workflow", "pattern"])
def test_invalid_manifest(manifest, tmp_path, mutation):
    invalid = copy.deepcopy(manifest)
    if mutation == "version":
        invalid["version"] = True
    elif mutation == "extra":
        invalid["extra"] = []
    elif mutation == "component":
        del invalid["components"]["android"]
    elif mutation == "workflow":
        invalid["components"]["android"]["workflow"] = "../android.yml"
    else:
        invalid["docs_only_paths"] = ["!docs/**"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(path)
    with pytest.raises(ValueError):
        selected([], invalid)


def test_manifest_preserves_legacy_workflow_filters(manifest):
    import yaml

    for component in manifest["components"].values():
        if component["workflow"] == "supply-chain.yml":
            assert component["paths"] == []
            continue
        workflow = yaml.load(
            (ROOT / ".github/workflows" / component["workflow"]).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        assert component["paths"] == workflow["on"]["pull_request"]["paths"]
        assert component["paths"] == workflow["on"]["push"]["paths"]
