"""Перевірені табличні результати для локального інтерактивного Data-звіту."""
import csv
import json
from datetime import datetime
from pathlib import Path

CANDIDATES = ("calendar", "trend", "frozen", "pooled", "chop_local")


def report_rows(results, queue_ids):
    indexed = {(r["candidate_id"], r["queue_id"]): r for r in results}
    if len(indexed) != len(results):
        raise ValueError("select one period/scenario before building report rows")
    rows = []
    for candidate in CANDIDATES:
        for queue in queue_ids:
            unsupported = candidate == "frozen" and queue not in (1, 6, 17, 29) or candidate == "chop_local" and queue != 17
            if unsupported:
                row = {"status": "not_applicable"}
            else:
                row = indexed.get((candidate, queue), {"status": "data_not_available"})
            rows.append({"candidate_id": candidate, "queue_id": queue, "precision": None,
                         "overall_recall": None, "observed_events": None, "tp_alerts": None,
                         "fp_alerts": None, "fn_events": None, **row})
    return rows


def json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("unsupported report value")


def write_report(results, output_dir: Path, *, provenance=None, synthetic=False):
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2,
                                                        default=json_default, allow_nan=False), encoding="utf-8")
    fields = sorted({key for row in results for key in row})
    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, default=json_default, allow_nan=False)
                             if isinstance(value, (dict, list, tuple)) else value for key, value in row.items()})
    snapshot = {"surface": "report", "title": "AvelRen: перевірка прогнозу по чергах",
                "status": "fixture" if synthetic else "reviewed", "buildStatus": "creating",
                "filters": [], "report": {"synthetic": synthetic},
                "queries": {"queue_results": {"rows": results, "source": {
                    "label": "Синтетична перевірка evaluator" if synthetic else "Локальний replay дозволеної історії",
                    "kind": "synthetic" if synthetic else "local_files", "provenance": provenance or {},
                    "metricDefinitions": [
                        {"label": "Precision", "definition": "TP початкових попереджень / (TP + FP); unknown виключено окремо.",
                         "componentIds": ["surge-results", "surge-summary"]},
                        {"label": "Overall recall", "definition": "Зіставлені чисті події / усі чисті події області recall; реальні пропуски історії не прибирають FN.",
                         "componentIds": ["surge-results", "surge-summary"]},
                        {"label": "Часові області", "definition": "Для [S,E): попередження [S,E−24г35хв), події [S+24г,E−23г35хв). Межі праворуч виключні.",
                         "componentIds": ["surge-results", "surge-methods"]}]}}}}
    (output_dir / "reviewed.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2,
                                                         default=json_default, allow_nan=False), encoding="utf-8")
