"""Повний реєстр звіту не приховує відсутні дані та різні знаменники."""
def test_38_by_5_rows_preserve_not_applicable():
    from tools.surge_experiment.report import report_rows
    rows = report_rows([], tuple(range(1, 39)))
    assert len(rows) == 190
    assert next(r for r in rows if r["queue_id"] == 14 and r["candidate_id"] == "frozen")["status"] == "not_applicable"
    assert next(r for r in rows if r["queue_id"] == 14 and r["candidate_id"] == "pooled")["status"] == "data_not_available"


def test_twelve_and_seven_remain_distinct():
    from tools.surge_experiment.report import report_rows
    result = {"queue_id": 17, "candidate_id": "pooled", "observed_events": 12, "strict_future_origins_events": 7}
    row = next(r for r in report_rows([result], (17,)) if r["candidate_id"] == "pooled")
    assert row["observed_events"] == 12 and row["strict_future_origins_events"] == 7


def test_report_snapshot_retains_nulls_and_fixture_label(tmp_path):
    import json

    from tools.surge_experiment.report import report_rows, write_report
    target = tmp_path / "report"
    write_report(report_rows([], (1, 17)), target, synthetic=True)
    snapshot = json.loads((target / "reviewed.json").read_text(encoding="utf-8"))
    assert snapshot["status"] == "fixture"
    assert snapshot["queries"]["queue_results"]["rows"][0]["precision"] is None
