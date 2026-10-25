"""Bounded follow-up for Decimal final-answer parsing; no old artifacts changed."""
import copy
import datetime as dt
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from alert_rlvr import config, verifier

HERE = Path(__file__).resolve().parent
GOLD_SOURCE = HERE / "run-20261025T110928510662Z" / "seed-17-independent-truth.json"


def main():
    # Independent API + Python-integer truth from the prior audit is unchanged.
    gold = json.loads(GOLD_SOURCE.read_text(encoding="utf-8"))["answer"]
    raw = json.dumps(gold)
    old = '"excess_failed_requests": 48'
    assert old in raw and gold["incidents"][0]["incident_id"] == "INC-AUTH"
    cases = []

    def add_token(label, token, valid, reward):
        answer = raw.replace(old, '"excess_failed_requests": ' + token, 1)
        cases.append((label, "raw_json", answer, token, valid, reward))

    for token in ("48", "48.0", "48.000000000000000000000000000", "48e0", "48E+0", "4.8e1", "480e-1", "0.48e2", "4.800e+1", "48e-0"):
        add_token("equivalent_" + token, token, True, 1.0)
    for depth in (1, 2, 6, 15, 16, 17, 18, 28, 29, 50, 100, 1000, 10000):
        # Exact independent lexical constructions: 48 + 10^-depth and 48 - 10^-depth.
        add_token(f"above_48_decimal_{depth}", "48." + "0" * (depth - 1) + "1", False, 0.0)
        add_token(f"below_48_decimal_{depth}", "47." + "9" * depth, False, 0.0)
        add_token(f"above_48_exponent_{depth}", "48" + "0" * (depth - 1) + "1e-" + str(depth), False, 0.0)
        add_token(f"equal_48_scaled_exponent_{depth}", "48" + "0" * depth + "e-" + str(depth), True, 1.0)
        add_token(f"positive_tiny_fraction_{depth}", "1e-" + str(depth), False, 0.0)
    for token in ("NaN", "Infinity", "-Infinity", "sNaN", "nan", "inf", "true", "false", "null", '"48"', "-48", "-48.0", "48.5", "4.81e1", "48.000000000000000001", "47.999999999999999999", "1e-999999", "1e-999999999999999999", "1e9999999999999999999", "1e-9999999999999999999", "00", "+48", "048", "48.", ".48e2", "48e", "0x30"):
        add_token("reject_" + token, token, False, 0.0)
    # Finite decimal integers are valid but numerically wrong; they lose AUTH's unit.
    for token in ("0", "0.0", "-0", "-0.0", "0e999999", "49", "47.0", "1e999", "1e999999", "1e999999999999999999"):
        add_token("wrong_integer_" + token, token, True, 0.8)
    for label, value, valid, reward in (
        ("int", 48, True, 1.0),
        ("integer_float", 48.0, True, 1.0),
        ("nextafter_up", math.nextafter(48.0, math.inf), False, 0.0),
        ("nextafter_down", math.nextafter(48.0, -math.inf), False, 0.0),
        ("bool_true", True, False, 0.0),
        ("bool_false", False, False, 0.0),
        ("nan", float("nan"), False, 0.0),
        ("positive_infinity", float("inf"), False, 0.0),
        ("negative_infinity", -float("inf"), False, 0.0),
        ("string", "48", False, 0.0),
        ("Decimal_not_standard_json_serializable", Decimal("48.0"), False, 0.0),
    ):
        answer = copy.deepcopy(gold)
        answer["incidents"][0]["excess_failed_requests"] = value
        cases.append(("dict_" + label, "dict", answer, repr(value), valid, reward))
    all_scientific = raw
    for value in (48, 174, 120):
        all_scientific = all_scientific.replace('"excess_failed_requests": ' + str(value), '"excess_failed_requests": ' + str(value) + "000e-3")
    cases.append(("all_three_scientific", "raw_json", all_scientific, "all event counts equivalent", True, 1.0))
    # Duplicate keys remain invalid even when their numeric spellings agree.
    duplicate = raw.replace(old, old + ', "excess_failed_requests": 48.0', 1)
    cases.append(("duplicate_numeric_key", "raw_json", duplicate, "48 and 48.0", False, 0.0))
    result = []
    failures = []
    for label, mode, answer, representation, wanted_valid, wanted_reward in cases:
        try:
            report = verifier.evaluate(config.make_task(17), answer)
            ok = report["valid"] == wanted_valid and report["reward"] == wanted_reward
        except Exception as exc:
            report = {"uncaught_exception": repr(exc)}
            ok = False
        row = {"case": label, "mode": mode, "number_representation": representation, "expected_valid": wanted_valid, "expected_reward": wanted_reward, "actual": report, "passed": ok}
        result.append(row)
        if not ok:
            failures.append(row)
    # Distinguish scoring raw text from a caller discarding precision first.
    fractional_raw = raw.replace(old, '"excess_failed_requests": 48.000000000000000001', 1)
    predecoded = json.loads(fractional_raw)
    boundary = {
        "raw_text": fractional_raw,
        "raw_text_report": verifier.evaluate(config.make_task(17), fractional_raw),
        "standard_json_loads_value_repr": repr(predecoded["incidents"][0]["excess_failed_requests"]),
        "predecoded_dict_report": verifier.evaluate(config.make_task(17), predecoded),
        "interpretation": "Caller already rounded original text before evaluate; preserve raw model JSON to retain lexical precision. This is not a raw JSON verifier bypass.",
    }
    run = HERE / ("post-fix-run-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    run.mkdir()
    summary = {
        "scope": "numeric parsing follow-up only; not a rerun of the 10000-seed audit",
        "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in ("alert_rlvr/config.py", "alert_rlvr/verifier.py", "alert_rlvr/data.py", "docs/CONTRACT.md")},
        "independent_gold": gold,
        "cases": len(result),
        "passes": sum(r["passed"] for r in result),
        "failures": failures,
    }
    for name, obj in (("summary.json", summary), ("cases.json", result), ("caller-predecode-boundary.json", boundary)):
        (run / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (run / "current-task.txt").write_text(config.make_task(17) + "\n", encoding="utf-8")
    print(json.dumps({"run": str(run), "cases": len(result), "passes": summary["passes"], "failures": failures}, ensure_ascii=False))


if __name__ == "__main__":
    main()
