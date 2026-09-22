"""Регресійні приклади поділу CI; перевіряємо YAML, не запускаємо збірки."""

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
print(f"CI scopes: {len(cases) * 2} examples passed")
