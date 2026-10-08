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
    args = parser.parse_args(argv)
    try:
        output = local_path(args.output)
        if output.exists():
            raise ValueError("output already exists")
        manifest = validate_manifest(json.loads(local_path(args.manifest).read_text(encoding="utf-8")))
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
        if args.command != "validate":
            raise ValueError("command not implemented; no analysis performed")
        receipt = {"code_commit": manifest.code_commit, "counts": {str(k): len(v) for k, v in data.rows.items()},
                   "source_hashes": dict(data.source_hashes), "missing_queue_ids": missing,
                   "status": "partial" if missing else "validated"}
        output.mkdir(parents=True, exist_ok=False)
        (output / "validation.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        return 0
    except (ValueError, OSError) as exc:
        # Never expose input contents, DSNs, or OS exception paths.
        safe = str(exc) if type(exc) is ValueError else "local input/output operation failed"
        print(f"research: {safe}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
