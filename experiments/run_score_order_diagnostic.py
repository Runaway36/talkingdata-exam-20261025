"""Four predeclared real-model samples; separate from the frozen pass@4 batch."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "artifacts/model-eval-final/score-order-diagnostic-run01"
    output.mkdir(exist_ok=False)
    plan = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Seek naturally occurring intermediate scores to inspect task-level ordering; no guarantee they occur.",
        "instance_seed": 17, "attempts": 4, "backend": "deepseek-flash",
        "thinking": "enabled", "reasoning_effort": "provider_default_high",
        "requested_temperature": 0.7, "effective_temperature": "ignored_in_thinking_mode",
        "top_p": 1.0, "max_turns": 12, "max_tokens_per_turn": 4096,
        "parallel_episodes": 2,
        "scope": "Supplementary condition, not pooled with non-thinking 1024-token pass@4. No grading feedback or retries for wrong answers.",
        "official_parameter_reference": "https://api-docs.deepseek.com/guides/thinking_mode/",
        "task_code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted((ROOT / "alert_rlvr").glob("*.py"))},
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    def run(attempt):
        folder = output / f"seed17-attempt{attempt:02d}"
        command = [sys.executable, "-X", "utf8", str(ROOT / "experiments/run_model_pilot.py"),
                   "--backend", "deepseek", "--thinking", "enabled", "--seed", "17",
                   "--temperature", "0.7", "--max-turns", "12", "--max-tokens", "4096",
                   "--output", str(folder)]
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=900)
        (output / f"attempt{attempt:02d}.stdout.txt").write_text(process.stdout, encoding="utf-8")
        (output / f"attempt{attempt:02d}.stderr.txt").write_text(process.stderr, encoding="utf-8")
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["task_code_sha256"] == plan["task_code_sha256"]
        row = {"attempt": attempt, "status": result["status"], "reward": result["reward"],
               "tool_calls": result["tool_calls"], "truncated_responses": result["truncated_responses"],
               "protocol_errors": result["protocol_errors"], "exit_code": process.returncode,
               "folder": str(folder.relative_to(ROOT))}
        print(json.dumps(row), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(run, range(1, 5)))
    report = {"plan": plan, "finished_at": datetime.now(timezone.utc).isoformat(), "runs": runs,
              "intermediate_score_count": sum(r["reward"] is not None and 0 < r["reward"] < 1 for r in runs),
              "infrastructure_errors": sum(r["status"] == "execution_error" for r in runs)}
    (output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
