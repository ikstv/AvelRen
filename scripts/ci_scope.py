"""Conservative component routing. Unknown/shared paths run both suites."""

import re
import subprocess
import sys


def classify(paths: list[str]) -> tuple[bool, bool]:
    backend = android = False
    for path in paths:
        if path.startswith("android/"):
            android = True
        elif path.startswith(("app/", "db/", "deploy/")):
            backend = True
        elif path.startswith("docs/") or path in {"README.md", "CONTRIBUTING.md"}:
            continue
        else:
            backend = android = True
    return backend, android


def main(base: str, head: str) -> None:
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        raise SystemExit("Expected full Git commit hashes")
    command = (
        ["git", "ls-files", "-z"] if base == "0" * 40
        else ["git", "diff", "--name-only", "--no-renames", "-z", base, head, "--"]
    )
    paths = subprocess.check_output(command).decode("utf-8").rstrip("\0").split("\0")
    backend, android = classify([path for path in paths if path])
    print(f"backend={str(backend).lower()}")
    print(f"android={str(android).lower()}")


if __name__ == "__main__":
    main(*sys.argv[1:])
