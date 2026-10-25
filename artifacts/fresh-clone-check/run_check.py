"""Independent checkout and offline-container delivery validation."""
import datetime
import json
import pathlib
import re
import subprocess
import sys
import time

EXPECTED_SHA = "4a23820622cbfa662ca6a55a72bc8a03f0d54025"
REMOTE = "git@github.com:Runaway36/talkingdata-exam-20261025.git"
IMAGE = "talkingdata-alert-rlvr:fresh-clone-v2"
EVIDENCE = pathlib.Path(__file__).resolve().parent
CLONE = pathlib.Path(r"C:\Users\runaway\Desktop\实习\99-临时材料\talkingdata-fresh-clone-20261025")
REPORT_PATH = EVIDENCE / "result.json"
if REPORT_PATH.exists() or CLONE.exists():
    raise SystemExit("Refusing to overwrite an existing result or clone")

report = {
    "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "expected_sha": EXPECTED_SHA,
    "remote": REMOTE,
    "clone_path": str(CLONE),
    "build_context": str(CLONE),
    "image": IMAGE,
    "command_timeout_seconds": 120,
    "steps": [],
    "success": False,
}


def save():
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(name, args, cwd=None):
    started = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120)
        output, error, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = exc.stdout or ""
        error = exc.stderr or ""
        output = output.decode("utf-8", "replace") if isinstance(output, bytes) else output
        error = error.decode("utf-8", "replace") if isinstance(error, bytes) else error
        code = 124
    stdout_path = EVIDENCE / (name + ".stdout.txt")
    stderr_path = EVIDENCE / (name + ".stderr.txt")
    stdout_path.write_text(output, encoding="utf-8")
    stderr_path.write_text(error, encoding="utf-8")
    step = {"name": name, "argv": args, "cwd": str(cwd) if cwd else None,
            "exit_code": code, "timed_out": timed_out,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout_file": stdout_path.name, "stderr_file": stderr_path.name}
    report["steps"].append(step)
    save()
    print(name, "exit", code, flush=True)
    return code, output, error


def checked(name, args, cwd=None):
    code, output, error = run(name, args, cwd)
    if code:
        raise RuntimeError(name + " failed; inspect captured logs")
    return output, error


try:
    ssh_options = "ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes"
    checked("01-clone", ["git", "-c", "core.sshCommand=" + ssh_options,
                          "clone", "--single-branch", "--branch", "main", REMOTE, str(CLONE)])
    output, _ = checked("02-head", ["git", "rev-parse", "HEAD"], CLONE)
    report["cloned_sha"] = output.strip()
    assert report["cloned_sha"] == EXPECTED_SHA, "Unexpected cloned commit"
    output, _ = checked("03-branch", ["git", "branch", "--show-current"], CLONE)
    report["cloned_branch"] = output.strip()
    assert report["cloned_branch"] == "main"
    output, _ = checked("04-clean-before", ["git", "status", "--porcelain"], CLONE)
    assert not output.strip(), "Clone has unexpected modified/untracked files"
    report["clean_before"] = True
    output, _ = checked("05-repository", ["gh", "repo", "view",
        "Runaway36/talkingdata-exam-20261025", "--json", "url,isPrivate,defaultBranchRef,createdAt"])
    report["github_repository"] = json.loads(output)
    assert report["github_repository"]["isPrivate"] is False
    assert report["github_repository"]["defaultBranchRef"]["name"] == "main"
    output, _ = checked("06-api-head", ["gh", "api",
        "repos/Runaway36/talkingdata-exam-20261025/commits/main", "--jq", ".sha"])
    report["github_api_head"] = output.strip()
    assert report["github_api_head"] == EXPECTED_SHA
    build_cmd = ["docker", "build", "--tag", IMAGE, str(CLONE)]
    code, output, error = run("07-build", build_cmd)
    if code and any(marker in (output + error).lower() for marker in (
            "timeout", "connection reset", "connection refused", "temporary failure", "tls handshake")):
        time.sleep(2)
        code, output, error = run("07-build-network-retry", build_cmd)
    assert code == 0, "Fresh-clone build failed"
    output, _ = checked("08-image-config", ["docker", "image", "inspect", IMAGE,
        "--format", "{{json .Config}}"])
    report["image_config"] = json.loads(output)
    assert report["image_config"].get("User") not in (None, "", "0", "root")
    output, _ = checked("09-container-uid", ["docker", "run", "--rm", "--network", "none", IMAGE, "id", "-u"])
    report["container_uid"] = output.strip()
    assert report["container_uid"].isdigit() and int(report["container_uid"]) != 0
    output, _ = checked("10-default-cmd", ["docker", "run", "--rm", "--network", "none", IMAGE])
    demo = json.loads(output)
    rewards = []
    def collect(value, path="root"):
        if isinstance(value, dict):
            if "reward" in value:
                rewards.append({"path": path, "reward": value["reward"]})
            for key, child in value.items():
                collect(child, path + "." + str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, path + "[" + str(index) + "]")
    collect(demo)
    report["default_cmd_rewards"] = rewards
    assert rewards and any(row["reward"] == 1 for row in rewards), "No correct-answer reward"
    assert any(row["reward"] == 0 for row in rewards), "No zero-reward control"
    output, error = checked("11-unittest", ["docker", "run", "--rm", "--network", "none", IMAGE,
        "python", "-m", "unittest", "discover", "-s", "tests", "-v"])
    match = re.search(r"Ran (\d+) tests?", output + error)
    assert match, "Missing unittest completion count"
    report["test_count"] = int(match.group(1))
    assert report["test_count"] == 41, "Unexpected test count"
    output, _ = checked("12-clean-after", ["git", "status", "--porcelain"], CLONE)
    assert not output.strip(), "Fresh clone was modified during validation"
    report["clean_after"] = True
    report["success"] = True
except Exception as exc:
    report["error"] = str(exc)
finally:
    report["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
    print(json.dumps(report, ensure_ascii=False, indent=2))

sys.exit(0 if report["success"] else 1)
