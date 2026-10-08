"""Відмова до аналізу неправильних або непогоджених inputs."""
import json
from datetime import UTC, datetime

import pytest


def test_hash_mismatch_fails_before_parse(tmp_path):
    from tools.surge_experiment.data import load_dataset
    path = tmp_path / "broken.gz"
    path.write_bytes(b"not gzip or json")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dataset([path], {path.name: "0" * 64})


@pytest.mark.parametrize("bad", [True, -1, 1.5, float("nan"), "SECRET"])
def test_duplicate_and_invalid_count_rejected(input_archive, bad):
    from tools.surge_experiment.data import load_dataset
    path, hashes = input_archive([[17, 1786000000, bad, False]])
    with pytest.raises(ValueError) as exc:
        load_dataset([path], hashes)
    assert "SECRET" not in str(exc.value)


def test_duplicate_key_across_files_rejected(input_archive):
    from tools.surge_experiment.data import load_dataset
    one, h1 = input_archive([[17, 1786000000, 10, False]], "one.gz")
    two, h2 = input_archive([[17, 1786000000, 11, True]], "two.gz")
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset([one, two], h1 | h2)


def test_rows_sorted_and_normalized_to_utc(input_archive):
    from tools.surge_experiment.data import load_dataset
    path, hashes = input_archive([
        [17, "2026-09-01T10:01:00+03:00", 11, True],
        [17, "2026-09-01T10:00:00+03:00", 10, False],
    ])
    data = load_dataset([path], hashes)
    assert [r.count for r in data.rows[17]] == [10, 11]
    assert data.rows[17][0].time == datetime(2026, 9, 1, 7, tzinfo=UTC)


def test_naive_timestamp_and_invalid_pause_rejected(input_archive):
    from tools.surge_experiment.data import load_dataset
    for row in ([17, "2026-09-01T10:00:00", 10, False], [17, 1786000000, 10, 0]):
        path, hashes = input_archive([row])
        with pytest.raises(ValueError):
            load_dataset([path], hashes)


def test_missing_parameter_blocks_fit(tmp_path, capsys):
    from tools.surge_experiment.__main__ import main
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"version": "shared-surge-v1"}))
    output = tmp_path / "output"
    assert main(["fit", "--manifest", str(path), "--output", str(output)]) == 2
    assert not output.exists()
    assert "manifest" in capsys.readouterr().err


@pytest.mark.parametrize("path", ["https://example.invalid/data.gz", "//host/share/data.gz", "\\\\host\\share\\data.gz"])
def test_no_network_or_production_credentials(path, monkeypatch):
    from tools.surge_experiment.data import load_dataset
    monkeypatch.setenv("DATABASE_URL", "postgresql://private-secret")
    with pytest.raises(ValueError, match="local") as exc:
        load_dataset([path], {})
    assert "private-secret" not in str(exc.value)


def test_existing_output_never_overwritten(tmp_path):
    from tools.surge_experiment.__main__ import main
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "marker"
    marker.write_text("keep")
    assert main(["validate", "--manifest", "missing.json", "--output", str(output)]) == 2
    assert marker.read_text() == "keep"


def test_complete_manifest_validates_and_nested_omission_fails(input_archive):
    from tools.surge_experiment.manifest import protocol_v1, validate_manifest
    path, hashes = input_archive([[17, 1786000000, 10, False]])
    config = {"version": "shared-surge-v1", "queue_ids": [17],
              "inputs": [{"path": str(path), "sha256": hashes[path.name]}],
              "code_commit": "a" * 40, "protocol": protocol_v1()}
    manifest = validate_manifest(config)
    assert manifest.queue_ids == (17,)
    config["protocol"]["training"].pop("seed")
    with pytest.raises(ValueError, match="protocol"):
        validate_manifest(config)
    assert manifest.settings["training"]["seed"] == 20261009


def test_validate_receipt_and_partial_input_policy(input_archive, tmp_path):
    from tools.surge_experiment.__main__ import main
    from tools.surge_experiment.manifest import protocol_v1
    path, hashes = input_archive([[17, 1786000000, 10, False]])
    config = {"version": "shared-surge-v1", "queue_ids": [1, 17],
              "inputs": [{"path": str(path), "sha256": hashes[path.name]}],
              "code_commit": "a" * 40, "protocol": protocol_v1()}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(config))
    output = tmp_path / "result"
    args = ["validate", "--manifest", str(manifest), "--output", str(output)]
    assert main(args) == 2
    assert not output.exists()
    assert main(args + ["--allow-partial"]) == 0
    receipt = json.loads((output / "validation.json").read_text())
    assert receipt["missing_queue_ids"] == [1]
    assert receipt["counts"] == {"17": 1}
