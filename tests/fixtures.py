"""Hand-calculated business controls, independent of the generated answer."""
import sqlite3

from alert_rlvr.config import snapshot_id


def fixture_database(seed=17):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE alerts (alert_id TEXT PRIMARY KEY, incident_id TEXT,
            resource_id TEXT, severity TEXT, state TEXT, started_at TEXT,
            ended_at TEXT, title TEXT, description TEXT, source TEXT);
        CREATE TABLE incident_services (incident_id TEXT, service_id TEXT,
            impact_start TEXT, impact_end TEXT);
        CREATE TABLE services (service_id TEXT PRIMARY KEY, name TEXT,
            environment TEXT, baseline_failure_bps INTEGER,
            owner_team TEXT, dashboard_url TEXT);
        CREATE TABLE request_metrics (service_id TEXT, bucket_start TEXT,
            bucket_end TEXT, request_count INTEGER, failed_requests INTEGER,
            retry_count INTEGER, latency_p95_ms INTEGER);
        CREATE TABLE maintenance (maintenance_id TEXT PRIMARY KEY,
            service_id TEXT, starts_at TEXT, ends_at TEXT, status TEXT, reason TEXT);
        CREATE TABLE host_metrics (resource_id TEXT, cpu_percent REAL,
            memory_percent REAL, collected_at TEXT);
        CREATE TABLE notification_history (notification_id TEXT,
            incident_id TEXT, channel TEXT, delivered INTEGER, sent_at TEXT);
    """)

    def stamp(minute):
        return "2026-10-25T08:%02d:00Z" % minute

    alerts = [
        ("alert-a1", "INC-A", "P1", "firing", stamp(0), None),
        ("alert-a2", "INC-A", "P0", "firing", stamp(0), None),
        ("alert-a3", "INC-A", "P0", "firing", stamp(0), None),
        ("alert-b", "INC-B", "P1", "firing", stamp(0), None),
        ("alert-c", "INC-C", "P0", "firing", stamp(0), None),
        ("alert-maint", "INC-MAINT", "P1", "firing", stamp(0), None),
        ("alert-resolved", "INC-RESOLVED", "P0", "resolved", stamp(0), stamp(5)),
        ("alert-noise", "INC-NOISE", "P2", "firing", stamp(0), None),
        ("alert-ended-before", "INC-BOUNDARY", "P0", "resolved",
         "2026-10-25T07:55:00Z", stamp(0)),
        ("alert-start-at-end", "INC-BOUNDARY", "P0", "firing", stamp(30), None),
    ]
    connection.executemany(
        "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(aid, iid, "host-1", severity, state, start, end,
          "Misleading human title", "Synthetic diagnostic", "monitor")
         for aid, iid, severity, state, start, end in alerts],
    )
    profiles = [
        ("svc-a", "production", 1000),
        # floor(101 * 150 / 10000) = 1, so 81 failures leave 80 excess.
        ("svc-b", "production", 150),
        ("svc-c", "production", 0),
        ("svc-stage", "staging", 0),
        ("svc-zero", "production", 1000),
        ("svc-maint", "production", 0),
        ("svc-resolved", "production", 0),
        ("svc-noise", "production", 0),
    ]
    connection.executemany(
        "INSERT INTO services VALUES (?, ?, ?, ?, ?, ?)",
        [(sid, sid, env, baseline, "team", "https://example.invalid")
         for sid, env, baseline in profiles],
    )
    relations = [
        ("INC-A", "svc-a", 0, 25), ("INC-A", "svc-stage", 0, 30),
        ("INC-A", "svc-zero", 0, 30), ("INC-B", "svc-b", 0, 5),
        ("INC-C", "svc-c", 0, 5), ("INC-MAINT", "svc-maint", 0, 30),
        ("INC-RESOLVED", "svc-resolved", 0, 30),
        ("INC-NOISE", "svc-noise", 0, 30),
    ]
    connection.executemany(
        "INSERT INTO incident_services VALUES (?, ?, ?, ?)",
        [(iid, sid, stamp(start), stamp(end)) for iid, sid, start, end in relations],
    )
    metrics = [("svc-a", start, 100, failed)
               for start, failed in [(0, 20), (5, 30), (10, 30), (15, 5),
                                     (20, 20), (25, 99)]]
    metrics += [("svc-b", 0, 101, 81), ("svc-c", 0, 100, 40),
                ("svc-stage", 0, 100, 99), ("svc-zero", 0, 100, 5),
                ("svc-maint", 0, 100, 99), ("svc-resolved", 0, 100, 99),
                ("svc-noise", 0, 100, 99)]
    connection.executemany(
        "INSERT INTO request_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(sid, stamp(start), stamp(start + 5), requests, failed, 777, 999)
         for sid, start, requests, failed in metrics],
    )
    connection.executemany("INSERT INTO maintenance VALUES (?, ?, ?, ?, ?, ?)", [
        ("maint-full-bucket", "svc-a", stamp(5), stamp(10), "approved", "planned"),
        ("maint-partial", "svc-a", stamp(11), stamp(14), "approved", "partial"),
        ("maint-cancelled", "svc-a", stamp(20), stamp(25), "cancelled", "cancelled"),
        ("maint-full-window", "svc-maint", stamp(0), stamp(30), "approved", "planned"),
    ])
    connection.commit()
    return connection


def manual_answer(seed=17):
    # A: 10 + 0 + 20 + 0 + 10 = 40 excess failed requests; B: 80; C: 40.
    # B comes first by count; A precedes C on their equal count and P0 severity.
    return {
        "snapshot_id": snapshot_id(seed),
        "incidents": [
            {"incident_id": "INC-A", "severity": "P0", "service_ids": ["svc-a"],
             "excess_failed_requests": 40},
            {"incident_id": "INC-B", "severity": "P1", "service_ids": ["svc-b"],
             "excess_failed_requests": 80},
            {"incident_id": "INC-C", "severity": "P0", "service_ids": ["svc-c"],
             "excess_failed_requests": 40},
        ],
        "priority": ["INC-B", "INC-A"],
    }
