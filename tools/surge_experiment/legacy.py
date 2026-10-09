"""Переносимий запуск архівного evaluator без зміни його обчислень."""
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .data import local_path

ARCHIVE = Path(__file__).resolve().parents[2] / "docs/research/queue-surge-2026-10-02/surge-frozen-evaluate.py"
ARCHIVE_SHA256 = "52a39d21e40c1f0aba7e991db6ef5bbd213c96839fa6609ab31d65b2b3e84b34"
OLD_ROOT = "C:/AI/AvelRen/dist"


def adapt_legacy_source(source: str, data_dir: Path) -> str:
    canonical = source.replace("\r\n", "\n")
    if hashlib.sha256(canonical.encode()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("legacy archive checksum mismatch")
    tree = ast.parse(canonical)
    found = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == OLD_ROOT]
    if len(found) != 1:
        raise ValueError("legacy root literal mismatch")
    found[0].value = str(local_path(data_dir))
    return ast.unparse(tree)


def run_legacy(data_dir: Path, start: datetime, end: datetime, output: Path) -> dict:
    output = local_path(output)
    if output.exists():
        raise ValueError("legacy output already exists")
    if not start < end or start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("aware ordered legacy dates required")
    source = adapt_legacy_source(ARCHIVE.read_text(encoding="utf-8"), data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="surge-legacy-", dir=output.parent) as temporary:
        runner = Path(temporary) / "runner.py"
        runner.write_text(source, encoding="utf-8")
        result = subprocess.run([sys.executable, str(runner), "--start", start.isoformat(), "--end", end.isoformat(),
                                 "--output", str(output)], capture_output=True, text=True, timeout=300, check=False)
        if result.returncode:
            raise ValueError("legacy evaluation failed; no metrics accepted")
    return json.loads(output.read_text(encoding="utf-8"))
