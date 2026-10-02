"""Additive measured-wait response with the historical numeric fields intact."""

from datetime import UTC, datetime, timedelta


def _iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_workload_additive_contract(api_client, checkpoint, conn):
    at = datetime.now(UTC).replace(microsecond=0)
    cases = (
        (checkpoint, 0, 80, False, "missing", "missing", None, None),
        (checkpoint + 1, 0, 80, False, None, "legacy_unknown", None, None),
        (checkpoint + 2, 0, 80, False, "reported", "reported", 0, at),
        (checkpoint + 3, 3600, 80, True, "reported", "reported", 3600, at + timedelta(hours=1)),
        (checkpoint + 4, 0, 0, True, "reported", "reported", 0, None),
    )
    for cid, seconds, vehicles, paused, stored_status, *_ in cases:
        if cid != checkpoint:
            conn.execute(
                "INSERT INTO checkpoints (id,title,for_vehicle_type,country_name) "
                "VALUES (%s,'synthetic',1,'test')",
                (cid,),
            )
        conn.execute(
            "INSERT INTO observations "
            "(time,checkpoint_id,wait_time_seconds,vehicles_in_queue,is_paused,wait_time_status) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (at, cid, seconds, vehicles, paused, stored_status),
        )

    response = api_client.get("/workload")
    assert response.status_code == 200
    by_id = {row["checkpoint_id"]: row for row in response.json()}
    assert set(by_id) == {case[0] for case in cases}
    for cid, seconds, vehicles, paused, _, expected_status, expected_seconds, expected_eta in cases:
        item = by_id[cid]
        assert item["wait_time_seconds"] == seconds
        assert item["vehicles_in_queue"] == vehicles
        assert item["is_paused"] is paused
        estimate = item["wait_estimate"]
        assert estimate["status"] == expected_status
        assert estimate["seconds"] == expected_seconds
        assert (_iso(estimate["entry_eta"]) if estimate["entry_eta"] else None) == expected_eta

    assert by_id[checkpoint + 2]["entry_eta"] is None  # legacy zero suppression
    assert by_id[checkpoint + 3]["entry_eta"] is not None  # paused positive unchanged
