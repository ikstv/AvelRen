"""Незалежні сценарії строгого підсумку CI та його CLI."""

import copy
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

IDS = (
    "backend_core", "api", "database", "watchdog", "android", "repository",
    "monitor_contracts", "supply_chain",
)
ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
MISSING = object()


def evaluator(plan, needs):
    assert (ROOT / "scripts/verify_ci_gate.py").exists(), "Gate evaluator is not implemented"
    return importlib.import_module("scripts.verify_ci_gate").evaluate(plan, needs)


def fixture(*, all_required=False, event="pull_request"):
    plan = {
        "version": 1, "complete": True, "reason": "matched", "event": event,
        "base_sha": "b" * 40, "head_sha": "c" * 40, "tested_sha": SHA,
        "required": {key: all_required or key in {"repository", "supply_chain"} for key in IDS},
    }
    needs = {key: {"result": "success", "outputs": {}} for key in IDS}
    refresh_scope(plan, needs)
    return plan, needs


def refresh_scope(plan, needs):
    needs["scope"] = {
        "result": "success", "outputs": {
            "plan": json.dumps(plan),
            **{key: "true" if value else "false" for key, value in plan["required"].items()},
        },
    }


@pytest.mark.parametrize("event", ["pull_request", "push"])
@pytest.mark.parametrize("result", ["success", "skipped"])
def test_success(event, result):
    plan, needs = fixture(event=event)
    for key in ("backend_core", "api", "database", "watchdog", "android", "monitor_contracts"):
        needs[key]["result"] = result
    assert evaluator(plan, needs) == []


@pytest.mark.parametrize("key", IDS)
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("result", [
    "success", "failure", "cancelled", "skipped", "neutral", "timed_out", "", None,
    MISSING, True, 1, [], {},
])
def test_status_matrix(key, required, result):
    plan, needs = fixture(all_required=required)
    plan["required"][key] = required
    # Repository/SBOM policy is also mandatory; those invalid plans must fail.
    refresh_scope(plan, needs)
    if result is MISSING:
        del needs[key]["result"]
    else:
        needs[key]["result"] = result
    expected_pass = (
        (required or key != "repository")
        and (result == "success" or (not required and result == "skipped"))
    )
    assert (evaluator(plan, needs) == []) is expected_pass


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "neutral", None, [], {}])
def test_scope_must_succeed(result):
    plan, needs = fixture()
    needs["scope"]["result"] = result
    assert evaluator(plan, needs)


@pytest.mark.parametrize("field,value", [
    ("version", True), ("version", 2), ("version", "1"), ("complete", False),
    ("complete", 1), ("reason", "unknown"), ("reason", []), ("event", "workflow_dispatch"),
    ("event", {}), ("base_sha", None), ("base_sha", "0" * 40),
    ("head_sha", "A" * 40), ("head_sha", "0" * 40), ("tested_sha", ""),
    ("tested_sha", "0" * 40), ("tested_sha", []),
])
def test_invalid_plan_field(field, value):
    plan, needs = fixture()
    plan[field] = value
    refresh_scope(plan, needs)
    assert evaluator(plan, needs)


@pytest.mark.parametrize("reason", [
    "matched", "control_change", "unknown_path", "history_unavailable", "diff_unavailable",
])
def test_known_reasons(reason):
    plan, needs = fixture(all_required=True)
    plan["reason"] = reason
    refresh_scope(plan, needs)
    assert evaluator(plan, needs) == []


@pytest.mark.parametrize("reason", [
    "control_change", "unknown_path", "new_branch", "history_unavailable", "diff_unavailable",
])
@pytest.mark.parametrize("omitted", IDS)
def test_fallback_reason_requires_every_component(reason, omitted):
    event = "push" if reason == "new_branch" else "pull_request"
    plan, needs = fixture(all_required=True, event=event)
    plan["reason"] = reason
    if reason == "new_branch":
        plan["base_sha"] = None
    plan["required"][omitted] = False
    needs[omitted]["result"] = "skipped"
    refresh_scope(plan, needs)
    assert evaluator(plan, needs)


def test_new_branch_nullable_base_only_on_push():
    plan, needs = fixture(all_required=True, event="push")
    plan.update(reason="new_branch", base_sha=None)
    refresh_scope(plan, needs)
    assert evaluator(plan, needs) == []
    plan["event"] = "pull_request"
    refresh_scope(plan, needs)
    assert evaluator(plan, needs)


def test_non_main_pr_can_omit_supply_chain():
    plan, needs = fixture()
    plan["required"]["supply_chain"] = False
    needs["supply_chain"]["result"] = "skipped"
    refresh_scope(plan, needs)
    assert evaluator(plan, needs) == []
    plan["event"] = "push"
    refresh_scope(plan, needs)
    assert evaluator(plan, needs)


@pytest.mark.parametrize("key", IDS)
@pytest.mark.parametrize("value", ["false", 0, 1, None, [], {}])
def test_required_flags_are_exact_booleans(key, value):
    plan, needs = fixture()
    plan["required"][key] = value
    refresh_scope(plan, needs)
    assert evaluator(plan, needs)


