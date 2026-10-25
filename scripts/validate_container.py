"""Build and validate the self-contained Docker delivery; preserve each run."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "artifacts" / ("container-validation-" + stamp)
    output.mkdir(parents=True, exist_ok=False)
    image = "talkingdata-alert-rlvr:exam-v3"
    records = []

    def run(name, command):
        process = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"},
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        (output / (name + ".stdout.txt")).write_text(process.stdout, encoding="utf-8")
        (output / (name + ".stderr.txt")).write_text(process.stderr, encoding="utf-8")
        records.append({"name": name, "command": command, "exit_code": process.returncode})
        print(json.dumps(records[-1]), flush=True)
        if process.returncode:
            raise RuntimeError(name + " failed; inspect preserved logs")
        return process

    summary = {"image": image, "steps": records, "success": False}
    try:
        run("build", ["docker", "build", "--progress=plain", "-t", image, "."])
        base = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "256m",
                "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=16m"]
        demo = json.loads(run("default", base + [image]).stdout)
        rewards = {row["name"]: row["evaluation"]["reward"] for row in demo["scenarios"]}
        assert rewards == {"correct": 1.0, "wrong_count_and_priority": 0.4, "empty": 0.0}, rewards
        tests = run("tests", base + [image, "python", "-m", "unittest", "discover", "-s", "tests", "-v"])
        count = re.search(r"Ran (\d+) tests?", tests.stderr + tests.stdout)
        assert count, "No completed test-count marker"
        mount = "type=bind,source=" + str(ROOT / "examples") + ",target=/workspace,readonly"
        mounted = json.loads(run("mounted-controller", base + ["--mount", mount, image,
                                                              "python", "/workspace/mounted_controller.py"]).stdout)
        assert mounted["reward"] == 1.0, mounted
        summary.update(success=True, default_rewards=rewards, test_count=int(count.group(1)),
                       mounted_controller=mounted, snapshot_id=demo["snapshot_id"])
    except Exception as error:
        summary["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Evidence: " + str(output), flush=True)


if __name__ == "__main__":
    main()
