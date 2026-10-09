"""Архівному runner дозволено змінити лише літерал локального data-root."""
import ast
from pathlib import Path

import pytest

ARCHIVE = Path(__file__).resolve().parents[2] / "docs/research/queue-surge-2026-10-02/surge-frozen-evaluate.py"


def test_legacy_adapter_changes_only_root_literal(tmp_path):
    from tools.surge_experiment.legacy import adapt_legacy_source
    source = ARCHIVE.read_text(encoding="utf-8")
    adapted = adapt_legacy_source(source, tmp_path)
    tree = ast.parse(adapted)
    replacements = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == str(tmp_path.resolve()):
            node.value = "C:/AI/AvelRen/dist"
            replacements += 1
    assert replacements == 1
    assert ast.dump(tree) == ast.dump(ast.parse(source))


def test_legacy_adapter_rejects_modified_archive(tmp_path):
    from tools.surge_experiment.legacy import adapt_legacy_source
    source = ARCHIVE.read_text(encoding="utf-8").replace("correct+=1", "correct+=2")
    with pytest.raises(ValueError, match="checksum"):
        adapt_legacy_source(source, tmp_path)
