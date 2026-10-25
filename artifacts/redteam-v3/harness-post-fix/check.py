"""Targeted raw-answer transport regression; no model/network invocation."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from alert_rlvr.config import make_task, snapshot_id
from alert_rlvr.verifier import evaluate
from experiments.run_model_pilot import raw_answer_json

answer = {"snapshot_id": snapshot_id(17), "incidents": [
    {"incident_id": "INC-AUTH", "severity": "P1", "service_ids": ["svc-auth"], "excess_failed_requests": 48},
    {"incident_id": "INC-DB", "severity": "P0", "service_ids": ["svc-checkout", "svc-search"], "excess_failed_requests": 174},
    {"incident_id": "INC-PAY", "severity": "P1", "service_ids": ["svc-pay"], "excess_failed_requests": 120},
], "priority": ["INC-DB", "INC-PAY"]}
base = json.dumps(answer)
checks = []
for number, wanted in (("48", 1.0), ("48.0", 1.0), ("48e0", 1.0), ("48.000000000000000001", 0.0)):
    raw = base.replace('"excess_failed_requests": 48', '"excess_failed_requests": ' + number, 1)
    for fenced in (False, True):
        envelope = '{"answer":' + raw + ',"action":"final"}'
        if fenced:
            envelope = "```json\n" + envelope + "\n```"
        extracted = raw_answer_json(envelope)
        assert extracted == raw
        grading = evaluate(make_task(17), extracted)
        assert grading["reward"] == wanted, (number, grading)
        checks.append({"number": number, "fenced": fenced, "reward": grading["reward"], "raw_preserved": True})
print(json.dumps({"passed": len(checks), "checks": checks}, indent=2))
