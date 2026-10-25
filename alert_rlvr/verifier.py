"""Trusted, deterministic scoring of final answers, independent of tool traces.

The oracle uses SQL over a fresh trusted snapshot. It does not call the agent's
business APIs or the reference solver. Never register this module as an agent
tool: ``expected_answer`` is provided only for trusted tests and evaluation.
"""

import json

from . import config
from .data import build_database


_TOP_LEVEL_KEYS = {"snapshot_id", "incidents", "priority"}
_INCIDENT_KEYS = {
    "incident_id", "severity", "service_ids", "excess_failed_requests"
}
_SCORED_FIELDS = (
    "severity", "service_ids", "excess_failed_requests"
)


def _zero_report(error, expected_count=0):
    return {
        "reward": 0.0,
        "valid": False,
        "components": {"coverage": 0.0, "fields": 0.0, "priority": 0.0},
        "errors": [error],
        "expected_count": expected_count,
    }


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON number: " + value)


def _parse_answer(answer):
    if type(answer) is str:
        if len(answer.encode("utf-8")) > config.MAX_ANSWER_BYTES:
            raise ValueError("answer exceeds byte limit")
        return json.loads(
            answer,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    if type(answer) is not dict:
        raise ValueError("answer must be a dict or JSON object string")
    # This also rejects cyclic objects, non-JSON objects and NaN/Infinity in a
    # dict submission. Schema validation below retains strict Python types.
    encoded = json.dumps(answer, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > config.MAX_ANSWER_BYTES:
        raise ValueError("answer exceeds byte limit")
    return answer


def _valid_id(value):
    return type(value) is str and bool(value.strip())


def _validate_answer(answer, seed):
    if type(answer) is not dict:
        raise ValueError("answer root must be an object")
    if set(answer) != _TOP_LEVEL_KEYS:
        raise ValueError("answer must contain exactly snapshot_id, incidents and priority")
    if type(answer["snapshot_id"]) is not str:
        raise ValueError("snapshot_id must be a string")
    if answer["snapshot_id"] != config.snapshot_id(seed):
        raise ValueError("snapshot_id does not match task")
    if type(answer["incidents"]) is not list:
        raise ValueError("incidents must be an array")
    if type(answer["priority"]) is not list:
        raise ValueError("priority must be an array")

    seen_incidents = set()
    for row in answer["incidents"]:
        if type(row) is not dict or set(row) != _INCIDENT_KEYS:
            raise ValueError("each incident must contain exactly the four required fields")
        incident_id = row["incident_id"]
        if not _valid_id(incident_id):
            raise ValueError("incident_id must be a nonempty string")
        if incident_id in seen_incidents:
            raise ValueError("duplicate incident_id")
        seen_incidents.add(incident_id)
        if type(row["severity"]) is not str or row["severity"] not in config.SEVERITY_ORDER:
            raise ValueError("severity must be a supported severity string")
        service_ids = row["service_ids"]
        if type(service_ids) is not list or any(not _valid_id(s) for s in service_ids):
            raise ValueError("service_ids must be an array of nonempty strings")
        if len(service_ids) != len(set(service_ids)):
            raise ValueError("duplicate service_id")
        for field in ("excess_failed_requests",):
            # bool is an int subclass, hence intentionally use exact type.
            if type(row[field]) is not int or row[field] < 0:
                raise ValueError(field + " must be a nonnegative integer")

    priority = answer["priority"]
    if len(priority) > config.TOP_K:
        raise ValueError("priority exceeds top_k")
    if any(not _valid_id(incident_id) for incident_id in priority):
        raise ValueError("priority must contain nonempty string IDs")
    if len(priority) != len(set(priority)):
        raise ValueError("duplicate priority ID")
    if any(incident_id not in seen_incidents for incident_id in priority):
        raise ValueError("priority must reference submitted incident details")


def _expected_for_seed(seed):
    # All time comparisons use the snapshot's canonical, fixed-width UTC ISO
    # timestamps. NOT EXISTS avoids multiplying observations by maintenance
    # rows. DISTINCT prevents duplicate alerts/relations/observations from
    # multiplying the same incident/service/bucket contribution.
    sql = """
        WITH eligible_incidents AS (
            SELECT incident_id,
                   MIN(CASE WHEN severity = :p0 THEN :p0_rank
                            ELSE :p1_rank END) AS severity_rank
            FROM alerts
            WHERE state = :active_state
              AND severity IN (:p0, :p1)
              AND started_at < :window_end
              AND (ended_at IS NULL OR ended_at > :window_end)
            GROUP BY incident_id
        ), effective_buckets AS (
            SELECT DISTINCT e.incident_id, e.severity_rank, m.service_id,
                   m.bucket_start, m.bucket_end,
                   MAX(0, m.failed_requests -
                       (m.request_count * s.baseline_failure_bps / :basis_points)
                   ) AS excess_failed_requests
            FROM eligible_incidents AS e
            JOIN incident_services AS r ON r.incident_id = e.incident_id
            JOIN services AS s ON s.service_id = r.service_id
            JOIN request_metrics AS m ON m.service_id = s.service_id
            WHERE s.environment = :production
              AND m.bucket_start >= :window_start
              AND m.bucket_end <= :window_end
              AND m.bucket_start >= r.impact_start
              AND m.bucket_end <= r.impact_end
              AND NOT EXISTS (
                  SELECT 1 FROM maintenance AS w
                  WHERE w.service_id = m.service_id
                    AND w.status = :approved
                    AND w.starts_at <= m.bucket_start
                    AND w.ends_at >= m.bucket_end
              )
        )
        SELECT incident_id, severity_rank, service_id,
               SUM(excess_failed_requests) AS excess_failed_requests
        FROM effective_buckets
        GROUP BY incident_id, severity_rank, service_id
        ORDER BY incident_id, service_id
    """
    parameters = {
        "p0": config.ELIGIBLE_SEVERITIES[0],
        "p1": config.ELIGIBLE_SEVERITIES[1],
        "p0_rank": config.SEVERITY_ORDER[config.ELIGIBLE_SEVERITIES[0]],
        "p1_rank": config.SEVERITY_ORDER[config.ELIGIBLE_SEVERITIES[1]],
        "active_state": config.ACTIVE_STATE,
        "window_start": config.WINDOW_START,
        "window_end": config.WINDOW_END,
        "production": config.PRODUCTION_ENVIRONMENT,
        "approved": config.APPROVED_MAINTENANCE,
        "basis_points": config.BASIS_POINTS,
    }
    connection = build_database(seed)
    try:
        records = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()

    severity_by_rank = {rank: label for label, rank in config.SEVERITY_ORDER.items()}
    incidents = {}
    for record in records:
        incident_id = record["incident_id"]
        if incident_id not in incidents:
            incidents[incident_id] = {
                "incident_id": incident_id,
                "severity": severity_by_rank[record["severity_rank"]],
                "service_ids": [],
                "excess_failed_requests": 0,
            }
        row = incidents[incident_id]
        row["excess_failed_requests"] += record["excess_failed_requests"]
        if record["excess_failed_requests"] > 0:
            row["service_ids"].append(record["service_id"])

    result = [row for row in incidents.values() if row["excess_failed_requests"] > 0]
    for row in result:
        row["service_ids"].sort()
    result.sort(key=lambda row: row["incident_id"])
    ranked = sorted(result, key=lambda row: (
        -row["excess_failed_requests"], config.SEVERITY_ORDER[row["severity"]], row["incident_id"]
    ))
    return {
        "snapshot_id": config.snapshot_id(seed),
        "incidents": result,
        "priority": [row["incident_id"] for row in ranked[:config.TOP_K]],
    }


def expected_answer(task):
    """Return the SQL oracle answer for trusted tests, never an agent-facing API."""
    return _expected_for_seed(config.resolve_task(task))


def evaluate(task, answer):
    """Validate and score a final dict/JSON answer; never inspect a tool trace.

    A valid but wrong/partial answer receives fractional credit. Protocol errors
    and unknown task text receive zero. Components are raw scores in [0, 1];
    the final reward applies config.REWARD_WEIGHTS to those components.
    """
    try:
        seed = config.resolve_task(task)
    except Exception:
        return _zero_report("unknown or malformed task")
    try:
        expected = _expected_for_seed(seed)
    except Exception:
        return _zero_report("trusted snapshot could not be evaluated")
    expected_rows = {row["incident_id"]: row for row in expected["incidents"]}
    expected_count = len(expected_rows)
    try:
        submitted = _parse_answer(answer)
        _validate_answer(submitted, seed)
    except Exception as exc:
        # Deliberately avoid returning a stack trace or the trusted oracle.
        detail = str(exc) if isinstance(exc, (ValueError, TypeError)) else "malformed answer"
        return _zero_report(detail, expected_count)

    actual_rows = {row["incident_id"]: row for row in submitted["incidents"]}
    matched_ids = expected_rows.keys() & actual_rows.keys()
    denominator = len(expected_rows) + len(actual_rows)
    coverage = 2 * len(matched_ids) / denominator if denominator else 1.0
    matched_fields = 0
    for incident_id in matched_ids:
        for field in _SCORED_FIELDS:
            actual = actual_rows[incident_id][field]
            wanted = expected_rows[incident_id][field]
            if field == "service_ids":
                actual, wanted = set(actual), set(wanted)
            matched_fields += int(actual == wanted)
    fields = matched_fields / (expected_count * len(_SCORED_FIELDS)) if expected_count else 1.0
    priority_matches = sum(
        index < len(submitted["priority"]) and submitted["priority"][index] == incident_id
        for index, incident_id in enumerate(expected["priority"])
    )
    priority = priority_matches / len(expected["priority"]) if expected["priority"] else (
        1.0 if not submitted["priority"] else 0.0
    )
    components = {"coverage": coverage, "fields": fields, "priority": priority}
    reward = sum(config.REWARD_WEIGHTS[name] * value for name, value in components.items())
    reward = max(0.0, min(1.0, reward))
    return {
        "reward": reward,
        "valid": True,
        "components": components,
        "errors": [],
        "expected_count": expected_count,
        "matched_count": len(matched_ids),
        "matched_fields": matched_fields,
    }


def compute_reward(task, answer):
    """Uniform training entry point: canonical task + final answer -> float."""
    return float(evaluate(task, answer)["reward"])
