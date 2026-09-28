"""Перевірка фактичних Linux-обмежень усередині тестового контейнера."""
from pathlib import Path

status = dict(
    line.split(":", 1)
    for line in Path("/proc/self/status").read_text().splitlines()
    if ":" in line
)
assert status["NoNewPrivs"].strip() == "1", "no-new-privileges is not active"
for field in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
    assert int(status[field], 16) == 0, f"{field} is not empty"
print("Python container security: NoNewPrivs=1, all capability sets empty")
