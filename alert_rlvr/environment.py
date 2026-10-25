"""Read-only business APIs; no agent-facing database path or SQL entrypoint."""

from datetime import datetime
import inspect
import re
import sqlite3

from .config import DEFAULT_SEED, MAX_IDS, SEVERITY_ORDER, WINDOW_END, WINDOW_START, make_task, snapshot_id
from .data import build_database


_TIME_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
_ID_LIST = {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": MAX_IDS}
_TIME = {"type": "string", "pattern": _TIME_PATTERN, "description": "Strict UTC timestamp within the snapshot window."}


def _schema(name, description, properties, required):
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}


API_SCHEMAS = [
    _schema("list_alerts", "List alerts overlapping a window, optionally filtered by severity and current state.", {"start": _TIME, "end": _TIME, "severities": {"type": ["array", "null"], "items": {"type": "string", "enum": list(SEVERITY_ORDER)}, "minItems": 1, "maxItems": MAX_IDS}, "states": {"type": ["array", "null"], "items": {"type": "string", "enum": ["firing", "resolved", "suppressed"]}, "minItems": 1, "maxItems": MAX_IDS}}, ["start", "end"]),
    _schema("get_incident_services", "Get authoritative incident/service relationships and impact intervals.", {"incident_ids": _ID_LIST}, ["incident_ids"]),
    _schema("get_service_profiles", "Get service environment, baseline request failure rate, and ownership.", {"service_ids": _ID_LIST}, ["service_ids"]),
    _schema("get_request_metrics", "Get request and failed-request counts for complete observation buckets within the supplied window.", {"service_ids": _ID_LIST, "start": _TIME, "end": _TIME}, ["service_ids", "start", "end"]),
    _schema("get_maintenance_windows", "Get overlapping maintenance records, including cancelled and partial coverage.", {"service_ids": _ID_LIST, "start": _TIME, "end": _TIME}, ["service_ids", "start", "end"]),
    _schema("get_host_metrics", "Get host CPU and memory utilization with collection timestamps.", {"resource_ids": _ID_LIST}, ["resource_ids"]),
    _schema("get_notification_history", "Get synthetic message delivery records for incidents.", {"incident_ids": _ID_LIST}, ["incident_ids"]),
]
_ALLOWED_NAMES = frozenset(schema["name"] for schema in API_SCHEMAS)


class AlertEnvironment:
    """Protocol boundary for a cooperating agent, not a same-process sandbox."""

    def __init__(self, seed=DEFAULT_SEED):
        self.snapshot_id = snapshot_id(seed)
        self.task = make_task(seed)
        self._connection = build_database(seed)

    def __enter__(self):
        if self._connection is None:
            raise RuntimeError("environment is closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _error(self, code, message):
        return {"ok": False, "snapshot_id": self.snapshot_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _ids(values, name, allowed=None):
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_IDS:
            raise ValueError(f"{name} must be a nonempty list with at most {MAX_IDS} strings")
        if any(type(value) is not str or not value.strip() for value in values):
            raise ValueError(f"{name} must contain nonempty strings")
        if allowed is not None and any(value not in allowed for value in values):
            raise ValueError(f"{name} contains an unsupported value")
        return list(dict.fromkeys(values))

    @staticmethod
    def _window(start, end):
        for value in (start, end):
            if type(value) is not str or re.fullmatch(_TIME_PATTERN, value) is None:
                raise ValueError("start and end must be strict UTC timestamps YYYY-MM-DDTHH:MM:SSZ")
            try:
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                raise ValueError("start or end is not a valid UTC timestamp") from None
        if not WINDOW_START <= start < end <= WINDOW_END:
            raise ValueError("start must precede end and both must be inside the snapshot window")
        return start, end

    def _execute(self, query, parameters=()):
        if self._connection is None:
            return self._error("ENVIRONMENT_CLOSED", "environment is closed")
        try:
            cursor = self._connection.execute(query, parameters)
            try:
                rows = [dict(row) for row in cursor.fetchall()]
            finally:
                cursor.close()
            return {"ok": True, "snapshot_id": self.snapshot_id, "data": rows}
        except sqlite3.Error:
            return self._error("DATA_UNAVAILABLE", "snapshot data is temporarily unavailable")

    def _query_ids(self, table, column, values, name, suffix="", parameters=(), order_by=None):
        try:
            values = self._ids(values, name)
        except ValueError as error:
            return self._error("INVALID_ARGUMENT", str(error))
        placeholders = ",".join("?" for _ in values)
        # Table/column/suffix originate only in trusted methods below, never agent input.
        query = f"SELECT * FROM {table} WHERE {column} IN ({placeholders}) {suffix} ORDER BY {order_by or column}"
        return self._execute(query, (*values, *parameters))

    def call(self, name, arguments=None):
        if type(name) is not str or name not in _ALLOWED_NAMES:
            return self._error("UNKNOWN_API", "unknown business API")
        if type(arguments) is not dict:
            return self._error("INVALID_ARGUMENT", "arguments must be an object")
        method = getattr(self, name)
        try:
            inspect.signature(method).bind(**arguments)
            return method(**arguments)
        except (TypeError, ValueError):
            return self._error("INVALID_ARGUMENT", "arguments do not match the business API schema")
        except Exception:
            return self._error("INTERNAL_ERROR", "business API request could not be completed")

    def list_alerts(self, start=None, end=None, severities=None, states=None):
        try:
            start, end = self._window(start, end)
            filters = []
            parameters = [end, start]
            for values, column, allowed in ((severities, "severity", SEVERITY_ORDER), (states, "state", ("firing", "resolved", "suppressed"))):
                if values is not None:
                    values = self._ids(values, column, allowed)
                    filters.append(f"AND {column} IN ({','.join('?' for _ in values)})")
                    parameters.extend(values)
        except ValueError as error:
            return self._error("INVALID_ARGUMENT", str(error))
        return self._execute("SELECT * FROM alerts WHERE started_at < ? AND (ended_at IS NULL OR ended_at > ?) " + " ".join(filters) + " ORDER BY alert_id", parameters)

    def get_incident_services(self, incident_ids=None):
        return self._query_ids("incident_services", "incident_id", incident_ids, "incident_ids", order_by="incident_id, service_id")

    def get_service_profiles(self, service_ids=None):
        return self._query_ids("services", "service_id", service_ids, "service_ids")

    def get_request_metrics(self, service_ids=None, start=None, end=None):
        try:
            start, end = self._window(start, end)
        except ValueError as error:
            return self._error("INVALID_ARGUMENT", str(error))
        return self._query_ids("request_metrics", "service_id", service_ids, "service_ids", "AND bucket_start >= ? AND bucket_end <= ?", (start, end), "service_id, bucket_start")

    def get_maintenance_windows(self, service_ids=None, start=None, end=None):
        try:
            start, end = self._window(start, end)
        except ValueError as error:
            return self._error("INVALID_ARGUMENT", str(error))
        return self._query_ids("maintenance", "service_id", service_ids, "service_ids", "AND starts_at < ? AND ends_at > ?", (end, start), "service_id, starts_at, maintenance_id")

    def get_host_metrics(self, resource_ids=None):
        return self._query_ids("host_metrics", "resource_id", resource_ids, "resource_ids")

    def get_notification_history(self, incident_ids=None):
        return self._query_ids("notification_history", "incident_id", incident_ids, "incident_ids", order_by="incident_id, notification_id")