@pytest.mark.parametrize("location", ["plan", "required", "needs", "scope", "outputs", "job"])
@pytest.mark.parametrize("operation", ["missing", "extra", "non_object"])
def test_bad_output(location, operation):
    plan, needs = fixture()
    objects = {
        "plan": plan, "required": plan["required"], "needs": needs,
        "scope": needs["scope"], "outputs": needs["scope"]["outputs"], "job": needs["api"],
    }
    obj = objects[location]
    if operation == "missing":
        del obj[next(iter(obj))]
    elif operation == "extra":
        obj["unexpected"] = True
    else:
        if location == "plan":
            plan = []
        elif location == "required":
            plan["required"] = []
        elif location == "needs":
            needs = []
        elif location == "scope":
            needs["scope"] = []
        elif location == "outputs":
            needs["scope"]["outputs"] = []
        else:
            needs["api"] = []
    assert evaluator(plan, needs)


@pytest.mark.parametrize("value", [None, "", "{", "[]", "null", "true"])
def test_bad_scope_plan(value):
    plan, needs = fixture()
    needs["scope"]["outputs"]["plan"] = value
    assert evaluator(plan, needs)


def test_scope_plan_and_boolean_outputs_must_match():
    plan, needs = fixture()
    other = copy.deepcopy(plan)
    other["tested_sha"] = "d" * 40
    needs["scope"]["outputs"]["plan"] = json.dumps(other)
    assert evaluator(plan, needs)
    refresh_scope(plan, needs)
    needs["scope"]["outputs"]["api"] = "true"
    assert evaluator(plan, needs)


@pytest.mark.parametrize("key", IDS)
@pytest.mark.parametrize("location", ["required", "needs", "outputs"])
def test_every_component_is_mandatory_in_each_map(key, location):
    plan, needs = fixture()
    target = {
        "required": plan["required"], "needs": needs, "outputs": needs["scope"]["outputs"],
    }[location]
    del target[key]
    assert evaluator(plan, needs)


@pytest.mark.parametrize("field,value", [("version", True), ("complete", 1)])
def test_scope_plan_types_cannot_hide_behind_python_equality(field, value):
    plan, needs = fixture()
    scope_plan = copy.deepcopy(plan)
    scope_plan[field] = value
    needs["scope"]["outputs"]["plan"] = json.dumps(scope_plan)
    assert evaluator(plan, needs)


@pytest.mark.parametrize("key", IDS)
@pytest.mark.parametrize("value", [True, False, "True", "False", "1", "", None])
def test_scope_outputs_are_boolean_strings(key, value):
    plan, needs = fixture()
    needs["scope"]["outputs"][key] = value
    assert evaluator(plan, needs)


@pytest.mark.parametrize("value", [None, True, 1, "", [], {}])
def test_malformed_top_level(value):
    plan, needs = fixture()
    assert evaluator(value, needs)
    assert evaluator(plan, value)


def cli(env):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_ci_gate.py")],
        env=env, capture_output=True, text=True, check=False,
    )


def cli_env():
    plan, needs = fixture()
    return {
        **os.environ, "CI_PLAN_JSON": json.dumps(plan),
        "CI_NEEDS_JSON": json.dumps(needs), "GITHUB_SHA": SHA,
    }


def test_cli_success():
    result = cli(cli_env())
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("key", ["CI_PLAN_JSON", "CI_NEEDS_JSON", "GITHUB_SHA"])
@pytest.mark.parametrize("value", [MISSING, "", "{", "null", "[]"])
def test_cli_bad_env(key, value):
    env = cli_env()
    if value is MISSING:
        del env[key]
    else:
        env[key] = value
    result = cli(env)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_stale_tested_sha():
    env = cli_env()
    env["GITHUB_SHA"] = "d" * 40
    result = cli(env)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("reason", [
    "control_change", "unknown_path", "new_branch", "history_unavailable", "diff_unavailable",
])
def test_cli_rejects_partial_fallback(reason):
    event = "push" if reason == "new_branch" else "pull_request"
    plan, needs = fixture(all_required=True, event=event)
    plan["reason"] = reason
    if reason == "new_branch":
        plan["base_sha"] = None
    plan["required"]["api"] = False
    needs["api"]["result"] = "skipped"
    refresh_scope(plan, needs)
    env = {
        **os.environ, "CI_PLAN_JSON": json.dumps(plan),
        "CI_NEEDS_JSON": json.dumps(needs), "GITHUB_SHA": SHA,
    }
    result = cli(env)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", MISSING])
def test_cli_fatal_result_is_nonzero(result):
    env = cli_env()
    needs = json.loads(env["CI_NEEDS_JSON"])
    if result is MISSING:
        del needs["repository"]
    else:
        needs["repository"]["result"] = result
    env["CI_NEEDS_JSON"] = json.dumps(needs)
    completed = cli(env)
    assert completed.returncode == 1
    assert "Traceback" not in completed.stderr
