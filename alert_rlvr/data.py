"""Trusted deterministic synthetic snapshots; never an agent-facing SQL tool."""

import random
import sqlite3
from datetime import datetime, timedelta

from . import config
from .config import DEFAULT_SEED, validate_seed


def _time(minute):
    start = datetime.fromisoformat(config.WINDOW_START.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bucket_layout():
    minutes = config.BUCKET_MINUTES
    if type(minutes) is not int or minutes <= 0:
        raise ValueError("BUCKET_MINUTES must be a positive integer")
    endpoints = []
    for value in (config.WINDOW_START, config.WINDOW_END):
        if type(value) is not str:
            raise ValueError("snapshot window must use strict UTC timestamps")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            raise ValueError("snapshot window must use strict UTC timestamps") from None
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
            raise ValueError("snapshot window must use strict UTC timestamps")
        endpoints.append(parsed)
    seconds = int((endpoints[1] - endpoints[0]).total_seconds())
    if not 0 < seconds <= 86400:
        raise ValueError("snapshot window must be positive and no longer than 24 hours")
    bucket_seconds = minutes * 60
    if seconds % bucket_seconds:
        raise ValueError("snapshot window must contain an exact positive number of complete buckets")
    return minutes, seconds // bucket_seconds


def build_database(seed=DEFAULT_SEED):
    """Build a fresh in-memory, read-only snapshot owned by the caller.

    This is an internal construction function, not a sandbox against arbitrary
    Python code executing in the same process. Callers must close the connection.
    """
    validate_seed(seed)
    bucket_minutes, bucket_count = _bucket_layout()
    rng = random.Random(seed)
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript("""
            CREATE TABLE alerts (
                alert_id TEXT PRIMARY KEY, incident_id TEXT, resource_id TEXT,
                severity TEXT, state TEXT, started_at TEXT, ended_at TEXT,
                title TEXT, description TEXT, source TEXT
            );
            CREATE TABLE incident_services (
                incident_id TEXT, service_id TEXT, impact_start TEXT, impact_end TEXT,
                PRIMARY KEY (incident_id, service_id)
            );
            CREATE TABLE services (
                service_id TEXT PRIMARY KEY, name TEXT, environment TEXT,
                baseline_failure_bps INTEGER, owner_team TEXT, dashboard_url TEXT
            );
            CREATE TABLE request_metrics (
                service_id TEXT, bucket_start TEXT, bucket_end TEXT,
                request_count INTEGER, failed_requests INTEGER, retry_count INTEGER,
                latency_p95_ms INTEGER, PRIMARY KEY (service_id, bucket_start)
            );
            CREATE TABLE maintenance (
                maintenance_id TEXT PRIMARY KEY, service_id TEXT, starts_at TEXT,
                ends_at TEXT, status TEXT, reason TEXT
            );
            CREATE TABLE host_metrics (
                resource_id TEXT PRIMARY KEY, cpu_percent REAL,
                memory_percent REAL, collected_at TEXT
            );
            CREATE TABLE notification_history (
                notification_id TEXT PRIMARY KEY, incident_id TEXT, channel TEXT,
                delivered INTEGER, sent_at TEXT
            );
        """)
        profiles = [
            ("svc-checkout", "Checkout", "production", 100, "orders"),
            ("svc-search", "Search", "production", 300, "discovery"),
            ("svc-cart", "Cart", "production", 200, "orders"),
            ("svc-pay", "Payment", "production", 50, "payments"),
            ("svc-pay-stage", "Payment staging", "staging", 0, "payments"),
            ("svc-auth", "Authentication", "production", 100, "identity"),
            ("svc-log", "Audit logging", "production", 0, "platform"),
            ("svc-baseline", "Returns", "production", 1000, "orders"),
            ("svc-noise", "Recommendations", "production", 0, "discovery"),
            ("svc-recovered", "Reconciler", "production", 0, "payments"),
            ("svc-future", "Future deployment", "production", 0, "platform"),
        ]
        connection.executemany(
            "INSERT INTO services VALUES (?, ?, ?, ?, ?, ?)",
            [(*row, f"https://monitoring.example.invalid/services/{row[0]}") for row in profiles],
        )
        relations = [
            ("INC-DB", "svc-checkout", _time(5), _time(25)),
            ("INC-DB", "svc-search", _time(7), _time(23)),
            ("INC-DB", "svc-cart", _time(0), _time(30)),
            ("INC-PAY", "svc-pay", _time(0), _time(30)),
            ("INC-PAY", "svc-pay-stage", _time(0), _time(30)),
            ("INC-AUTH", "svc-auth", _time(0), _time(30)),
            ("INC-LOG", "svc-log", _time(0), _time(30)),
            ("INC-BASE", "svc-baseline", _time(0), _time(30)),
            ("INC-NOISE", "svc-noise", _time(0), _time(30)),
            ("INC-RESOLVED", "svc-recovered", _time(0), _time(10)),
            ("INC-FUTURE", "svc-future", _time(30), _time(35)),
        ]
        connection.executemany("INSERT INTO incident_services VALUES (?, ?, ?, ?)", relations)
        # Titles deliberately do not specify authoritative service relationships.
        raw_alerts = [
            ("A-DB-1", "INC-DB", "host-db", "P0", "firing", _time(5), None, "Database connection pressure"),
            ("A-DB-2", "INC-DB", "host-db", "P1", "firing", _time(6), None, "Repeated database notification"),
            ("A-DB-3", "INC-DB", "host-db", "P0", "firing", _time(7), None, "Duplicate exporter alert"),
            ("A-PAY-1", "INC-PAY", "host-pay", "P1", "firing", _time(-10), None, "Payment dependency errors"),
            ("A-PAY-OLD", "INC-PAY", "host-pay", "P0", "resolved", _time(0), _time(3), "Earlier symptom recovered"),
            ("A-AUTH-1", "INC-AUTH", "host-auth", "P1", "firing", _time(0), None, "Authentication errors"),
            ("A-LOG-1", "INC-LOG", "host-log", "P0", "firing", _time(0), None, "Audit writer unavailable"),
            ("A-BASE-1", "INC-BASE", "host-returns", "P1", "firing", _time(0), None, "Failure counter threshold"),
            ("A-NOISE-1", "INC-NOISE", "host-recommend", "P2", "firing", _time(0), None, "Background diagnostic warning"),
            ("A-RESOLVED-1", "INC-RESOLVED", "host-reconcile", "P0", "resolved", _time(-10), _time(10), "Recovered incident"),
            ("A-FUTURE-1", "INC-FUTURE", "host-future", "P0", "firing", _time(30), None, "Outside report window"),
            ("A-HISTORY-1", "INC-HISTORY", "host-history", "P0", "resolved", _time(-20), _time(0), "Ended exactly at report start"),
        ]
        connection.executemany(
            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(*row, "Synthetic observation; query incident services for authoritative scope.", "synthetic-monitor") for row in raw_alerts],
        )
        maintenance = [
            ("M-LOG-FULL", "svc-log", _time(0), _time(30), "approved", "Planned audit migration"),
            ("M-AUTH-BUCKET", "svc-auth", _time(5), _time(10), "approved", "One complete bucket"),
            ("M-AUTH-CANCELLED", "svc-auth", _time(10), _time(15), "cancelled", "Cancelled deployment"),
            ("M-AUTH-PARTIAL", "svc-auth", _time(17), _time(19), "approved", "Partial coverage only"),
            ("M-DB-PARTIAL", "svc-checkout", _time(11), _time(14), "approved", "Does not cover a complete bucket"),
            ("M-PAY-CANCELLED", "svc-pay", _time(0), _time(30), "cancelled", "Migration did not take place"),
        ]
        connection.executemany("INSERT INTO maintenance VALUES (?, ?, ?, ?, ?, ?)", maintenance)
        metrics = []
        for service_id, _, _, baseline_bps, _ in profiles:
            for bucket in range(bucket_count):
                bucket_start = bucket * bucket_minutes
                bucket_end = bucket_start + bucket_minutes
                requests = 1000 + rng.randint(0, 200)
                baseline = requests * baseline_bps // 10000
                if service_id == "svc-pay":
                    excess = 18 + seed % 17 + rng.randint(0, 7)
                elif service_id == "svc-checkout":
                    excess = 25 + seed % 11 + rng.randint(0, 9) if 5 <= bucket_start and bucket_end <= 25 else 600
                elif service_id == "svc-search":
                    excess = 12 + seed % 7 + rng.randint(0, 5) if 7 <= bucket_start and bucket_end <= 23 else 500
                elif service_id == "svc-auth":
                    excess = 5 + seed % 5 + rng.randint(0, 4)
                elif service_id in ("svc-cart", "svc-baseline"):
                    excess = -rng.randint(0, 3)
                else:
                    excess = 400 + rng.randint(0, 100)
                failed = max(0, baseline + excess)
                metrics.append((service_id, _time(bucket_start), _time(bucket_end), requests, failed, rng.randint(0, 900), rng.randint(20, 4000)))
        connection.executemany("INSERT INTO request_metrics VALUES (?, ?, ?, ?, ?, ?, ?)", metrics)
        resources = sorted({row[2] for row in raw_alerts})
        connection.executemany(
            "INSERT INTO host_metrics VALUES (?, ?, ?, ?)",
            [(resource_id, round(rng.uniform(10, 99), 1), round(rng.uniform(20, 95), 1), _time(25)) for resource_id in resources],
        )
        incidents = sorted({row[1] for row in raw_alerts})
        connection.executemany(
            "INSERT INTO notification_history VALUES (?, ?, ?, ?, ?)",
            [(f"N-{index:03d}", incident_id, "synthetic-chat", int(index % 3 != 0), _time(28)) for index, incident_id in enumerate(incidents)],
        )
        connection.commit()
        connection.execute("PRAGMA query_only = ON")
        return connection
    except Exception:
        connection.close()
        raise
