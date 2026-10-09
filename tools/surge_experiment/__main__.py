"""Локальний CLI; credentials, мережа й production DSN не використовуються."""
import argparse
import json
import sys

from .data import load_dataset, local_path, timestamp
from .manifest import validate_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "replay", "fit", "compare", "report", "legacy"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--fit-dir")
    parser.add_argument("--results")
    parser.add_argument("--legacy-data-dir")
    parser.add_argument("--latency", type=int, choices=(0, 60), default=0)
    args = parser.parse_args(argv)
    try:
        output = local_path(args.output)
        if output.exists():
            raise ValueError("output already exists")
        raw_manifest = json.loads(local_path(args.manifest).read_text(encoding="utf-8"))
        manifest = validate_manifest(raw_manifest)
        data = load_dataset([p for p, _ in manifest.inputs], {p.name: sha for p, sha in manifest.inputs})
        missing = sorted(set(manifest.queue_ids) - set(data.rows))
        if set(data.rows) - set(manifest.queue_ids):
            raise ValueError("input contains unlisted queue IDs")
        if missing and not args.allow_partial:
            raise ValueError("incomplete data requires --allow-partial")
        periods = manifest.settings["periods"]
        start, end = timestamp(periods["train_start"]), timestamp(periods["development_end"])
        if any(not start <= row.time < end for rows in data.rows.values() for row in rows):
            raise ValueError("input crosses permitted development interval")
        if args.command == "compare" and not args.fit_dir:
            raise ValueError("compare requires --fit-dir")
        if args.command == "report" and not args.results:
            raise ValueError("report requires --results")
        if args.command == "legacy" and not args.legacy_data_dir:
            raise ValueError("legacy requires --legacy-data-dir")
        receipt = {"code_commit": manifest.code_commit, "counts": {str(k): len(v) for k, v in data.rows.items()},
                   "source_hashes": dict(data.source_hashes), "missing_queue_ids": missing,
                   "status": "partial" if missing else "validated"}
        output.mkdir(parents=True, exist_ok=False)
        (output / "validation.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        (output / "manifest.json").write_text(json.dumps(raw_manifest, indent=2), encoding="utf-8")
        if args.command == "replay":
            from dataclasses import asdict

            from .frozen import FrozenCandidate
            from .replay import replay
            from .report import json_default
            result = replay(data, FrozenCandidate(), manifest, args.latency)
            (output / "replay.json").write_text(json.dumps(asdict(result), default=json_default, sort_keys=True), encoding="utf-8")
        elif args.command in ("fit", "compare"):
            from .runner import compare, encoded, fit_dataset, read_fit
            if args.command == "fit":
                result = fit_dataset(data, manifest, raw_manifest)
                (output / "fit.json").write_bytes(encoded(result))
            else:
                fitted = read_fit(local_path(args.fit_dir) / "fit.json", raw_manifest)
                result = compare(data, manifest, fitted, output,
                                 progress=lambda value: print(json.dumps(value), flush=True))
                (output / "comparison.json").write_bytes(encoded(result))
        elif args.command == "report":
            from .report import write_report
            result = json.loads(local_path(args.results).read_text(encoding="utf-8"))
            if result.get("manifest") != raw_manifest:
                raise ValueError("result manifest mismatch")
            write_report(result["summary_rows"], output / "tables",
                         provenance={"source_hashes": dict(data.source_hashes), "code_commit": manifest.code_commit,
                                     "protocol": "shared-surge-v1", "scope": result["scope"]})
        elif args.command == "legacy":
            from .legacy import run_legacy
            directory = local_path(args.legacy_data_dir)
            if any(p.resolve().parent != directory.resolve() for p, _ in manifest.inputs):
                raise ValueError("legacy inputs must be the manifest directory")
            run_legacy(directory, timestamp(periods["selection_end"]), timestamp(periods["development_end"]),
                       output / "legacy.json")
        return 0
    except (ValueError, OSError) as exc:
        # Never expose input contents, DSNs, or OS exception paths.
        safe = str(exc) if type(exc) is ValueError else "local input/output operation failed"
        print(f"research: {safe}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
