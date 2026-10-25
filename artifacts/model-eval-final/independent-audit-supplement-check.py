"""Audit the four supplementary runs and two GPT single solves, without model calls."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from alert_rlvr.config import make_task
from alert_rlvr.environment import AlertEnvironment, API_SCHEMAS
from alert_rlvr.verifier import evaluate
from experiments.run_model_pilot import SYSTEM

spec = importlib.util.spec_from_file_location("main_batch_audit", BASE / "independent-audit-check.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(answer):
    return {
        "snapshot_id": answer["snapshot_id"],
        "incidents": sorted([(r["incident_id"], r["severity"], sorted(r["service_ids"]), r["excess_failed_requests"]) for r in answer["incidents"]]),
        "priority": answer["priority"],
    }


def main():
    frozen = helper.normalized_hashes(read(BASE / "frozen-task.json")["business_sha256"])
    truth = read(BASE / "independent-audit-evidence-20261025T113909690721Z/independent-truth.json")["17"]["answer"]
    batch = BASE / "score-order-diagnostic-run01"
    saved_summary = read(batch / "summary.json")
    supplement = [helper.inspect_run(p, frozen) for p in sorted(batch.glob("seed*-attempt*")) if p.is_dir()]
    expected = []
    for row in supplement:
        expected.append({
            "attempt": int(row["folder"][-2:]), "status": row["status"], "reward": row["reward"],
            "tool_calls": len(row["tool_calls"]), "truncated_responses": row["truncated_responses"], "protocol_errors": row["protocol_errors"],
        })
    recorded = [{key: r[key] for key in expected[0]} for r in saved_summary["runs"]]
    for row in supplement:
        row["exact_independent_business_answer"] = canonical(row["answer"]) == canonical(truth)
    gpt_checks = []
    for name in ("gpt-subagent-run01", "gpt-subagent-run02"):
        folder = BASE / name
        initial, saved_eval = read(folder / "input.json"), read(folder / "evaluation.json")
        answer_text = (folder / "final_answer.json").read_text(encoding="utf-8")
        checks = {
            "task_exact": initial["task"] == make_task(17),
            "system_exact": initial["system"] == SYSTEM,
            "tools_exact": initial["tools"] == API_SCHEMAS,
            "frozen_business_hashes_match": helper.normalized_hashes(saved_eval["task_code_sha256"]) == frozen,
            "saved_score_matches_replay": saved_eval["evaluation"] == evaluate(make_task(17), answer_text),
            "exact_independent_business_answer": canonical(json.loads(answer_text)) == canonical(truth),
        }
        calls = []
        with AlertEnvironment(17) as env:
            for request_file in sorted(folder.glob("request-*.json")):
                request = read(request_file)
                stored = read(folder / request_file.name.replace("request-", "call-"))
                calls.append({"file": request_file.name, "name": request["name"], "request_matches_bridge_log": stored["request"] == request, "result_matches_fresh_api": stored["result"] == env.call(request["name"], request["arguments"]), "ok": stored["result"]["ok"], "rows": len(stored["result"].get("data", []))})
        checks["all_tool_calls_match"] = all(c["request_matches_bridge_log"] and c["result_matches_fresh_api"] for c in calls)
        checks["call_count_matches_metadata"] = len(calls) == saved_eval["business_api_calls"]
        gpt_checks.append({"folder": name, "checks": checks, "calls": calls, "score": saved_eval["evaluation"], "scope": saved_eval["scope"]})
    result = {
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "Supplementary 4 + GPT 2; separate from main 24. No pooled performance statistic.",
        "supplement_plan": saved_summary["plan"],
        "supplement_runs": supplement,
        "supplement_summary_matches_reaggregation": expected == recorded,
        "observed_intermediate_scores": sum(0 < r["reward"] < 1 for r in supplement),
        "gpt_checks": gpt_checks,
    }
    output = BASE / ("independent-audit-supplement-evidence-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir()
    (output / "integrity.json").write_text(json.dumps(helper.json_safe(result), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "supplement_summary_matches": result["supplement_summary_matches_reaggregation"], "intermediate_scores": result["observed_intermediate_scores"], "supplement_integrity_failures": [r for r in supplement if any(v is False for v in r["checks"].values())], "gpt_integrity_failures": [r for r in gpt_checks if not all(r["checks"].values())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
