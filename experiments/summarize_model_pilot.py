"""Summarize the fixed three-seed pilot without changing task or reward rules."""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alert_rlvr.environment import AlertEnvironment
from alert_rlvr.verifier import evaluate, expected_answer
from examples.reference_agent import solve


def normalize(answer):
    return {
        "snapshot_id": answer["snapshot_id"],
        "incidents": sorted([
            {**row, "service_ids": sorted(row["service_ids"])}
            for row in answer["incidents"]
        ], key=lambda row: row["incident_id"]),
        "priority": answer["priority"],
    }


def main():
    base = ROOT / "artifacts/model-pilot-v2"
    output = base / "summary-run01.json"
    if output.exists():
        raise FileExistsError("Preserve the original summary; use a new run identifier.")
    current_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in sorted((ROOT / "alert_rlvr").glob("*.py"))}
    controls, runs = [], []
    for seed in (17, 42, 99):
        with AlertEnvironment(seed) as env:
            expected = expected_answer(env.task)
            reference = solve(env)
            assert normalize(reference) == normalize(expected)
            assert evaluate(env.task, reference)["reward"] == 1.0
            controls.append({"seed": seed, "answer": reference, "reward": 1.0,
                             "api_reference_matches_sql_oracle": True})
            for model in ("deepseek-flash", "qwen25-15b"):
                folder = base / f"{model}-seed{seed}-run01"
                metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
                assert metadata["task_code_sha256"] == current_hashes, "Task code changed during pilot"
                assert metadata["seed"] == seed and metadata["max_turns"] == 12
                assert metadata["max_output_tokens_per_turn"] == 1024
                entry = {"model": model, "seed": seed, "status": result["status"],
                         "reward": result["reward"], "tool_calls": result["tool_calls"],
                         "protocol_errors": result["protocol_errors"],
                         "truncated_responses": result["truncated_responses"],
                         "strict_correct": False, "correct_counts": 0, "correct_service_sets": 0,
                         "expected_incidents": len(expected["incidents"]),
                         "evidence": str(folder.relative_to(ROOT))}
                if (folder / "final_answer.json").exists():
                    answer = json.loads((folder / "final_answer.json").read_text(encoding="utf-8"))
                    grading = evaluate(env.task, answer)
                    assert grading == result["evaluation"]
                    if grading["valid"]:
                        rows = {row["incident_id"]: row for row in answer["incidents"]}
                        expected_ids = {row["incident_id"] for row in expected["incidents"]}
                        entry["strict_correct"] = normalize(answer) == normalize(expected)
                        entry["extra_incidents"] = sorted(rows.keys() - expected_ids)
                        entry["missing_incidents"] = sorted(expected_ids - rows.keys())
                        entry["priority_exact"] = answer["priority"] == expected["priority"]
                        entry["correct_counts"] = sum(
                            rows.get(row["incident_id"], {}).get("excess_failed_requests") == row["excess_failed_requests"]
                            for row in expected["incidents"])
                        entry["correct_service_sets"] = sum(
                            set(rows.get(row["incident_id"], {}).get("service_ids", [])) == set(row["service_ids"])
                            for row in expected["incidents"])
                runs.append(entry)
    with AlertEnvironment(17) as env:
        expected = expected_answer(env.task)
        zero_counts = copy.deepcopy(expected)
        for row in zero_counts["incidents"]:
            row["excess_failed_requests"] = 0
        extra_incident = copy.deepcopy(expected)
        extra_incident["incidents"].append({"incident_id": "INC-EXTRA", "severity": "P1",
                                             "service_ids": [], "excess_failed_requests": 1})
        score_controls = {"all_counts_wrong_other_fields_correct": evaluate(env.task, zero_counts),
                          "one_extra_incident_other_fields_correct": evaluate(env.task, extra_incident)}
    summary = {"scope": "Three fixed instances, one rollout each; not a stable pass-rate estimate.",
               "protocol": "text-json-single-action-v1; business API tools only; no code execution tool",
               "reference_controls": controls, "model_runs": runs,
               "reward_interpretation_controls": score_controls}
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runs": runs, "reward_controls": score_controls}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
