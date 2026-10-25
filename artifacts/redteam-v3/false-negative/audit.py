"""Local-only false-negative audit; independent business calculation via APIs.

Run from the repository root with PYTHONDONTWRITEBYTECODE=1. The only writes
are an exclusive, timestamped evidence directory next to this file.
"""

import argparse
import copy
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from alert_rlvr import verifier
from alert_rlvr.config import make_task
from alert_rlvr.environment import AlertEnvironment

START = "2026-10-25T08:00:00Z"
END = "2026-10-25T08:30:00Z"


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def independent_answer(seed):
    """Do not import reference_agent or call expected_answer.

    Literal business rules below are derived from the actual task text.
    Raw input is retrieved exclusively through the public business APIs.
    """
    with AlertEnvironment(seed) as env:
        def query(name, **arguments):
            result = env.call(name, arguments)
            if not result["ok"]:
                raise RuntimeError(result)
            return result["data"]

        alerts = query("list_alerts", start=START, end=END)
        eligible = {}
        for alert in alerts:
            if alert["severity"] not in ("P0", "P1") or alert["state"] != "firing":
                continue
            if dt(alert["started_at"]) >= dt(END):
                continue
            if alert["ended_at"] is not None and dt(alert["ended_at"]) <= dt(END):
                continue
            iid = alert["incident_id"]
            eligible[iid] = min(eligible.get(iid, "P1"), alert["severity"])

        if not eligible:
            return {"snapshot_id": env.snapshot_id, "incidents": [], "priority": []}, []
        relations = query("get_incident_services", incident_ids=list(eligible))
        ids = sorted({r["service_id"] for r in relations})
        profiles = {r["service_id"]: r for r in query("get_service_profiles", service_ids=ids)}
        metrics = query("get_request_metrics", service_ids=ids, start=START, end=END)
        maintenance = query("get_maintenance_windows", service_ids=ids, start=START, end=END)

        totals = {}
        service_contributions = {}
        counted = set()
        trace = []
        for relation in relations:
            iid, sid = relation["incident_id"], relation["service_id"]
            profile = profiles[sid]
            if profile["environment"] != "production":
                continue
            for bucket in metrics:
                if bucket["service_id"] != sid:
                    continue
                left, right = dt(bucket["bucket_start"]), dt(bucket["bucket_end"])
                key = (iid, sid, left)
                if key in counted:
                    continue
                if not (dt(START) <= left < right <= dt(END)):
                    continue
                if not (dt(relation["impact_start"]) <= left and right <= dt(relation["impact_end"])):
                    continue
                if any(m["service_id"] == sid and m["status"] == "approved"
                       and dt(m["starts_at"]) <= left and right <= dt(m["ends_at"])
                       for m in maintenance):
                    continue
                counted.add(key)
                baseline = bucket["request_count"] * profile["baseline_failure_bps"] // 10000
                excess = max(bucket["failed_requests"] - baseline, 0)
                totals[iid] = totals.get(iid, 0) + excess
                service_contributions[(iid, sid)] = service_contributions.get((iid, sid), 0) + excess
                trace.append({"incident_id": iid, "service_id": sid,
                              "bucket_start": bucket["bucket_start"],
                              "baseline": baseline, "excess": excess})
        rows = [{"incident_id": iid, "severity": eligible[iid],
                 "service_ids": sorted(sid for (event, sid), n in service_contributions.items()
                                       if event == iid and n > 0),
                 "excess_failed_requests": n}
                for iid, n in sorted(totals.items()) if n > 0]
        ranking = sorted(rows, key=lambda row: (-row["excess_failed_requests"], row["severity"], row["incident_id"]))
        return {"snapshot_id": env.snapshot_id, "incidents": rows,
                "priority": [row["incident_id"] for row in ranking[:2]]}, trace


