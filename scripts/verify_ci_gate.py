"""Строгий підсумок CI з плану scope та результатів фіксованих jobs."""

import json
import os
import re
import sys
from collections.abc import Sequence

COMPONENT_IDS = (
    "backend_core", "api", "database", "watchdog", "android", "repository",
    "monitor_contracts", "supply_chain",
)
PLAN_KEYS = {
    "version", "complete", "reason", "event", "base_sha", "head_sha", "tested_sha", "required",
}
REASONS = {
    "matched", "control_change", "unknown_path", "new_branch",
    "history_unavailable", "diff_unavailable",
}


def _sha(value: object) -> bool:
    return (
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None
        and value != "0" * 40
    )


def _plan_errors(plan: object) -> list[str]:
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS:
        return ["Plan must be an object with exactly the approved keys"]
    errors = []
    if type(plan["version"]) is not int or plan["version"] != 1:
        errors.append("Plan version must be integer 1")
    if type(plan["complete"]) is not bool or plan["complete"] is not True:
        errors.append("Plan must be complete")
    reason = plan["reason"]
    event = plan["event"]
    if not isinstance(reason, str) or reason not in REASONS:
        errors.append("Unknown plan reason")
    if not isinstance(event, str) or event not in {"pull_request", "push"}:
        errors.append("Unknown plan event")
    nullable_base = event == "push" and reason == "new_branch"
    if not _sha(plan["base_sha"]) and not (nullable_base and plan["base_sha"] is None):
        errors.append("Invalid base SHA")
    if reason == "new_branch" and event != "push":
        errors.append("New branch is only valid for push")
    for field in ("head_sha", "tested_sha"):
        if not _sha(plan[field]):
            errors.append(f"Invalid {field}")
    required = plan["required"]
    if not isinstance(required, dict) or set(required) != set(COMPONENT_IDS):
        errors.append("Required must contain exactly the eight component IDs")
    elif any(type(value) is not bool for value in required.values()):
        errors.append("Required flags must be booleans")
    else:
        if not required["repository"]:
            errors.append("Repository is always required")
        if event == "push" and not required["supply_chain"]:
            errors.append("Supply chain is required for push")
    return errors


def evaluate(plan: object, needs: object) -> list[str]:
    """Повернути всі знайдені помилки; порожній список означає успіх."""
    errors = _plan_errors(plan)
    valid_plan = not errors
    if not isinstance(needs, dict) or set(needs) != {"scope", *COMPONENT_IDS}:
        return errors + ["Needs must contain scope and exactly the eight component IDs"]
    for key in ("scope", *COMPONENT_IDS):
        job = needs[key]
        if not isinstance(job, dict) or set(job) != {"result", "outputs"}:
            errors.append(f"{key}: expected result and outputs")
            continue
        if not isinstance(job["outputs"], dict):
            errors.append(f"{key}: outputs must be an object")
        result = job["result"]
        if key == "scope":
            if result != "success":
                errors.append("Scope must succeed")
        elif valid_plan:
            allowed = ("success",) if plan["required"][key] else ("success", "skipped")
            if not isinstance(result, str) or result not in allowed:
                errors.append(f"{key}: unacceptable result")

    scope = needs["scope"]
    if not isinstance(scope, dict) or not isinstance(scope.get("outputs"), dict):
        return errors
    outputs = scope["outputs"]
    if set(outputs) != {"plan", *COMPONENT_IDS}:
        return errors + ["Scope outputs must contain plan and exactly eight flags"]
    raw_plan = outputs["plan"]
    if not isinstance(raw_plan, str):
        return errors + ["Scope plan output must be JSON text"]
    try:
        scope_plan = json.loads(raw_plan)
    except (ValueError, RecursionError):
        return errors + ["Scope plan output is invalid JSON"]
    if _plan_errors(scope_plan) or scope_plan != plan:
        errors.append("Scope plan output differs from the valid input plan")
    if valid_plan:
        for key in COMPONENT_IDS:
            expected = "true" if plan["required"][key] else "false"
            if type(outputs[key]) is not str or outputs[key] != expected:
                errors.append(f"{key}: scope flag differs from required plan flag")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    """Читати лише погоджені env inputs; кожна помилка завершується exit 1."""
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        print("CI gate: no command-line arguments are accepted", file=sys.stderr)
        return 1
    values = {key: os.environ.get(key) for key in ("CI_PLAN_JSON", "CI_NEEDS_JSON", "GITHUB_SHA")}
    if any(not value for value in values.values()):
        print("CI gate: missing required environment input", file=sys.stderr)
        return 1
    try:
        plan = json.loads(values["CI_PLAN_JSON"])
        needs = json.loads(values["CI_NEEDS_JSON"])
    except (ValueError, RecursionError):
        print("CI gate: malformed JSON input", file=sys.stderr)
        return 1
    errors = evaluate(plan, needs)
    github_sha = values["GITHUB_SHA"]
    if not _sha(github_sha):
        errors.append("GITHUB_SHA must be a real lowercase SHA")
    elif not isinstance(plan, dict) or plan.get("tested_sha") != github_sha:
        errors.append("Plan tested_sha must equal GITHUB_SHA")
    if errors:
        for error in errors:
            print(f"CI gate: {error}", file=sys.stderr)
        return 1
    print("CI gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
