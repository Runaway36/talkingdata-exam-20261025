"""Read-only replay/audit of saved final evaluation runs; writes only new audit evidence.

No model calls. No changes to task, dataset, scoring, or model-run artifacts.
"""
import copy
import datetime as dt
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from alert_rlvr.config import make_task
from alert_rlvr.environment import AlertEnvironment, API_SCHEMAS
from alert_rlvr.verifier import evaluate
from experiments.run_model_pilot import SYSTEM

BASE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_hashes(value):
    return {key.replace("\\", "/"): digest for key, digest in value.items()}


def inspect_run(folder, frozen):
    result, metadata = read(folder / "result.json"), read(folder / "metadata.json")
    seed = metadata["seed"]
    initial = read(folder / "initial_input.json")
    checks = {
        "frozen_business_hashes_match": normalized_hashes(metadata["task_code_sha256"]) == frozen,
        "task_text_exact": initial[1] == {"role": "user", "content": make_task(seed)},
        "system_and_schemas_exact": initial[0] == {"role": "system", "content": SYSTEM + "\n工具定义：\n" + json.dumps(API_SCHEMAS, ensure_ascii=False)},
        "request_history_unmodified": True,
        "tool_results_match_fresh_api": True,
        "raw_final_answer_preserved": None,
        "saved_score_matches_replay": None,
    }
    expected_messages = initial
    tool_calls = []
    with AlertEnvironment(seed) as env:
        for response_path in sorted(folder.glob("turn-*-response.json")):
            prefix = response_path.name[:-len("response.json")]
            request = read(folder / (prefix + "request.json"))
            checks["request_history_unmodified"] &= request["messages"] == expected_messages
            response = read(response_path)
            content = response["content"]
            expected_messages = expected_messages + [{"role": "assistant", "content": content}]
            tool_path = folder / (prefix + "tool.json")
            if tool_path.exists():
                tool = read(tool_path)
                replay = env.call(tool["name"], tool["arguments"])
                checks["tool_results_match_fresh_api"] &= replay == tool["result"]
                expected_messages.append({"role": "user", "content": "工具返回：" + json.dumps(tool["result"], ensure_ascii=False)})
                tool_calls.append({"name": tool["name"], "ok": tool["result"]["ok"], "rows": len(tool["result"].get("data", []))})
            else:
                answer_path = folder / "final_answer.json"
                if answer_path.exists() and response_path == sorted(folder.glob("turn-*-response.json"))[-1]:
                    original_answer = answer_path.read_text(encoding="utf-8")
                    checks["raw_final_answer_preserved"] = original_answer in content
                    checks["saved_score_matches_replay"] = evaluate(make_task(seed), original_answer) == read(folder / "evaluation.json") == result["evaluation"]
                else:
                    expected_messages.append({"role": "user", "content": "协议错误。请只输出一个完整 JSON：action=call 时包含 name 和 arguments；action=final 时包含 answer。"})
    row = {
        "folder": str(folder.relative_to(BASE)), "seed": seed,
        "status": result["status"], "reward": result["reward"],
        "tool_calls": tool_calls, "turns": result["turns"],
        "protocol_errors": result["protocol_errors"],
        "truncated_responses": result["truncated_responses"],
        "checks": checks,
    }
    if (folder / "final_answer.json").exists():
        row["answer"] = json.loads((folder / "final_answer.json").read_text(encoding="utf-8"), parse_float=Decimal)
    return row