def numeric_fixture(case):
    """New out-of-distribution snapshot; public generator cannot produce it."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE alerts (alert_id TEXT PRIMARY KEY, incident_id TEXT,
            resource_id TEXT, severity TEXT, state TEXT, started_at TEXT,
            ended_at TEXT, title TEXT, description TEXT, source TEXT);
        CREATE TABLE incident_services (incident_id TEXT, service_id TEXT,
            impact_start TEXT, impact_end TEXT);
        CREATE TABLE services (service_id TEXT PRIMARY KEY, name TEXT,
            environment TEXT, baseline_failure_bps INTEGER, owner_team TEXT,
            dashboard_url TEXT);
        CREATE TABLE request_metrics (service_id TEXT, bucket_start TEXT,
            bucket_end TEXT, request_count INTEGER, failed_requests INTEGER,
            retry_count INTEGER, latency_p95_ms INTEGER);
        CREATE TABLE maintenance (maintenance_id TEXT PRIMARY KEY, service_id TEXT,
            starts_at TEXT, ends_at TEXT, status TEXT, reason TEXT);
    """)
    db.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?,?,?)",
               ("ALERT-1", "INC-EXACT", "host-1", "P1", "firing", START, None, "Synthetic", "", "audit"))
    db.execute("INSERT INTO incident_services VALUES (?,?,?,?)", ("INC-EXACT", "svc-exact", START, END))
    baseline = 5000 if case == "product_precision" else 0
    db.execute("INSERT INTO services VALUES (?,?,?,?,?,?)",
               ("svc-exact", "Exact integer arithmetic", "production", baseline, "audit", "https://example.invalid"))
    observations = [(0, 5, 9007199254740995, 4503599627370498)] if case == "product_precision" else [
        (0, 5, 2 ** 62, 2 ** 62), (5, 10, 2 ** 62, 2 ** 62)]
    for left, right, requests, failed in observations:
        db.execute("INSERT INTO request_metrics VALUES (?,?,?,?,?,?,?)",
                   ("svc-exact", f"2026-10-25T08:{left:02d}:00Z", f"2026-10-25T08:{right:02d}:00Z",
                    requests, failed, 0, 0))
    db.commit()
    return db


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-count", type=int, default=10000)
    args = parser.parse_args()
    destination = Path(__file__).resolve().parent / ("evidence-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    destination.mkdir()
    started = time.monotonic()
    task = make_task(17)
    (destination / "task-seed-17.txt").write_text(task, encoding="utf-8")
    golden, trace = independent_answer(17)
    write_json(destination / "independent-answer-seed-17.json", golden)
    write_json(destination / "independent-buckets-seed-17.json", trace)

    # Every permutation of three rows and the DB event's two services.
    equivalent = []
    for order in itertools.permutations(golden["incidents"]):
        for reverse in (False, True):
            answer = copy.deepcopy(golden)
            answer["incidents"] = copy.deepcopy(list(order))
            if reverse:
                for row in answer["incidents"]:
                    row["service_ids"].reverse()
            for kind in ("dict", "compact_json", "pretty_json", "escaped_json"):
                value = answer if kind == "dict" else json.dumps(answer, indent=2 if kind == "pretty_json" else None)
                if kind == "escaped_json":
                    value = value.replace("INC", "\\u0049\\u004e\\u0043")
                equivalent.append({"row_order": [r["incident_id"] for r in order], "reverse_services": reverse,
                                   "representation": kind, "reward": verifier.compute_reward(task, value)})
    write_json(destination / "equivalent-representations.json", equivalent)

    compact = json.dumps(golden, separators=(",", ":"))
    at_limit = compact + " " * (1000000 - len(compact.encode("utf-8")))
    above_limit = at_limit + " "
    (destination / "correct-but-over-byte-limit.json").write_text(above_limit, encoding="utf-8")
    byte_limit = {
        "at_limit_bytes": len(at_limit.encode("utf-8")),
        "above_limit_bytes": len(above_limit.encode("utf-8")),
        "semantic_equality": json.loads(at_limit) == json.loads(above_limit) == golden,
        "at_limit": verifier.evaluate(task, at_limit),
        "above_limit": verifier.evaluate(task, above_limit),
        "above_limit_compute_reward": verifier.compute_reward(task, above_limit),
    }
    write_json(destination / "byte-limit-result.json", byte_limit)

    numeric = []
    for case, exact in (("product_precision", 1), ("sum_overflow", 2 ** 63)):
        answer = {"snapshot_id": golden["snapshot_id"], "incidents": [
            {"incident_id": "INC-EXACT", "severity": "P1", "service_ids": ["svc-exact"],
             "excess_failed_requests": exact}], "priority": ["INC-EXACT"]}
        with patch("alert_rlvr.verifier.build_database", lambda seed, case=case: numeric_fixture(case)):
            report = verifier.evaluate(task, answer)
            reward = verifier.compute_reward(task, answer)
        numeric.append({"case": case, "public_generator_reachable": False, "answer": answer,
                        "manual_reason": "4503599627370498 - (9007199254740995 * 5000 // 10000) = 1" if exact == 1 else "2**62 + 2**62 = 2**63",
                        "report": report, "compute_reward": reward})
    write_json(destination / "out-of-distribution-numeric-fixtures.json", numeric)

    mismatches = []
    tie_seeds = []
    priorities = {}
    for seed in range(args.seed_count):
        answer, _ = independent_answer(seed)
        reward = verifier.compute_reward(make_task(seed), answer)
        if reward != 1.0:
            mismatches.append({"seed": seed, "answer": answer, "reward": reward})
        values = [row["excess_failed_requests"] for row in answer["incidents"]]
        if len(values) != len(set(values)):
            tie_seeds.append(seed)
        ranking = ",".join(answer["priority"])
        priorities[ranking] = priorities.get(ranking, 0) + 1
        if (seed + 1) % 1000 == 0:
            print(json.dumps({"completed_seeds": seed + 1, "mismatches": len(mismatches),
                              "elapsed_seconds": round(time.monotonic() - started, 2)}), flush=True)
    summary = {"seed_start": 0, "seed_count": args.seed_count, "mismatches": mismatches,
               "tie_seed_count": len(tie_seeds), "tie_seeds": tie_seeds,
               "priority_distribution": priorities, "equivalent_representation_count": len(equivalent),
               "equivalent_representation_failures": [r for r in equivalent if r["reward"] != 1.0],
               "elapsed_seconds": round(time.monotonic() - started, 2)}
    write_json(destination / "summary.json", summary)
    print(json.dumps({"evidence_directory": str(destination), "summary": summary}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
