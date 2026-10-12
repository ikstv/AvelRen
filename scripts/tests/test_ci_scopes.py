"""Незалежні приклади залежностей і безпечного вибору CI."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import ci_scopes
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
    # Незалежний snapshot однакових PR/push filters до reusable migration.
    expected = {
        "backend_core": [
            "services/backend/**",
            "scripts/verify_core_provenance.py",
            "docs/CORE-PROVENANCE.json",
            "docs/DB-PROVENANCE.json",
            "docs/API-PROVENANCE.json",
            "docs/WATCHDOG-PROVENANCE.json",
            "ops/telemetry-snapshot.sh",
            "db/**",
            ".gitattributes",
            ".github/workflows/backend-core.yml",
        ],
        "api": [
            "services/backend/**",
            "db/**",
            "ops/**",
            "scripts/test_database.sh",
            "scripts/verify_core_provenance.py",
            "docs/CORE-PROVENANCE.json",
            "docs/DB-PROVENANCE.json",
            "docs/API-PROVENANCE.json",
            "docs/WATCHDOG-PROVENANCE.json",
            ".gitattributes",
            ".github/workflows/api.yml",
        ],
        "database": [
            "db/**",
            "ops/**",
            "services/backend/**",
            "docker-compose.yml",
            ".env.example",
            ".gitignore",
            "scripts/test_database.sh",
            "scripts/verify_core_provenance.py",
            "docs/CORE-PROVENANCE.json",
            "docs/DB-PROVENANCE.json",
            "docs/API-PROVENANCE.json",
            "docs/WATCHDOG-PROVENANCE.json",
            ".gitattributes",
            ".github/workflows/database.yml",
        ],
        "watchdog": [
            "services/backend/**",
            "db/**",
            "ops/**",
            "scripts/test_database.sh",
            "scripts/verify_core_provenance.py",
            "docs/CORE-PROVENANCE.json",
            "docs/DB-PROVENANCE.json",
            "docs/API-PROVENANCE.json",
            "docs/WATCHDOG-PROVENANCE.json",
            ".gitattributes",
            ".github/workflows/watchdog.yml",
        ],
        "android": [
            "apps/android/**",
            "services/backend/src/avelren/api.py",
            "services/backend/src/avelren/schemas.py",
            "services/backend/src/avelren/subscriptions_api.py",
            "services/backend/src/avelren/admin_access_api.py",
            "services/backend/src/avelren/maintenance.py",
            "services/backend/src/avelren/surge*.py",
            "docs/ANDROID-PROVENANCE.json",
            "docs/ASSETS.md",
            "scripts/verify_android.py",
            "scripts/verify_push_qa.py",
            "scripts/verify_full_test.py",
            ".github/workflows/android.yml",
            ".gitattributes",
        ],
        "repository": [
            ".github/**",
            "docs/**",
            "scripts/**",
            "AGENTS.md",
            "CONTRIBUTING.md",
            "README.md",
        ],
        "monitor_contracts": [
            "scripts/classify_alert_channel.py",
            "scripts/tests/**",
            ".github/workflows/external-health-monitor.yml",
            ".github/workflows/external-monitor-checks.yml",
        ],
        "supply_chain": [
        ],
    }
    assert {key: item["paths"] for key, item in manifest["components"].items()} == expected


@pytest.mark.parametrize("event", [[], {}, None, 1])
def test_invalid_event_name_type(manifest, event):
    with pytest.raises(ValueError):
        selected([], manifest, event)


class GitRepo:
    """Disposable Git history; identity and configuration stay in this fixture."""

    def __init__(self, path):
        self.path = path
        path.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-b", "main")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.commit({"README.md": "initial"})

    def git(self, *args, input=None):
        return subprocess.run(
            ["git", *args], cwd=self.path, env=self.env, input=input,
            check=True, capture_output=True, shell=False,
        ).stdout.decode().strip()

    def commit(self, files):
        for name, content in files.items():
            path = self.path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                path.unlink()
            else:
                path.write_text(content, encoding="utf-8")
        self.git("add", "--all")
        self.git("commit", "--allow-empty", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def push(self, files):
        before = self.git("rev-parse", "HEAD")
        after = self.commit(files)
        return {"before": before, "after": after, "ref": "refs/heads/main"}, after

    def pr(self, commits, integration=None, target="main"):
        self.git("checkout", "-b", "feature")
        for files in commits:
            self.commit(files)
        head = self.git("rev-parse", "HEAD")
        self.git("checkout", "main")
        base = self.commit({"docs/base.md": "base advanced"})
        self.git("merge", "--no-ff", "--no-commit", "feature")
        if integration:
            self.commit(integration)
        else:
            self.git("commit", "-m", "merge fixture")
        tested = self.git("rev-parse", "HEAD")
        event = {"pull_request": {
            "base": {"sha": base, "ref": target}, "head": {"sha": head},
        }}
        return event, tested


@pytest.fixture
def repo(tmp_path):
    return GitRepo(tmp_path / "repo")


def collect(repo, event, tested, name="pull_request"):
    return ci_scopes.collect_changed_paths(
        repo.path, event_name=name, event=event, tested_sha=tested,
    )


def plan(repo, manifest, event, tested, name="pull_request"):
    return ci_scopes.build_plan(
        repo.path, manifest, event_name=name, event=event, tested_sha=tested,
    )


def test_pr_full_diff(repo, manifest):
    event, tested = repo.pr([
        {"apps/android/early.kt": "android"}, {"docs/last.md": "last"},
    ])
    paths, base, head, reason = collect(repo, event, tested)
    assert set(paths) == {"apps/android/early.kt", "docs/last.md"}
    assert (base, head, reason) == (
        event["pull_request"]["base"]["sha"], event["pull_request"]["head"]["sha"], "matched",
    )
    assert plan(repo, manifest, event, tested)["required"]["android"] is True


def test_merge_delta_union(repo, manifest):
    event, tested = repo.pr(
        [{"docs/head.md": "head"}], {"apps/android/integration.kt": "merge delta"},
    )
    assert set(collect(repo, event, tested)[0]) == {
        "docs/head.md", "apps/android/integration.kt",
    }
    assert plan(repo, manifest, event, tested)["required"]["android"] is True


def test_push_diff(repo, manifest):
    event, tested = repo.push({"apps/android/push.kt": "push"})
    assert collect(repo, event, tested, "push") == (
        ["apps/android/push.kt"], event["before"], tested, "matched",
    )
    assert plan(repo, manifest, event, tested, "push")["required"]["android"] is True


def test_force_updated_head(repo, manifest):
    old, old_tested = repo.pr([{ "apps/android/stale.kt": "old"}])
    base = old["pull_request"]["base"]["sha"]
    repo.git("checkout", "-B", "feature", base)
    new_head = repo.commit({"docs/current.md": "new"})
    repo.git("checkout", "-B", "main", base)
    repo.git("merge", "--no-ff", "-m", "new merge", "feature")
    new_tested = repo.git("rev-parse", "HEAD")
    current = copy.deepcopy(old)
    current["pull_request"]["head"]["sha"] = new_head
    assert collect(repo, current, new_tested)[0] == ["docs/current.md"]
    assert plan(repo, manifest, current, new_tested)["required"]["android"] is False
    with pytest.raises(ValueError):
        collect(repo, old, old_tested)


@pytest.mark.parametrize("old,new", [
    ("apps/android/old.kt", "docs/new.md"), ("docs/old.md", "apps/android/new.kt"),
])
def test_rename_both_sides(repo, manifest, old, new):
    repo.commit({old: "same content"})
    before = repo.git("rev-parse", "HEAD")
    (repo.path / new).parent.mkdir(parents=True, exist_ok=True)
    repo.git("mv", "--", old, new)
    tested = repo.commit({})
    event = {"before": before, "after": tested, "ref": "refs/heads/main"}
    assert set(collect(repo, event, tested, "push")[0]) == {old, new}
    assert plan(repo, manifest, event, tested, "push")["required"]["android"] is True


def test_delete(repo, manifest):
    repo.commit({"apps/android/deleted.kt": "gone"})
    event, tested = repo.push({"apps/android/deleted.kt": None})
    assert collect(repo, event, tested, "push")[0] == ["apps/android/deleted.kt"]
    assert plan(repo, manifest, event, tested, "push")["required"]["android"] is True


@pytest.mark.parametrize("name", ["space name", "Україна", "line\nbreak", "$(touch sentinel)"])
def test_nul_filenames(repo, manifest, name):
    filename = f"docs/{name}.md"
    event, tested = repo.push({filename: "literal"})
    assert collect(repo, event, tested, "push")[0] == [filename]
    result = plan(repo, manifest, event, tested, "push")
    if "\n" in name:
        assert all(result["required"].values())
        assert result["reason"] == "unknown_path"
    else:
        assert result["reason"] == "matched"
    assert not (repo.path / "sentinel").exists()


@pytest.mark.parametrize("count", [301, 3001])
def test_large_diff(repo, manifest, count):
    files = {f"docs/{i:04}.md": "docs" for i in range(count)}
    files["docs/ANDROID-PROVENANCE.json"] = "important"
    event, tested = repo.push(files)
    paths = collect(repo, event, tested, "push")[0]
    assert len(paths) == count + 1
    assert paths[-1] == "docs/ANDROID-PROVENANCE.json"
    assert plan(repo, manifest, event, tested, "push")["required"]["android"] is True


@pytest.mark.parametrize("mutation", [
    "tested", "unknown_tested", "uppercase", "head", "base", "one_parent", "reverse_parents",
    "third_parent", "missing_pr", "target", "event_type", "bad_sha", "zero_head",
])
def test_revision_identity(repo, mutation):
    event, tested = repo.pr([{ "docs/a.md": "head"}])
    pr = event["pull_request"]
    if mutation == "tested":
        tested = pr["head"]["sha"]
    elif mutation == "unknown_tested":
        tested = "f" * 40
    elif mutation == "uppercase":
        tested = tested.upper()
    elif mutation in {"head", "base"}:
        pr[mutation]["sha"] = "f" * 40
    elif mutation in {"one_parent", "reverse_parents", "third_parent"}:
        parents = [pr["base"]["sha"], pr["head"]["sha"]]
        if mutation == "one_parent":
            parents = parents[:1]
        elif mutation == "reverse_parents":
            parents.reverse()
        else:
            parents.append(repo.git("rev-parse", "HEAD~2"))
        args = ["commit-tree", "HEAD^{tree}"]
        for parent in parents:
            args += ["-p", parent]
        tested = repo.git(*args, input=b"invalid merge\n")
        repo.git("reset", "--hard", tested)
    elif mutation == "missing_pr":
        event = {}
    elif mutation == "target":
        pr["base"]["ref"] = []
    elif mutation == "event_type":
        event = []
    elif mutation == "bad_sha":
        pr["head"]["sha"] = "HEAD;touch sentinel"
    else:
        pr["head"]["sha"] = "0" * 40
    with pytest.raises(ValueError):
        collect(repo, event, tested)


@pytest.mark.parametrize("mutation", ["after", "ref", "missing", "sha", "zero_after"])
def test_push_identity(repo, mutation):
    event, tested = repo.push({"docs/a.md": "push"})
    if mutation == "after":
        event["after"] = event["before"]
    elif mutation == "ref":
        event["ref"] = "refs/heads/feature"
    elif mutation == "missing":
        del event["before"]
    elif mutation == "sha":
        event["before"] = "main"
    else:
        event["after"] = "0" * 40
    with pytest.raises(ValueError):
        collect(repo, event, tested, "push")


@pytest.mark.parametrize("event_name", ["workflow_dispatch", [], None])
def test_collector_invalid_event_name(repo, event_name):
    event, tested = repo.push({})
    with pytest.raises(ValueError):
        collect(repo, event, tested, event_name)


@pytest.mark.parametrize("before,reason", [
    ("0" * 40, "new_branch"), ("f" * 40, "history_unavailable"),
])
def test_push_fallback(repo, manifest, before, reason):
    event, tested = repo.push({})
    event["before"] = before
    expected_base = None if reason == "new_branch" else before
    assert collect(repo, event, tested, "push") == (None, expected_base, tested, reason)
    result = plan(repo, manifest, event, tested, "push")
    assert result["base_sha"] == expected_base
    assert result["complete"] is True
    assert result["reason"] == reason
    assert all(result["required"].values())


def test_missing_merge_base(repo, manifest):
    base = repo.git("rev-parse", "HEAD")
    repo.git("checkout", "--orphan", "unrelated")
    head = repo.commit({"docs/head.md": "head"})
    tested = repo.git("commit-tree", "HEAD^{tree}", "-p", base, "-p", head, input=b"merge\n")
    repo.git("reset", "--hard", tested)
    event = {"pull_request": {"base": {"sha": base, "ref": "release"}, "head": {"sha": head}}}
    assert collect(repo, event, tested)[3] == "history_unavailable"
    assert all(plan(repo, manifest, event, tested)["required"].values())


def test_missing_parent_history(repo, manifest):
    event, tested = repo.pr([{ "docs/head.md": "head"}])
    head = event["pull_request"]["head"]["sha"]
    (repo.path / ".git/objects" / head[:2] / head[2:]).unlink()
    assert collect(repo, event, tested)[3] == "history_unavailable"
    assert all(plan(repo, manifest, event, tested)["required"].values())


def test_diff_unavailable(repo, manifest):
    event, tested = repo.push({"docs/a.md": "push"})
    tree = repo.git("rev-parse", event["before"] + "^{tree}")
    (repo.path / ".git/objects" / tree[:2] / tree[2:]).unlink()
    assert collect(repo, event, tested, "push")[3] == "diff_unavailable"
    assert all(plan(repo, manifest, event, tested, "push")["required"].values())


def test_undecodable_filename(repo, manifest):
    filename = os.fsencode(repo.path) + b"/docs/invalid-\xff.md"
    (repo.path / "docs").mkdir()
    with open(filename, "wb") as stream:
        stream.write(b"literal")
    event, tested = repo.push({})
    result = plan(repo, manifest, event, tested, "push")
    assert result["reason"] == "unknown_path"
    assert all(result["required"].values())


def test_invalid_manifest_fatal_before_git(repo, manifest):
    event, tested = repo.push({})
    invalid = copy.deepcopy(manifest)
    invalid["version"] = True
    with pytest.raises(ValueError):
        plan(repo, invalid, event, tested, "push")


def test_empty_diff(repo, manifest):
    event, tested = repo.push({})
    assert collect(repo, event, tested, "push")[0] == []
    result = plan(repo, manifest, event, tested, "push")
    assert result["reason"] == "matched"
    assert {key for key, value in result["required"].items() if value} == {
        "repository", "supply_chain",
    }


def run_cli(repo, tmp_path, event, tested, event_name="push", raw_event=None):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        raw_event if raw_event is not None else json.dumps(event), encoding="utf-8",
    )
    output, summary, artifact = [tmp_path / name for name in ("output", "summary", "plan.json")]
    env = dict(repo.env, GITHUB_EVENT_NAME=event_name, GITHUB_EVENT_PATH=str(event_path),
               GITHUB_SHA=tested, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary))
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci_scopes.py"),
         "--manifest", str(ROOT / ".github/ci-scopes.json"), "--plan-file", str(artifact)],
        cwd=repo.path, env=env, capture_output=True, text=True, shell=False, check=False,
    )
    return result, output, summary, artifact


@pytest.mark.parametrize("filename,reason,required", [
    ("docs/Україна\nandroid=true.md", "unknown_path", {
        "backend_core": True, "api": True, "database": True, "watchdog": True,
        "android": True, "repository": True, "monitor_contracts": True, "supply_chain": True,
    }),
    ("docs/Україна.md", "matched", {
        "backend_core": False, "api": False, "database": False, "watchdog": False,
        "android": False, "repository": True, "monitor_contracts": False, "supply_chain": True,
    }),
])
def test_cli_outputs(repo, manifest, tmp_path, filename, reason, required):
    event, tested = repo.push({filename: "literal"})
    result, output, summary, artifact = run_cli(repo, tmp_path, event, tested)
    assert result.returncode == 0, result.stderr
    actual = json.loads(artifact.read_text())
    assert set(actual) == {
        "version", "complete", "reason", "event", "base_sha", "head_sha", "tested_sha", "required",
    }
    assert actual == plan(repo, manifest, event, tested, "push")
    assert actual == {
        "version": 1, "complete": True, "reason": reason, "event": "push",
        "base_sha": event["before"], "head_sha": tested, "tested_sha": tested,
        "required": required,
    }
    expected = json.dumps(actual, ensure_ascii=True, separators=(",", ":"))
    assert output.read_text().splitlines() == ["plan=" + expected] + [
        f"{name}={str(required[name]).lower()}" for name in COMPONENT_IDS
    ]
    assert filename not in (
        output.read_text() + summary.read_text() + artifact.read_text() + result.stdout
    )
    assert json.loads(result.stdout) == actual
    for value in (event["before"], tested, reason):
        assert value in summary.read_text()


@pytest.mark.parametrize("mutation", ["json", "event", "tested", "missing_env"])
def test_cli_fatal_without_outputs(repo, tmp_path, mutation):
    event, tested = repo.push({})
    name, raw = "push", None
    if mutation == "json":
        raw = "{invalid"
    elif mutation == "event":
        event["ref"] = "refs/heads/feature"
    elif mutation == "tested":
        tested = "f" * 40
    else:
        name = ""
    result, output, summary, artifact = run_cli(repo, tmp_path, event, tested, name, raw)
    assert result.returncode != 0
    assert not output.exists() and not summary.exists() and not artifact.exists()
    assert "Traceback" not in result.stderr
    assert not result.stdout


def test_cli_plan_write_failure_without_success_outputs(repo, tmp_path):
    event, tested = repo.push({})
    (tmp_path / "plan.json").mkdir()
    result, output, summary, _ = run_cli(repo, tmp_path, event, tested)
    assert result.returncode != 0
    assert not output.exists() and not summary.exists()
    assert "Traceback" not in result.stderr
    assert not result.stdout
