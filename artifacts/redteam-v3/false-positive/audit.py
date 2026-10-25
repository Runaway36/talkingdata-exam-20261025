"""Independent false-positive audit. Only writes into a new local evidence run.

Run from repository root:
  python artifacts/redteam-v3/false-positive/audit.py

No network, external models, solver imports, or business-source edits.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import itertools
import json
from pathlib import Path
import platform
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from alert_rlvr import config, data, verifier
from alert_rlvr.environment import AlertEnvironment

UTC_START = "2026-10-25T08:00:00Z"
UTC_END = "2026-10-25T08:30:00Z"


def stamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def independent_answer(seed, raw=None):
    """Read public APIs and apply literal task rules using Python integer math.

    Does not import examples/reference_agent or use expected_answer/SQL oracle.
    For generated snapshots, raw is obtained entirely through business APIs.
    """
    if raw is None:
        with AlertEnvironment(seed) as env:
            alerts = env.list_alerts(UTC_START, UTC_END)["data"]
            incident_ids = sorted({row["incident_id"] for row in alerts})
            relations = env.get_incident_services(incident_ids)["data"]
            service_ids = sorted({row["service_id"] for row in relations})
            raw = {
                "alerts": alerts,
                "incident_services": relations,
                "services": env.get_service_profiles(service_ids)["data"],
                "request_metrics": env.get_request_metrics(service_ids, UTC_START, UTC_END)["data"],
                "maintenance": env.get_maintenance_windows(service_ids, UTC_START, UTC_END)["data"],
            }
    start, end = stamp(UTC_START), stamp(UTC_END)
    severity = {}
    for alert in raw["alerts"]:
        if alert["severity"] not in ("P0", "P1") or alert["state"] != "firing":
            continue
        if stamp(alert["started_at"]) >= end:
            continue
        if alert["ended_at"] is not None and stamp(alert["ended_at"]) <= end:
            continue
        iid = alert["incident_id"]
        severity[iid] = min(severity.get(iid, "P1"), alert["severity"])
    profiles = {r["service_id"]: r for r in raw["services"]}
    totals = {}
    seen = set()
    ledger = []
    for relation in raw["incident_services"]:
        iid, sid = relation["incident_id"], relation["service_id"]
        if iid not in severity or profiles[sid]["environment"] != "production":
            continue
        for metric in raw["request_metrics"]:
            if metric["service_id"] != sid:
                continue
            lo, hi = stamp(metric["bucket_start"]), stamp(metric["bucket_end"])
            if not (start <= lo and hi <= end and stamp(relation["impact_start"]) <= lo and hi <= stamp(relation["impact_end"])):
                continue
            key = iid, sid, lo
            if key in seen:
                continue
            seen.add(key)
            covered = any(
                m["service_id"] == sid and m["status"] == "approved"
                and stamp(m["starts_at"]) <= lo and hi <= stamp(m["ends_at"])
                for m in raw["maintenance"]
            )
            baseline = metric["request_count"] * profiles[sid]["baseline_failure_bps"] // 10000
            excess = 0 if covered else max(0, metric["failed_requests"] - baseline)
            ledger.append({"incident_id": iid, "service_id": sid, "bucket_start": metric["bucket_start"], "request_count": metric["request_count"], "failed_requests": metric["failed_requests"], "baseline_failure_bps": profiles[sid]["baseline_failure_bps"], "baseline_failures": baseline, "approved_full_maintenance": covered, "excess": excess})
            totals[iid, sid] = totals.get((iid, sid), 0) + excess
    rows = []
    for iid in sorted(severity):
        services = sorted(sid for (incident, sid), total in totals.items() if incident == iid and total > 0)
        total = sum(totals[iid, sid] for sid in services)
        if total:
            rows.append({"incident_id": iid, "severity": severity[iid], "service_ids": services, "excess_failed_requests": total})
    ranked = sorted(rows, key=lambda r: (-r["excess_failed_requests"], r["severity"], r["incident_id"]))
    answer = {"snapshot_id": config.snapshot_id(seed), "incidents": rows, "priority": [r["incident_id"] for r in ranked[:2]]}
    return answer, raw, ledger


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def semantic_equal(actual, gold):
    def normalized(a):
        rows = sorted((r["incident_id"], r["severity"], tuple(sorted(r["service_ids"])), r["excess_failed_requests"]) for r in a["incidents"])
        return a["snapshot_id"], rows, a["priority"]
    return normalized(actual) == normalized(gold)


def matrix_variants(gold):
    """All 5^3 event states, optional extra, and legal distinct priorities."""
    options = []
    for row in gold["incidents"]:
        states = [None, copy.deepcopy(row)]
        for field, value in (("severity", "P1" if row["severity"] == "P0" else "P0"), ("service_ids", []), ("excess_failed_requests", row["excess_failed_requests"] + 1)):
            variant = copy.deepcopy(row)
            variant[field] = value
            states.append(variant)
        options.append(states)
    for states in itertools.product(range(5), repeat=len(options)):
        rows = [copy.deepcopy(options[i][s]) for i, s in enumerate(states) if options[i][s] is not None]
        for extra in (False, True):
            submitted = copy.deepcopy(rows)
            if extra:
                submitted.append({"incident_id": "INC-EXTRA", "severity": "P0", "service_ids": ["svc-extra"], "excess_failed_requests": 999})
            ids = [r["incident_id"] for r in submitted]
            for size in range(min(2, len(ids)) + 1):
                for priority in itertools.permutations(ids, size):
                    yield {"snapshot_id": gold["snapshot_id"], "incidents": submitted, "priority": list(priority)}, {"states": states, "extra": extra}


def protocol_variants(gold):
    def edited(path, value):
        result = copy.deepcopy(gold)
        node = result
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
        return result
    base = json.dumps(gold)
    for name, value in (("nan", float("nan")), ("infinity", float("inf")), ("negative_infinity", -float("inf")), ("bool", True), ("negative", -1), ("integer_float", 44.0), ("fraction", 44.5), ("null", None), ("number_string", "44"), ("list", []), ("dict", {})):
        yield "count_" + name, edited(("incidents", 0, "excess_failed_requests"), value)
    for name, path in (("incidents", ("incidents",)), ("priority", ("priority",)), ("services", ("incidents", 0, "service_ids"))):
        for bad in (None, True, 1, {}, "", ("INC-DB",)):
            yield name + "_type_" + repr(bad), edited(path, bad)
    for path in (("snapshot_id",), ("incidents", 0, "incident_id"), ("incidents", 0, "severity")):
        for bad in (None, 1, True, [], {}, "", " ", "\ud800"):
            yield "string_type_" + str(path) + repr(bad), edited(path, bad)
    for extra in ("top", "nested"):
        answer = copy.deepcopy(gold)
        node = answer if extra == "top" else answer["incidents"][0]
        node["unexpected"] = "ignored?"
        yield extra + "_extra_field", answer
    answer = copy.deepcopy(gold)
    answer["incidents"].append(copy.deepcopy(answer["incidents"][0]))
    yield "duplicate_incident", answer
    answer = copy.deepcopy(gold)
    answer["incidents"][0]["service_ids"] *= 2
    yield "duplicate_service", answer
    yield "duplicate_priority", edited(("priority",), [gold["priority"][0]] * 2)
    yield "unknown_priority", edited(("priority",), ["INC-UNKNOWN"])
    yield "wrong_snapshot", edited(("snapshot_id",), config.snapshot_id(18))
    yield "duplicate_top_json_key", base[:-1] + ', "snapshot_id": "' + gold["snapshot_id"] + '"}'
    yield "duplicate_escaped_top_json_key", base[:-1] + ', "snapshot\\u005fid": "' + gold["snapshot_id"] + '"}'
    token = '"excess_failed_requests": ' + str(gold["incidents"][0]["excess_failed_requests"])
    yield "duplicate_nested_json_key", base.replace(token, token + ", " + token, 1)
    for literal in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999", "true", "null", "0.0", "1e0"):
        yield "json_numeric_" + literal, base.replace(token, '"excess_failed_requests": ' + literal, 1)
    yield "too_large_answer", base + " " * 1_000_001
    yield "giant_integer", base.replace(token, '"excess_failed_requests": ' + "9" * 5000, 1)
    for bad in (None, True, 1, [], "null", "[]", "{}", "not json", base + "garbage", "[" * 2000):
        yield "bad_root_" + repr(bad)[:40], bad
    cycle = copy.deepcopy(gold)
    cycle["priority"].append(cycle)
    yield "cyclic_dict", cycle


def fixture_database(seed, mode):
    connection = data.build_database(seed)
    connection.execute("PRAGMA query_only=OFF")
    for table in ("alerts", "incident_services", "services", "request_metrics", "maintenance", "host_metrics", "notification_history"):
        connection.execute("DELETE FROM " + table)
    if mode != "empty":
        connection.execute("INSERT INTO services VALUES ('svc-controlled', 'Controlled fixture', 'production', 100, 'audit', '')")
        connection.execute("INSERT INTO incident_services VALUES ('INC-CONTROLLED', 'svc-controlled', ?, ?)", (UTC_START, UTC_END))
        connection.execute("INSERT INTO alerts VALUES ('A-CONTROLLED', 'INC-CONTROLLED', 'host-control', 'P0', 'firing', ?, NULL, 'Controlled fixture', '', '')", (UTC_START,))
        requests = 9223372036854775807 if mode == "overflow" else 1000
        failed = requests * 100 // 10000 + 100
        connection.execute("INSERT INTO request_metrics VALUES ('svc-controlled', ?, '2026-10-25T08:05:00Z', ?, ?, 0, 0)", (UTC_START, requests, failed))
    connection.commit()
    return connection


def main():
    run = Path(__file__).parent / ("run-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    run.mkdir()
    summary = {"python": platform.python_version(), "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in ("alert_rlvr/config.py", "alert_rlvr/data.py", "alert_rlvr/environment.py", "alert_rlvr/verifier.py", "docs/CONTRACT.md")}, "generated_seeds_checked": 0, "independent_oracle_mismatches": [], "wrong_full_reward_answers": [], "matrix_cases": 0, "matrix_correct_full_rewards": 0, "protocol_cases": 0, "protocol_failures": []}
    digest = hashlib.sha256()
    for seed in range(10000):
        gold, raw, ledger = independent_answer(seed)
        scored = verifier.evaluate(config.make_task(seed), json.dumps(gold))
        if scored["reward"] != 1.0:
            summary["independent_oracle_mismatches"].append({"seed": seed, "answer": gold, "report": scored})
        digest.update(json.dumps(gold, sort_keys=True).encode())
        summary["generated_seeds_checked"] += 1
        if seed in (0, 17, 23, 91, 9999):
            dump(run / f"seed-{seed}-independent-truth.json", {"answer": gold, "ledger": ledger, "api_data": raw, "report": scored})
        if seed % 1000 == 999:
            print(f"independent generated snapshots checked: {seed + 1}", flush=True)
    summary["all_independent_answers_sha256"] = digest.hexdigest()
    gold, _, _ = independent_answer(17)
    for answer, labels in matrix_variants(gold):
        report = verifier.evaluate(config.make_task(17), json.dumps(answer))
        summary["matrix_cases"] += 1
        correct = semantic_equal(answer, gold)
        if report["reward"] == 1.0:
            if correct:
                summary["matrix_correct_full_rewards"] += 1
            else:
                summary["wrong_full_reward_answers"].append({"answer": answer, "labels": labels, "report": report})
    protocols = []
    for name, answer in protocol_variants(gold):
        report = verifier.evaluate(config.make_task(17), answer)
        summary["protocol_cases"] += 1
        protocols.append({"case": name, "report": report})
        if report["reward"] != 0.0 or report["valid"]:
            summary["protocol_failures"].append({"case": name, "report": report})
    dump(run / "protocol-results.json", protocols)
    # Result-order permutations are valid semantic equivalences, not exploits.
    reorder = copy.deepcopy(gold)
    reorder["incidents"].reverse()
    for row in reorder["incidents"]:
        row["service_ids"].reverse()
    summary["equivalent_reordering"] = verifier.evaluate(config.make_task(), reorder)
    # Changing API-returned containers must not modify the trusted snapshot.
    with AlertEnvironment(17) as env:
        before = env.list_alerts(UTC_START, UTC_END)
        before["data"][0]["severity"] = "P3"
        after = env.list_alerts(UTC_START, UTC_END)
        summary["api_return_copy_isolated"] = after["data"][0]["severity"] != "P3"
    # Controlled fixtures are injected only at the trusted dataset constructor.
    # They are not available through any public seed and are NOT JSON exploits.
    empty = {"snapshot_id": config.snapshot_id(), "incidents": [], "priority": []}
    fixture_results = {}
    for mode in ("empty", "single", "overflow"):
        db = fixture_database(17, mode)
        raw = {table: [dict(r) for r in db.execute("SELECT * FROM " + table)] for table in ("alerts", "incident_services", "services", "request_metrics", "maintenance")}
        db.close()
        truth, _, ledger = independent_answer(17, raw)
        with patch("alert_rlvr.verifier.build_database", lambda seed, mode=mode: fixture_database(seed, mode)):
            if mode == "empty":
                extra = copy.deepcopy(gold)
                fixture_results[mode] = {"truth": truth, "empty_report": verifier.evaluate(config.make_task(), empty), "extra_report": verifier.evaluate(config.make_task(), extra)}
            elif mode == "single":
                fixture_results[mode] = {"truth": truth, "gold_report": verifier.evaluate(config.make_task(), truth), "omitted_report": verifier.evaluate(config.make_task(), empty)}
            else:
                wrong = copy.deepcopy(truth)
                wrong["incidents"][0]["excess_failed_requests"] = 96
                fixture_results[mode] = {"scope": "controlled fixture only; NOT reachable from any current public seed", "task": config.make_task(), "raw": raw, "ledger": ledger, "truth": truth, "wrong_answer": wrong, "wrong_report": verifier.evaluate(config.make_task(), json.dumps(wrong)), "true_report": verifier.evaluate(config.make_task(), truth)}
    dump(run / "controlled-fixtures.json", fixture_results)
    summary["controlled_overflow_wrong_reward"] = fixture_results["overflow"]["wrong_report"]["reward"]
    summary["controlled_overflow_true_excess"] = 100
    summary["controlled_overflow_accepted_excess"] = 96
    dump(run / "summary.json", summary)
    (run / "canonical-task.txt").write_text(config.make_task() + "\n", encoding="utf-8")
    print(json.dumps({"run": str(run), **{k:v for k,v in summary.items() if k != "source_sha256"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
