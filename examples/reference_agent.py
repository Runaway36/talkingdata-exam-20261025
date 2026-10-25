"""Transparent reference computation using ONLY the public business APIs.

This is a deterministic demonstration, not an LLM or a training trajectory.
The independent verifier does not import this module.
"""
from alert_rlvr import config


def solve(env, trace=None):
    def query(name, **arguments):
        response = env.call(name, arguments)
        if not response.get("ok"):
            raise RuntimeError(f"Business API {name} failed: {response.get('error')}")
        if response["snapshot_id"] != env.snapshot_id:
            raise RuntimeError("Mixed snapshots are not allowed")
        if trace is not None:
            trace.append({"tool": name, "arguments": arguments,
                          "row_count": len(response["data"]),
                          "sample": response["data"][:2],
                          "snapshot_id": response["snapshot_id"]})
        return response["data"]

    alerts = query("list_alerts", start=config.WINDOW_START, end=config.WINDOW_END,
                   severities=list(config.ELIGIBLE_SEVERITIES), states=[config.ACTIVE_STATE])
    # An overlapping alert is not necessarily still active at the cutoff.
    alerts = [a for a in alerts if a["ended_at"] is None or a["ended_at"] > config.WINDOW_END]
    incident_ids = sorted({a["incident_id"] for a in alerts})
    if not incident_ids:
        return {"snapshot_id": env.snapshot_id, "incidents": [], "priority": []}
    links = query("get_incident_services", incident_ids=incident_ids)
    service_ids = sorted({link["service_id"] for link in links})
    if not service_ids:
        return {"snapshot_id": env.snapshot_id, "incidents": [], "priority": []}
    profiles = {row["service_id"]: row for row in
                query("get_service_profiles", service_ids=service_ids)}
    metrics = query("get_request_metrics", service_ids=service_ids,
                    start=config.WINDOW_START, end=config.WINDOW_END)
    maintenance = query("get_maintenance_windows", service_ids=service_ids,
                        start=config.WINDOW_START, end=config.WINDOW_END)
    incidents = []
    for incident_id in incident_ids:
        severity = min((a["severity"] for a in alerts if a["incident_id"] == incident_id),
                       key=config.SEVERITY_ORDER.__getitem__)
        contributing_services, seen = set(), set()
        excess_total = 0
        for link in links:
            if link["incident_id"] != incident_id:
                continue
            service_id = link["service_id"]
            profile = profiles[service_id]
            if profile["environment"] != config.PRODUCTION_ENVIRONMENT:
                continue
            for bucket in metrics:
                if bucket["service_id"] != service_id:
                    continue
                start, end = bucket["bucket_start"], bucket["bucket_end"]
                if not (config.WINDOW_START <= start < end <= config.WINDOW_END
                        and link["impact_start"] <= start and end <= link["impact_end"]):
                    continue
                key = (service_id, start, end)
                if key in seen:
                    continue
                seen.add(key)
                if any(m["service_id"] == service_id
                       and m["status"] == config.APPROVED_MAINTENANCE
                       and m["starts_at"] <= start and end <= m["ends_at"]
                       for m in maintenance):
                    continue
                baseline = bucket["request_count"] * profile["baseline_failure_bps"] // config.BASIS_POINTS
                excess = max(0, bucket["failed_requests"] - baseline)
                excess_total += excess
                if excess > 0:
                    contributing_services.add(service_id)
        if excess_total > 0:
            incidents.append({"incident_id": incident_id, "severity": severity,
                              "service_ids": sorted(contributing_services),
                              "excess_failed_requests": excess_total})
    priority = sorted(incidents, key=lambda row: (-row["excess_failed_requests"],
                      config.SEVERITY_ORDER[row["severity"]], row["incident_id"]))
    return {"snapshot_id": env.snapshot_id, "incidents": incidents,
            "priority": [row["incident_id"] for row in priority[:config.TOP_K]]}
