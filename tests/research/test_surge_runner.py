"""Runner зберігає manifest та межі сітки, cache не змінює replay."""
import json
from pathlib import Path

from tests.research.test_surge_replay import FixedCandidate, manifest, observations
from tools.surge_experiment.contracts import Dataset


def test_cached_replay_same_decisions_and_alerts():
    from tools.surge_experiment.replay import ReplayCache, replay
    data = Dataset({17: observations()}, {})
    cache = ReplayCache(data)
    uncached = replay(data, FixedCandidate(), manifest(minutes=65), 0)
    cached = replay(data, FixedCandidate(), manifest(minutes=65), 0, cache=cache)
    assert uncached == cached
    assert replay(data, FixedCandidate(), manifest(minutes=65), 0, cache=cache) == cached


def test_fit_command_writes_all_fixed_artifacts(tmp_path, input_archive):
    from tools.surge_experiment.__main__ import main
    from tools.surge_experiment.manifest import protocol_v1
    path, hashes = input_archive([[17, "2026-09-01T00:00:00+03:00", 5, False]])
    config = {"version": "shared-surge-v1", "queue_ids": [17], "code_commit": "a" * 40,
              "inputs": [{"path": str(path), "sha256": hashes[path.name]}], "protocol": protocol_v1()}
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(config), encoding="utf-8")
    out = tmp_path / "fit"
    assert main(["fit", "--manifest", str(source), "--output", str(out)]) == 0
    artifact = json.loads((out / "fit.json").read_text(encoding="utf-8"))
    assert len(artifact["artifacts"]) == 9
    assert artifact["manifest"] == config
    assert all(a["status"] != "ready" for a in artifact["artifacts"] if a["candidate_id"] != "frozen")


def test_compare_rejects_changed_fit_manifest(tmp_path):
    from tools.surge_experiment.runner import read_fit
    path = tmp_path / "fit.json"
    path.write_text(json.dumps({"manifest": {"changed": True}, "artifacts": []}), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="manifest"):
        read_fit(Path(path), {"changed": False})


def test_compare_single_class_has_explicit_missing_rows(tmp_path):
    from tools.surge_experiment.contracts import ObservationRow
    from tools.surge_experiment.data import timestamp
    from tools.surge_experiment.manifest import Manifest, protocol_v1
    from tools.surge_experiment.runner import compare, fit_dataset
    config = protocol_v1()
    config["replay"]["start"] = "2026-09-24T23:55:00+03:00"
    config["periods"]["development_end"] = "2026-09-25T00:05:00+03:00"
    m = Manifest(tuple(range(1,39)), (), "a" * 40, json.dumps(config))
    data = Dataset({17: [ObservationRow(17, timestamp("2026-09-01T00:00:00+03:00"), 5, False)]}, {})
    fitted = fit_dataset(data, m, {"synthetic": True})
    result = compare(data, m, fitted, tmp_path)
    assert len(result["trials"]) == 161 and len(result["summary_rows"]) == 190
    assert result["selected"]["pooled"] is None and result["full_38_winner"] is None
    assert next(r for r in result["summary_rows"] if r["candidate_id"] == "frozen" and r["queue_id"] == 14)["status"] == "not_applicable"
