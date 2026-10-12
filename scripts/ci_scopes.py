"""Чистий вибір компонентів CI: positive glob із сегментами * та **.

* не перетинає slash; окремий сегмент ** означає нуль або більше сегментів.
Невідомі шляхи запускають усі компоненти, навіть для PR не до main.
"""

import json
import re
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
    if event_name not in {"pull_request", "push"}:
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
