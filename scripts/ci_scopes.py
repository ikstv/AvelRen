"""Чистий вибір компонентів CI: positive glob із сегментами * та **.

* не перетинає slash; окремий сегмент ** означає нуль або більше сегментів.
Невідомі шляхи запускають усі компоненти, навіть для PR не до main.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path

COMPONENT_IDS = (
    "backend_core", "api", "database", "watchdog", "android", "repository",
    "monitor_contracts", "supply_chain",
)
_WORKFLOWS = dict(zip(COMPONENT_IDS, (
    "backend-core.yml", "api.yml", "database.yml", "watchdog.yml", "android.yml",
    "repository.yml", "external-monitor-checks.yml", "supply-chain.yml",
), strict=True))


def _segments(value: str, *, pattern: bool) -> list[str]:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ValueError("Expected a nonempty repository-relative path")
    if any(char in value for char in "\\:!?[]{}") or any(ord(char) < 32 for char in value):
        raise ValueError("Unsupported path syntax")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid path segment")
    if any("**" in part and part != "**" for part in parts):
        raise ValueError("** must occupy a whole segment")
    if not pattern and "*" in value:
        raise ValueError("Changed paths must be literal")
    return parts


def match_path(path: str, pattern: str) -> bool:
    """Зіставити literal шлях із підтримуваним positive glob."""
    parts = _segments(path, pattern=False)
    patterns = _segments(pattern, pattern=True)

    @cache
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(patterns):
            return path_index == len(parts)
        segment = patterns[pattern_index]
        if segment == "**":
            return match(path_index, pattern_index + 1) or (
                path_index < len(parts) and match(path_index + 1, pattern_index)
            )
        expression = re.escape(segment).replace(r"\*", ".*")
        return (
            path_index < len(parts)
            and re.fullmatch(expression, parts[path_index]) is not None
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def _validate_manifest(manifest: Mapping) -> None:
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "version", "components", "all_components_paths", "docs_only_paths"
    }:
        raise ValueError("Invalid manifest keys")
    if type(manifest["version"]) is not int or manifest["version"] != 1:
        raise ValueError("Unsupported manifest version")
    components = manifest["components"]
    if not isinstance(components, Mapping) or set(components) != set(COMPONENT_IDS):
        raise ValueError("Invalid component IDs")
    lists = [manifest["all_components_paths"], manifest["docs_only_paths"]]
    for name, component in components.items():
        if not isinstance(component, Mapping) or set(component) != {"workflow", "paths"}:
            raise ValueError("Invalid component schema")
        if component["workflow"] != _WORKFLOWS[name]:
            raise ValueError("Invalid component workflow")
        lists.append(component["paths"])
    if components["supply_chain"]["paths"] != []:
        raise ValueError("Supply chain must use event selection")
    for patterns in lists:
        if not isinstance(patterns, list):
            raise ValueError("Patterns must be lists")
        for pattern in patterns:
            _segments(pattern, pattern=True)


def load_manifest(path: Path) -> dict:
    """Прочитати та суворо перевірити versioned JSON manifest."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Cannot read CI manifest") from error
    _validate_manifest(manifest)
    return manifest


def classify_paths(
    paths: Sequence[str], manifest: Mapping, *, event_name: str, target_branch: str
) -> tuple[dict[str, bool], str]:
    """Обрати залежні компоненти або консервативно запустити всі."""
    _validate_manifest(manifest)
    if not isinstance(event_name, str) or event_name not in {"pull_request", "push"}:
        raise ValueError("Unsupported CI event")
    if not isinstance(target_branch, str) or not target_branch.strip():
        raise ValueError("Missing target branch")
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
        raise ValueError("Changed paths must be a sequence")
    for path in paths:
        _segments(path, pattern=False)

    def matches(path: str, patterns: list[str]) -> bool:
        return any(match_path(path, pattern) for pattern in patterns)

    all_required = dict.fromkeys(COMPONENT_IDS, True)
    if any(matches(path, manifest["all_components_paths"]) for path in paths):
        return all_required, "control_change"
    required = dict.fromkeys(COMPONENT_IDS, False)
    required["repository"] = True
    required["supply_chain"] = target_branch == "main"
    for path in paths:
        matched = False
        for name in COMPONENT_IDS:
            if name in {"repository", "supply_chain"}:
                continue
            if matches(path, manifest["components"][name]["paths"]):
                required[name] = True
                matched = True
        if not matched and not matches(path, manifest["docs_only_paths"]):
            return all_required, "unknown_path"
    return required, "matched"


_ZERO_SHA = "0" * 40


def _sha(value: object, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("Expected a full lowercase commit SHA")
    if not allow_zero and value == _ZERO_SHA:
        raise ValueError("Expected a nonzero commit SHA")
    return value


def _event_details(event_name: str, event: Mapping) -> tuple[str, str, str]:
    if not isinstance(event_name, str) or event_name not in {"pull_request", "push"}:
        raise ValueError("Unsupported CI event")
    if not isinstance(event, Mapping):
        raise ValueError("Expected an event object")
    if event_name == "push":
        if event.get("ref") != "refs/heads/main":
            raise ValueError("Only main push events are supported")
        return _sha(event.get("before"), allow_zero=True), _sha(event.get("after")), "main"
    pr = event.get("pull_request")
    if not isinstance(pr, Mapping):
        raise ValueError("Missing pull request")
    base, head = pr.get("base"), pr.get("head")
    if not isinstance(base, Mapping) or not isinstance(head, Mapping):
        raise ValueError("Missing pull request revisions")
    target = base.get("ref")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("Missing target branch")
    return _sha(base.get("sha")), _sha(head.get("sha")), target


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-pager", *args], cwd=repo, check=True, capture_output=True,
        shell=False, env=dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1"),
    ).stdout


