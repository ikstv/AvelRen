"""Копія Linux lock для unit-тестів Windows; вихідний lock не змінюється."""

import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = root / "services/backend/requirements.lock"
lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
matches = 0
for index, line in enumerate(lines):
    if line.startswith("uvloop=="):
        version, continuation = line.split(" ", 1)
        lines[index] = f'{version} ; sys_platform != "win32" {continuation}'
        matches += 1
if matches != 1 or args.output.resolve() == source.resolve():
    raise SystemExit("Expected one uvloop entry and a separate output file")
args.output.write_text("".join(lines), encoding="utf-8")
