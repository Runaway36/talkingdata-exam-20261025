"""Four independent attempts per fixed instance; no feedback across attempts."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alert_rlvr.config import TASK_VERSION, make_task
from alert_rlvr.verifier import evaluate, expected_answer


def diagnostic_json(value):
    """Keep exact decimal text in diagnostic displays, including huge exponents."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: diagnostic_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [diagnostic_json(item) for item in value]
    return value


def inspect_attempt(folder, seed):
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    record = {"folder": str(folder.relative_to(ROOT)), "instance_seed": seed,
              "status": result["status"], "reward": result["reward"],
              "sampling_seed": metadata.get("sampling_seed"),
              "temperature": metadata["temperature"], "passed": False,
              "tool_calls": result["tool_calls"], "protocol_errors": result["protocol_errors"],
              "truncated_responses": result["truncated_responses"],
              "elapsed_seconds": result["elapsed_seconds"], "events": [],
              "extra_incidents": [], "priority_expected": None, "priority_actual": None}
    if result["status"] == "execution_error":
        record["passed"] = None
        return record
    expected = expected_answer(make_task(seed))
    record["priority_expected"] = expected["priority"]
    answer_file = folder / "final_answer.json"
    if not answer_file.exists():
        return record
    answer_json = answer_file.read_text(encoding="utf-8")
    grading = evaluate(make_task(seed), answer_json)
    assert grading == result["evaluation"], "Saved grading differs from current frozen rules"
    record["passed"] = grading["valid"] and grading["reward"] == 1.0
    if not grading["valid"]:
        record["format_errors"] = grading["errors"]
        return record
    # Parse only after validation, retaining precision during comparisons. Decimal
    # values become strings only in diagnostic output, never before grading.
    answer = json.loads(answer_json, parse_float=Decimal)
    record["decimal_display"] = "Exact decimal strings in diagnostics; original JSON retained in final_answer.json"
    actual = {row["incident_id"]: row for row in answer["incidents"]}
    record["extra_incidents"] = sorted(actual.keys() - {row["incident_id"] for row in expected["incidents"]})
    record["priority_actual"] = answer["priority"]
    for row in expected["incidents"]:
        received = actual.get(row["incident_id"])
        checks = {
            "severity_correct": bool(received and received["severity"] == row["severity"]),
            "services_correct": bool(received and set(received["service_ids"]) == set(row["service_ids"])),
            "count_correct": bool(received and received["excess_failed_requests"] == row["excess_failed_requests"]),
        }
        record["events"].append({"incident_id": row["incident_id"], "missing": received is None,
                                 "expected": row, "actual": diagnostic_json(received),
                                 **checks, "complete_correct": all(checks.values())})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("deepseek", "qwen"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-python")
    parser.add_argument("--model-path")
    args = parser.parse_args()
    if TASK_VERSION != 3:
        raise RuntimeError("This frozen evaluation batch requires task v3")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runs = []
    report = {"task_version": TASK_VERSION, "backend": args.backend, "instances": [17, 42, 99],
              "attempts_per_instance": 4, "temperature": 0.7,
              "thinking": "disabled" if args.backend == "deepseek" else "not_applicable",
              "max_turns": 12, "max_output_tokens_per_turn": 1024,
              "started_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Three fixed instances, four independent attempts each; not population performance.",
              "complete": False, "runs": runs}
    report["task_code_sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "alert_rlvr").glob("*.py"))}
    report["evaluation_code_sha256"] = {
        name: hashlib.sha256((ROOT / "experiments" / name).read_bytes()).hexdigest()
        for name in ("run_model_pilot.py", "local_qwen_driver.py", "run_repeated_evaluation.py")}
    try:
        for seed in report["instances"]:
            for attempt in range(1, 5):
                folder = output / f"seed{seed}-attempt{attempt:02d}"
                # Disjoint RNG-seed blocks across both instances and attempts;
                # each attempt uses at most 12 consecutive per-turn seeds.
                sampling_seed = 20261025 + seed * 10000 + attempt * 100
                command = [sys.executable, "-X", "utf8", str(ROOT / "experiments/run_model_pilot.py"),
                           "--backend", args.backend, "--seed", str(seed), "--temperature", "0.7",
                           "--sampling-seed", str(sampling_seed), "--max-turns", "12", "--max-tokens", "1024",
                           "--output", str(folder)]
                if args.backend == "qwen":
                    if not args.local_python or not args.model_path:
                        raise ValueError("Qwen requires --local-python and --model-path")
                    command += ["--local-python", args.local_python, "--model-path", args.model_path, "--device", "cuda"]
                run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=900)
                (output / f"seed{seed}-attempt{attempt:02d}.stdout.txt").write_text(run.stdout, encoding="utf-8")
                (output / f"seed{seed}-attempt{attempt:02d}.stderr.txt").write_text(run.stderr, encoding="utf-8")
                if not (folder / "result.json").exists():
                    raise RuntimeError("Attempt produced no result artifact")
                record = inspect_attempt(folder, seed)
                metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                assert metadata["task_code_sha256"] == report["task_code_sha256"], "Task changed during batch"
                record["attempt"] = attempt
                runs.append(record)
                print(json.dumps({key: record[key] for key in (
                    "instance_seed", "attempt", "status", "reward", "passed", "tool_calls")}), flush=True)
                if run.returncode or record["status"] == "execution_error":
                    raise RuntimeError("Infrastructure failure; batch paused without treating it as a business error")
        grouped = []
        for seed in report["instances"]:
            attempts = [row for row in runs if row["instance_seed"] == seed]
            correct = sum(row["passed"] for row in attempts)
            grouped.append({"instance_seed": seed, "attempts": 4, "correct": correct,
                            "pass_at_1": correct / 4, "pass_at_4": int(correct > 0)})
        report.update(complete=True, by_instance=grouped,
                      pass_at_1=sum(row["pass_at_1"] for row in grouped) / 3,
                      pass_at_4=sum(row["pass_at_4"] for row in grouped) / 3,
                      mean_reward=sum(row["reward"] or 0 for row in runs) / len(runs))
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print("Evidence: " + str(output), flush=True)


if __name__ == "__main__":
    main()