def _check_head(repo: Path, tested_sha: str) -> None:
    try:
        if _git(repo, "rev-parse", "--verify", "HEAD").strip() != tested_sha.encode("ascii"):
            raise ValueError("Checkout HEAD differs from tested SHA")
        if _git(repo, "cat-file", "-t", tested_sha).strip() != b"commit":
            raise ValueError("Tested revision must be a commit")
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("Cannot verify tested revision") from error


def collect_changed_paths(
    repo: Path, *, event_name: str, event: Mapping, tested_sha: str,
) -> tuple[list[str] | None, str | None, str, str]:
    """Повний NUL diff лише локальної історії; неповна історія запускає всі CI."""
    tested_sha = _sha(tested_sha)
    base_sha, head_sha, _ = _event_details(event_name, event)
    if event_name == "push" and head_sha != tested_sha:
        raise ValueError("Push after differs from tested SHA")
    _check_head(repo, tested_sha)
    if event_name == "pull_request":
        try:
            headers = _git(repo, "cat-file", "-p", tested_sha).split(b"\n\n", 1)[0]
        except (OSError, subprocess.CalledProcessError) as error:
            raise ValueError("Cannot verify tested merge parents") from error
        parents = [line[7:] for line in headers.splitlines() if line.startswith(b"parent ")]
        if parents != [base_sha.encode("ascii"), head_sha.encode("ascii")]:
            raise ValueError("Tested merge parents differ from event base/head")
    if base_sha == _ZERO_SHA:
        return None, None, head_sha, "new_branch"

    try:
        for revision in (base_sha, head_sha):
            if _git(repo, "cat-file", "-t", revision).strip() != b"commit":
                return None, base_sha, head_sha, "history_unavailable"
        if _git(repo, "rev-parse", "--is-shallow-repository").strip() == b"true":
            return None, base_sha, head_sha, "history_unavailable"
        if event_name == "pull_request":
            merge_base = _sha(_git(repo, "merge-base", base_sha, head_sha).decode("ascii").strip())
            comparisons = [(merge_base, head_sha), (base_sha, tested_sha)]
        else:
            comparisons = [(base_sha, tested_sha)]
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError):
        return None, base_sha, head_sha, "history_unavailable"

    paths = set()
    try:
        for old, new in comparisons:
            output = _git(
                repo, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z",
                "--no-renames", old, new, "--",
            )
            if output and not output.endswith(b"\0"):
                return None, base_sha, head_sha, "diff_unavailable"
            paths.update(path.decode("utf-8") for path in output.split(b"\0")[:-1])
    except UnicodeError:
        return None, base_sha, head_sha, "unknown_path"
    except (OSError, subprocess.CalledProcessError):
        return None, base_sha, head_sha, "diff_unavailable"
    _check_head(repo, tested_sha)
    return sorted(paths), base_sha, head_sha, "matched"


def build_plan(
    repo: Path, manifest: Mapping, *, event_name: str, event: Mapping, tested_sha: str,
) -> dict:
    """Побудувати versioned план без сирих filenames у вихідному контракті."""
    _validate_manifest(manifest)
    _, _, target_branch = _event_details(event_name, event)
    paths, base_sha, head_sha, reason = collect_changed_paths(
        repo, event_name=event_name, event=event, tested_sha=tested_sha,
    )
    if paths is None:
        required = dict.fromkeys(COMPONENT_IDS, True)
    else:
        try:
            required, reason = classify_paths(
                paths, manifest, event_name=event_name, target_branch=target_branch,
            )
        except ValueError:
            required, reason = dict.fromkeys(COMPONENT_IDS, True), "unknown_path"
    return {
        "version": 1, "complete": True, "reason": reason, "event": event_name,
        "base_sha": base_sha, "head_sha": head_sha, "tested_sha": tested_sha,
        "required": required,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Вибір компонентів CI за повним Git diff")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        event_path = os.environ.get("GITHUB_EVENT_PATH", "")
        if not event_path:
            raise ValueError("Missing event path")
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        plan = build_plan(
            Path.cwd(), load_manifest(args.manifest), event_name=event_name,
            event=event, tested_sha=os.environ.get("GITHUB_SHA", ""),
        )
        serialized = json.dumps(plan, ensure_ascii=True, separators=(",", ":"))
        args.plan_file.write_text(serialized + "\n", encoding="utf-8")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as summary:
                summary.write(
                    "CI scopes\n\n"
                    f"Base: `{plan['base_sha']}`\n\nHead: `{plan['head_sha']}`\n\n"
                    f"Tested: `{plan['tested_sha']}`\n\nReason: `{plan['reason']}`\n\n"
                )
        output_path = os.environ.get("GITHUB_OUTPUT")
        if output_path:
            with Path(output_path).open("a", encoding="utf-8") as output:
                output.write("plan=" + serialized + "\n")
                for component in COMPONENT_IDS:
                    output.write(f"{component}={str(plan['required'][component]).lower()}\n")
        print(serialized)
    except (ValueError, OSError, UnicodeError) as error:
        print(f"CI scopes failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
