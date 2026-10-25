"""Supplemental local probes: numeric spelling and manual business boundaries."""

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from unittest.mock import patch

from audit import independent_answer, make_task, numeric_fixture, verifier, write_json


def manual_singleton(total=1, iid="INC-EXACT", severity="P1", sid="svc-exact"):
    return {"snapshot_id": "alert-impact-v3-seed-17", "incidents": [
        {"incident_id": iid, "severity": severity, "service_ids": [sid],
         "excess_failed_requests": total}], "priority": [iid]}


def control_database(mutate):
    db = numeric_fixture("product_precision")
    db.execute("UPDATE services SET baseline_failure_bps=150")
    db.execute("UPDATE request_metrics SET request_count=101, failed_requests=2")
    if mutate:
        mutate(db)
    db.commit()
    return db


def main():
    destination = Path(__file__).resolve().parent / ("edge-evidence-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    destination.mkdir()
    task = make_task(17)
    golden, _ = independent_answer(17)
    raw = json.dumps(golden, separators=(",", ":"))
    variants = {
        "integer_json": raw,
        "integer_valued_decimal_json": re.sub(r'("excess_failed_requests":)(\d+)', r'\g<1>\g<2>.0', raw),
        "integer_valued_exponent_json": re.sub(r'("excess_failed_requests":)(\d+)', r'\g<1>\g<2>e0', raw),
    }
    numeric = []
    for name, value in variants.items():
        decoded = json.loads(value)
        numeric.append({"name": name, "answer": value,
                        "value_equality_after_json_parsing": decoded == golden,
                        "numeric_types_after_json_parsing": [type(r["excess_failed_requests"]).__name__ for r in decoded["incidents"]],
                        "report": verifier.evaluate(task, value), "compute_reward": verifier.compute_reward(task, value)})
    write_json(destination / "numeric-spelling.json", numeric)

    empty = {"snapshot_id": "alert-impact-v3-seed-17", "incidents": [], "priority": []}
    maintenance = "INSERT INTO maintenance VALUES ('M1','svc-exact',?,?,'approved','synthetic')"
    cases = [
        ("floor_then_subtract", None, manual_singleton()),
        ("equal_baseline_excludes_service", lambda db: db.execute("UPDATE request_metrics SET failed_requests=1"), empty),
        ("below_baseline_clamps_to_zero", lambda db: db.execute("UPDATE request_metrics SET failed_requests=0"), empty),
        ("one_second_partial_impact_excludes_bucket", lambda db: db.execute("UPDATE incident_services SET impact_start='2026-10-25T08:00:01Z'"), empty),
        ("exact_impact_end_includes_bucket", lambda db: db.execute("UPDATE incident_services SET impact_end='2026-10-25T08:05:00Z'"), manual_singleton()),
        ("full_maintenance_excludes_bucket", lambda db: db.execute(maintenance, ("2026-10-25T08:00:00Z", "2026-10-25T08:05:00Z")), empty),
        ("partial_maintenance_keeps_bucket", lambda db: db.execute(maintenance, ("2026-10-25T08:00:00Z", "2026-10-25T08:04:59Z")), manual_singleton()),
        ("cancelled_maintenance_keeps_bucket", lambda db: db.execute("INSERT INTO maintenance VALUES ('M1','svc-exact','2026-10-25T08:00:00Z','2026-10-25T08:05:00Z','cancelled','synthetic')"), manual_singleton()),
        ("ended_at_report_end_is_not_active", lambda db: db.execute("UPDATE alerts SET ended_at='2026-10-25T08:30:00Z'"), empty),
        ("ends_after_report_end_is_active", lambda db: db.execute("UPDATE alerts SET ended_at='2026-10-25T08:30:01Z'"), manual_singleton()),
        ("duplicate_eligible_alert_does_not_multiply", lambda db: db.execute("INSERT INTO alerts SELECT 'ALERT-2',incident_id,resource_id,severity,state,started_at,ended_at,title,description,source FROM alerts"), manual_singleton()),
        ("staging_excludes_service", lambda db: db.execute("UPDATE services SET environment='staging'"), empty),
    ]
    results = []
    for name, mutate, answer in cases:
        with patch("alert_rlvr.verifier.build_database", lambda seed, mutate=mutate: control_database(mutate)):
            report = verifier.evaluate(task, answer)
            reward = verifier.compute_reward(task, answer)
        results.append({"case": name, "public_generator_reachable": False,
                        "answer": answer, "report": report, "compute_reward": reward})
    write_json(destination / "manual-business-boundaries.json", results)
    print(json.dumps({"evidence_directory": str(destination), "numeric_spelling": [{"name": r["name"], "reward": r["compute_reward"]} for r in numeric],
                      "manual_boundary_count": len(results), "manual_boundary_failures": [r for r in results if r["compute_reward"] != 1.0]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