def json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def main():
    frozen = normalized_hashes(read(BASE / "frozen-task.json")["business_sha256"])
    current = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in frozen}
    snapshot = {"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), "business_still_frozen": current == frozen, "source_sha256": current, "runs": [], "batches": {}}
    for backend in ("deepseek-flash-run01", "qwen25-15b-run01"):
        batch = BASE / backend
        for folder in sorted(batch.glob("seed*-attempt*")):
            if folder.is_dir() and (folder / "result.json").exists():
                snapshot["runs"].append(inspect_run(folder, frozen))
        runs = [r for r in snapshot["runs"] if r["folder"].startswith(backend + "\\") or r["folder"].startswith(backend + "/")]
        info = {"completed_artifacts": len(runs), "expected_attempts": 12, "status_counts": {status: sum(r["status"] == status for r in runs) for status in {r["status"] for r in runs}}}
        summary_path = batch / "summary.json"
        if summary_path.exists():
            summary = read(summary_path)
            info["saved_complete"] = summary["complete"]
            if summary["complete"]:
                by_instance = []
                for seed in (17, 42, 99):
                    group = [r for r in runs if r["seed"] == seed]
                    correct = sum(r["reward"] == 1.0 and r["status"] == "completed" for r in group)
                    by_instance.append({"instance_seed": seed, "attempts": len(group), "correct": correct, "pass_at_1": correct / len(group), "pass_at_4": int(correct > 0)})
                recomputed = {"by_instance": by_instance, "pass_at_1": sum(r["pass_at_1"] for r in by_instance) / 3, "pass_at_4": sum(r["pass_at_4"] for r in by_instance) / 3, "mean_reward": sum(r["reward"] or 0 for r in runs) / len(runs)}
                info["independent_reaggregation"] = recomputed
                info["summary_matches_reaggregation"] = all(summary[k] == value for k, value in recomputed.items())
                info["evaluation_source_hashes_match"] = all(hashlib.sha256((ROOT / "experiments" / name).read_bytes()).hexdigest() == digest for name, digest in summary["evaluation_code_sha256"].items())
        snapshot["batches"][backend] = info
    # Reuse the independent API/Python-integer audit method, not a scorer oracle.
    helper = ROOT / "artifacts/redteam-v3/false-positive/audit.py"
    spec = importlib.util.spec_from_file_location("independent_business_rules", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    truth = {}
    for seed in (17, 42, 99):
        answer, api_data, ledger = module.independent_answer(seed)
        truth[str(seed)] = {"answer": answer, "api_data": api_data, "ledger": ledger}
    gpt = BASE / "gpt-subagent-run01"
    if (gpt / "evaluation.json").exists():
        scoring = read(gpt / "evaluation.json")
        actual = (gpt / "final_answer.json").read_text(encoding="utf-8")
        gpt_tools = []
        with AlertEnvironment(17) as env:
            for request in sorted(gpt.glob("request-*.json")):
                data = read(request)
                saved = read(gpt / request.name.replace("request-", "call-"))
                # Preserve raw structures for a human check if conventions vary.
                gpt_tools.append({"request": data, "saved_response": saved})
        snapshot["gpt_single"] = {"score_recomputed": evaluate(make_task(17), actual), "saved_score": scoring["evaluation"], "answer": json.loads(actual), "calls": gpt_tools, "scope": scoring["scope"]}
    # Author-created illustrations. They never enter model aggregation.
    a = copy.deepcopy(truth["17"]["answer"])
    for row in a["incidents"]:
        if row["incident_id"] == "INC-AUTH":
            row["excess_failed_requests"] = 0
    b = copy.deepcopy(a)
    b["priority"].reverse()
    controls = {"provenance": "Author-constructed examples, NOT real model output; excluded from all model statistics.", "task": make_task(17), "examples": [
        {"name": "wrong_AUTH_only", "answer": a, "report": evaluate(make_task(17), json.dumps(a))},
        {"name": "same_wrong_AUTH_plus_reversed_priority", "answer": b, "report": evaluate(make_task(17), json.dumps(b))},
    ]}
    output = BASE / ("independent-audit-evidence-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir()
    for name, data in (("run-integrity.json", snapshot), ("independent-truth.json", truth), ("controlled-scoring-examples.json", controls)):
        (output / name).write_text(json.dumps(json_safe(data), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "business_still_frozen": snapshot["business_still_frozen"], "batches": snapshot["batches"], "integrity_failure_rows": [r for r in snapshot["runs"] if any(value is False for value in r["checks"].values())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
