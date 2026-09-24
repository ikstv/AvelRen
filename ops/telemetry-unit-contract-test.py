#!/usr/bin/env python3
"""Static contract for the host telemetry systemd units."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_unit(path: Path) -> dict[str, dict[str, list[str]]]:
    sections: dict[str, dict[str, list[str]]] = {}
    current = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            raise AssertionError(f"invalid unit line in {path}: {raw_line!r}")
        key, value = line.split("=", 1)
        sections[current].setdefault(key, []).append(value)
    return sections


def exactly(section: dict[str, list[str]], key: str, expected: str) -> None:
    actual = section.get(key)
    assert actual == [expected], f"{key}: expected {[expected]!r}, got {actual!r}"


service = read_unit(ROOT / "ops/avelren-telemetry.service")
timer = read_unit(ROOT / "ops/avelren-telemetry.timer")

unit = service["Unit"]
exactly(unit, "Documentation", "file:///opt/avelren/ops/telemetry-snapshot.sh")
exactly(unit, "After", "docker.service")
exactly(unit, "Wants", "docker.service")

runtime = service["Service"]
exactly(runtime, "Type", "oneshot")
exactly(runtime, "ExecStart", "/usr/local/sbin/avelren-telemetry-snapshot")
for key in ("NoNewPrivileges", "PrivateTmp", "ProtectSystem", "ProtectHome", "LockPersonality"):
    assert key in runtime, f"service hardening directive missing: {key}"
exactly(runtime, "NoNewPrivileges", "true")
exactly(runtime, "PrivateTmp", "true")
exactly(runtime, "ProtectSystem", "strict")
exactly(runtime, "ProtectHome", "true")
exactly(runtime, "ReadWritePaths", "/var/lib/avelren-telemetry")
exactly(runtime, "ReadOnlyPaths", "/proc /run")
exactly(runtime, "RestrictAddressFamilies", "AF_UNIX AF_INET AF_INET6")
exactly(runtime, "LockPersonality", "true")

timer_unit = timer["Unit"]
exactly(timer_unit, "Documentation", "file:///opt/avelren/ops/telemetry-snapshot.sh")
schedule = timer["Timer"]
exactly(schedule, "OnBootSec", "30s")
exactly(schedule, "OnUnitActiveSec", "1min")
exactly(schedule, "AccuracySec", "5s")
exactly(schedule, "Persistent", "true")
exactly(timer["Install"], "WantedBy", "timers.target")

print("telemetry systemd unit contract ok")
