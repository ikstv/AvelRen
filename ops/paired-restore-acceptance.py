"""Validate a paired backup and accept recovery only inside the owned rehearsal."""

import argparse
import asyncio
import gzip
import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_backup_manifest import (  # noqa: E402
    ManifestError,
    load_manifest,
    validate_manifest,
    verify_local_pair,
)


def _receipt_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError("replay_receipt_invalid")
        result[key] = value
    return result


def validate_receipt(text: str | bytes, manifest: dict) -> dict:
    """Emit only exact integer/count evidence from an otherwise untrusted stdout file."""
    manifest = validate_manifest(manifest)
    try:
        if len(text) > 1_048_576:
            raise ValueError
        value = json.loads(text, object_pairs_hook=_receipt_object)
        fields = {
            "acked_cycles",
            "acked_observations",
            "recovered_started",
            "replayed_sequences",
            "verified_cycles",
            "verified_observations",
            "primary_counts",
            "pending_after",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError
        for field in fields - {"primary_counts", "replayed_sequences"}:
            if type(value[field]) is not int or not 0 <= value[field] <= 2**63 - 1:
                raise ValueError
        primary = value["primary_counts"]
        if type(primary) is not dict or set(primary) != {"runs", "observations"}:
            raise ValueError
        if any(type(count) is not int or not 0 <= count <= 2**63 - 1 for count in primary.values()):
            raise ValueError
        counts = manifest["spool"]["state_counts"]
        sequences = value["replayed_sequences"]
        if (
            type(sequences) is not list
            or len(sequences) != counts["pending"] + counts["started"]
            or any(type(seq) is not int or not 1 <= seq <= 2**63 - 1 for seq in sequences)
            or any(left >= right for left, right in zip(sequences, sequences[1:], strict=False))
        ):
            raise ValueError
        cycle_range = manifest["spool"]["cycle_range"]
        if sequences and not (
            cycle_range["first_seq"] <= sequences[0] <= sequences[-1] <= cycle_range["last_seq"]
        ):
            raise ValueError
        if (
            value["acked_cycles"] != counts["acked"]
            or value["recovered_started"] != counts["started"]
            or value["verified_cycles"] != sum(counts.values())
            or value["pending_after"] != 0
            or value["acked_observations"] > value["verified_observations"]
            or (counts["acked"] == 0 and value["acked_observations"] != 0)
            or (manifest["spool"]["payload_count"] == 0 and value["verified_observations"] != 0)
            or primary["runs"] < value["verified_cycles"]
            or primary["observations"] < value["verified_observations"]
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError) as exc:
        raise ManifestError("replay_receipt_invalid") from exc
    return value


def read_pair(directory: Path, basename: str, work: Path) -> dict:
    """Validate all inputs before extracting into a newly owned private directory."""
    if not re.fullmatch(r"avelren-[0-9]{8}-[0-9]{6}\.pair\.json", basename):
        raise ManifestError("manifest_name_invalid")
    directory, work = Path(directory), Path(work)
    path = directory / basename
    if not path.is_file() or path.is_symlink():
        raise ManifestError("pair_incomplete")
    manifest = load_manifest(path.read_bytes())
    if basename != f"avelren-{manifest['backup_id']}.pair.json":
        raise ManifestError("manifest_name_invalid")
    verify_local_pair(manifest, directory)
    if work.exists() or work.resolve().is_relative_to(directory.resolve()):
        raise ManifestError("restore_work_unsafe")
    work.mkdir(mode=0o700)
    try:
        for artifact in manifest["artifacts"].values():
            for suffix in ("", ".sha256"):
                shutil.copyfile(
                    directory / (artifact["name"] + suffix), work / (artifact["name"] + suffix)
                )
                os.chmod(work / (artifact["name"] + suffix), 0o600)
        # Recheck the bytes actually copied before native restore/recovery.
        verify_local_pair(manifest, work)
        spool = work / "restored.sqlite3"
        with (
            gzip.open(work / manifest["artifacts"]["spool"]["name"], "rb") as source,
            spool.open("xb") as target,
        ):
            shutil.copyfileobj(source, target)
        os.chmod(spool, 0o600)
        from avelren.paired_backup_spool import inspect_spool

        if inspect_spool(spool) != manifest["spool"]:
            raise ManifestError("spool_summary_invalid")
        (work / "pair.json").write_text(json.dumps(manifest), encoding="utf-8")
        os.chmod(work / "pair.json", 0o600)
    except BaseException:
        shutil.rmtree(work)
        raise
    return manifest


async def recover_pair(store, dsn: str) -> dict:
    """ACK verification precedes any restored SQLite mutation and FIFO replay."""
    from avelren.collector_replay import replay_once, verify_committed_cycle
    from avelren.paired_backup_spool import decode_cycle, verify_acked_primary
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    async with AsyncConnectionPool(dsn, open=False, kwargs={"row_factory": dict_row}) as pool:
        async with pool.connection() as conn:
            evidence = await verify_acked_primary(store, conn)
        started = store.conn.execute(
            "SELECT count(*) FROM cycles WHERE state='started'"
        ).fetchone()[0]
        acked_before = store.conn.execute(
            "SELECT * FROM cycles WHERE state='acked' ORDER BY seq"
        ).fetchall()
        store.recover_started()
        expected = [
            decode_cycle(row)
            for row in store.conn.execute(
                "SELECT seq,at,payload_version,payload,payload_sha256 FROM cycles ORDER BY seq"
            )
        ]
        store.set_capture_only(False)
        replayed = []
        while (cycle := store.next_pending()) is not None:
            if not await replay_once(store, pool, datetime.now(UTC), prune_acked=False):
                raise RuntimeError("restored_replay_paused")
            replayed.append(cycle.seq)
        async with pool.connection() as conn:
            for cycle in expected:
                await verify_committed_cycle(conn, cycle)
            counts = await (
                await conn.execute(
                    "SELECT (SELECT count(*) FROM collector_runs) AS runs, "
                    "(SELECT count(*) FROM observations) AS observations"
                )
            ).fetchone()
        for row in acked_before:
            if store.conn.execute("SELECT * FROM cycles WHERE seq=?", (row[0],)).fetchone() != row:
                raise RuntimeError("retained_ack_changed")
        evidence.update(
            recovered_started=started,
            replayed_sequences=replayed,
            verified_cycles=len(expected),
            verified_observations=sum(len(c.items) for c in expected),
            primary_counts=dict(counts),
            pending_after=store.status().pending_count,
        )
        return evidence


def owned_dsn() -> str:
    from psycopg.conninfo import conninfo_to_dict

    expected = "postgresql://avelren_collector:ci-only@db:5432/restore_test"
    if os.environ.get("AVELREN_PAIRED_REHEARSAL") != "1" or conninfo_to_dict(
        os.environ.get("DATABASE_URL", "")
    ) != conninfo_to_dict(expected):
        raise ManifestError("rehearsal_identity_refused")
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--directory", type=Path, required=True)
    prepare.add_argument("--manifest", required=True)
    prepare.add_argument("--work", type=Path, required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--work", type=Path, required=True)
    receipt = commands.add_parser("receipt")
    receipt.add_argument("--source", type=Path, required=True)
    receipt.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            read_pair(args.directory, args.manifest, args.work)
            print("pair_preflight_ok")
        elif args.command == "receipt":
            if args.source.stat().st_size > 1_048_576:
                raise ManifestError("replay_receipt_invalid")
            manifest = load_manifest(args.manifest.read_bytes())
            print(json.dumps(validate_receipt(args.source.read_bytes(), manifest), sort_keys=True))
        else:
            from avelren.collector_spool import SpoolStore
            from avelren.paired_backup_spool import inspect_spool

            dsn = owned_dsn()
            if args.work.resolve() != Path("/evidence/pair"):
                raise ManifestError("restore_work_unsafe")
            manifest = load_manifest((args.work / "pair.json").read_bytes())
            if inspect_spool(args.work / "restored.sqlite3") != manifest["spool"]:
                raise ManifestError("spool_summary_invalid")
            store = SpoolStore(args.work / "restored.sqlite3")
            try:
                print(json.dumps(asyncio.run(recover_pair(store, dsn)), sort_keys=True))
            finally:
                store.close()
    except Exception:
        # No DSN, payload or rejected value crosses the operator log boundary.
        print("paired_restore_acceptance_failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
