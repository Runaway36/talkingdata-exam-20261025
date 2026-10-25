"""Run correct, partially wrong, and empty submissions against the verifier."""
import argparse
import copy
import json
from pathlib import Path

from alert_rlvr.config import DEFAULT_SEED
from alert_rlvr.environment import AlertEnvironment
from alert_rlvr.verifier import evaluate
from .reference_agent import solve


def run_demo(seed=DEFAULT_SEED):
    with AlertEnvironment(seed=seed) as env:
        trace = []
        correct = solve(env, trace)
        wrong = copy.deepcopy(correct)
        if wrong["incidents"]:
            wrong["incidents"][0]["excess_failed_requests"] += 1
        if len(wrong["priority"]) > 1:
            wrong["priority"].reverse()
        empty = {"snapshot_id": env.snapshot_id, "incidents": [], "priority": []}
        scenarios = [{"name": name, "answer": answer, "evaluation": evaluate(env.task, answer)}
                     for name, answer in (("correct", correct), ("wrong_count_and_priority", wrong),
                                          ("empty", empty))]
        if scenarios[0]["evaluation"]["reward"] != 1.0:
            raise RuntimeError("Independent verifier rejected the API-only reference result")
        if not (scenarios[1]["evaluation"]["reward"] < 1.0 and scenarios[2]["evaluation"]["reward"] == 0.0):
            raise RuntimeError("Negative controls were not rejected as expected")
        return {"task": env.task, "snapshot_id": env.snapshot_id, "api_calls": trace,
                "scenarios": scenarios,
                "scope": "Deterministic integration demo; not a model success-rate or difficulty measurement."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, help="Optional new JSON report file; refuses to overwrite")
    args = parser.parse_args(argv)
    try:
        report = run_demo(args.seed)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered + "\n")
        print(rendered)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"Demo failed: {error}\n")


if __name__ == "__main__":
    main()
