"""Auditable business-tool bridge for one fresh-context sub-agent solve.

This is a protocol restriction, not a filesystem security sandbox. The solver
is instructed to read only its input and API outputs, never this implementation.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alert_rlvr.environment import AlertEnvironment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    folder = args.folder.resolve()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    calls = sorted(folder.glob("call-*.json"))
    if len(calls) >= 11:
        raise RuntimeError("Eleven API calls used; reserve the twelfth action for the final answer")
    if set(request) != {"name", "arguments"}:
        raise ValueError("Request requires name and arguments")
    with AlertEnvironment(seed=17) as env:
        result = env.call(request["name"], request["arguments"])
    record = {"at": datetime.now(timezone.utc).isoformat(), "request": request, "result": result}
    with (folder / f"call-{len(calls)+1:02d}.json").open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
