"""Targeted post-fix check. Preserve all pre-fix reports and evidence."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from audit import ROOT, independent_answer, make_task, verifier, write_json


def main():
    destination = Path(__file__).resolve().parent / ("post-fix-evidence-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    destination.mkdir()
    answer, _ = independent_answer(17)
    task = make_task(17)
    raw = json.dumps(answer, separators=(",", ":"))
    (destination / "current-task-seed-17.txt").write_text(task, encoding="utf-8")
    write_json(destination / "independent-answer-seed-17.json", answer)
    (destination / "source-hashes.json").write_text(json.dumps({
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ("alert_rlvr/config.py", "alert_rlvr/verifier.py", "docs/CONTRACT.md")
    }, indent=2) + "\n", encoding="utf-8")
    outcomes = []

    def check(name, value, expected_reward, expected_valid, description):
        report = verifier.evaluate(task, value)
        reward = verifier.compute_reward(task, value)
        outcomes.append({"name": name, "description": description,
                         "answer": value if len(str(value)) < 2000 else "See construction in post_fix_probe.py; exact byte length recorded below.",
                         "json_bytes": len(value.encode("utf-8")) if isinstance(value, str) else None,
                         "expected_reward": expected_reward, "expected_valid": expected_valid,
                         "report": report, "compute_reward": reward,
                         "pass": reward == expected_reward and report["valid"] == expected_valid})

    check("correct_integer_json", raw, 1.0, True, "Independent seed 17 business answer")
    for suffix in (".0", "e0", ".00000000000000000000000000000000000000"):
        changed = re.sub(r'("excess_failed_requests":)(\d+)', lambda m: m.group(1) + m.group(2) + suffix, raw)
        check("integer_value_suffix_" + suffix, changed, 1.0, True, "All three counts preserve exact integer value")
    shifted = re.sub(r'("excess_failed_requests":)(\d+)', lambda m: m.group(1) + str(int(m.group(2)) * 10) + "e-1", raw)
    check("integer_value_shifted_exponent", shifted, 1.0, True, "480e-1, 1740e-1, 1200e-1 preserve exact values")
    float_dict = copy.deepcopy(answer)
    for row in float_dict["incidents"]:
        row["excess_failed_requests"] = float(row["excess_failed_requests"])
    check("integer_valued_float_dict", float_dict, 1.0, True, "Finite integer-valued Python floats round-trip through JSON")

    for token in ("48.00000000000000000000000000000000000001",
                  "47.99999999999999999999999999999999999999",
                  "1e-10000", "48.5", "true", '"48"', "NaN", "Infinity"):
        changed = raw.replace('"excess_failed_requests":48', '"excess_failed_requests":' + token, 1)
        check("reject_" + token, changed, 0.0, False, "First count is a noninteger or explicitly unsupported type/constant")

    at_limit = raw + " " * (1000000 - len(raw.encode("utf-8")))
    check("byte_limit_exact", at_limit, 1.0, True, "Exactly 1,000,000 UTF-8 bytes including trailing spaces")
    check("byte_limit_plus_one", at_limit + " ", 0.0, False, "1,000,001 UTF-8 bytes; now explicitly prohibited in task")
    contract = (ROOT / "docs/CONTRACT.md").read_text(encoding="utf-8")
    disclosure = {"task_discloses_limit": "1000000 字节（包含空白字符）" in task,
                  "task_discloses_zero_reward": "超过时按输入超限处理并得 0" in task,
                  "task_discloses_numeric_equivalence": "48、48.0、48e0" in task,
                  "contract_discloses_limit": "1,000,000 字节，包含空白字符" in contract,
                  "contract_discloses_exact_decimal": "JSON 小数采用精确十进制解析" in contract}
    write_json(destination / "targeted-results.json", {"disclosure": disclosure, "cases": outcomes,
               "all_pass": all(disclosure.values()) and all(row["pass"] for row in outcomes)})
    print(json.dumps({"evidence_directory": str(destination), "cases": len(outcomes),
                      "disclosure": disclosure, "failures": [r for r in outcomes if not r["pass"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
