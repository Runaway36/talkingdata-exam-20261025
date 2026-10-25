"""Reproducible local acceptance runner; writes a new result directory per run."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = args.output or root / "artifacts" / f"validation-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    commands = [
        ("unit-tests", [sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests", "-v"]),
        ("demo-17", [sys.executable, "-X", "utf8", "-m", "examples.demo", "--seed", "17"]),
        ("demo-42", [sys.executable, "-X", "utf8", "-m", "examples.demo", "--seed", "42"]),
        ("demo-99", [sys.executable, "-X", "utf8", "-m", "examples.demo", "--seed", "99"]),
        ("harness", [sys.executable, "-X", "utf8", "-m", "examples.harness_integration"]),
    ]
    results = []
    for name, command in commands:
        try:
            run = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                 encoding="utf-8", timeout=120)
            code, stdout, stderr = run.returncode, run.stdout, run.stderr
        except subprocess.TimeoutExpired as error:
            code, stdout, stderr = -1, "", f"Timed out: {error}"
        (out / f"{name}.stdout.txt").write_text(stdout, encoding="utf-8")
        (out / f"{name}.stderr.txt").write_text(stderr, encoding="utf-8")
        item = {"name": name, "exit_code": code}
        if name != "unit-tests" and code == 0:
            report = json.loads(stdout)
            (out / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if name.startswith("demo"):
                item["rewards"] = {s["name"]: s["evaluation"]["reward"] for s in report["scenarios"]}
                item["api_call_count"] = len(report["api_calls"])
            else:
                item["reward"] = report["evaluation"]["reward"]
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    summary = {"started_at_utc": stamp, "python": platform.python_version(),
               "platform": platform.platform(), "results": results,
               "all_passed": all(r["exit_code"] == 0 for r in results),
               "scope": "Programmatic acceptance only; no real-model difficulty/training measurement."}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evidence: {out}")
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
