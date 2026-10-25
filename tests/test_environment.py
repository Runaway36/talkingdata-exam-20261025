import unittest
from unittest.mock import patch

from alert_rlvr.config import WINDOW_START, WINDOW_END, make_task, resolve_task, snapshot_id
from alert_rlvr.data import build_database
from alert_rlvr.environment import AlertEnvironment
from tests.fixtures import fixture_database


class ConfigurationTests(unittest.TestCase):
    def test_seed_validation_and_canonical_task(self):
        for seed in (0, 17, 9999):
            self.assertEqual(resolve_task(make_task(seed)), seed)
        for bad in (-1, 10000, True, 1.5, "17", None):
            with self.subTest(seed=bad):
                with self.assertRaises(ValueError):
                    snapshot_id(bad)


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch("alert_rlvr.environment.build_database", fixture_database)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.environment = AlertEnvironment()
        self.addCleanup(self.environment.close)

    def assert_error(self, response):
        self.assertIsInstance(response, dict)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["snapshot_id"], snapshot_id())
        self.assertIsInstance(response["error"]["code"], str)
        self.assertIsInstance(response["error"]["message"], str)
        self.assertNotIn("Traceback", str(response))

    def test_alert_query_uses_half_open_overlap(self):
        response = self.environment.list_alerts(WINDOW_START, WINDOW_END)
        self.assertTrue(response["ok"], response)
        identifiers = {row["alert_id"] for row in response["data"]}
        self.assertIn("alert-a1", identifiers)
        self.assertIn("alert-resolved", identifiers)
        self.assertNotIn("alert-ended-before", identifiers)
        self.assertNotIn("alert-start-at-end", identifiers)

    def test_alert_filters(self):
        response = self.environment.list_alerts(WINDOW_START, WINDOW_END,
                                                severities=["P0"], states=["firing"])
        self.assertTrue(response["ok"], response)
        self.assertTrue(response["data"])
        self.assertTrue(all(r["severity"] == "P0" and r["state"] == "firing"
                            for r in response["data"]))

    def test_metric_query_requires_complete_buckets(self):
        response = self.environment.get_request_metrics(
            ["svc-a"], "2026-10-25T08:01:00Z", "2026-10-25T08:10:00Z")
        self.assertTrue(response["ok"], response)
        self.assertEqual([r["bucket_start"] for r in response["data"]],
                         ["2026-10-25T08:05:00Z"])
        response = self.environment.get_request_metrics(
            ["svc-a"], WINDOW_START, "2026-10-25T08:05:00Z")
        self.assertEqual(len(response["data"]), 1)
        self.assertEqual(response["data"][0]["bucket_start"], WINDOW_START)

    def test_maintenance_returns_cancelled_for_business_decision(self):
        response = self.environment.get_maintenance_windows(["svc-a"], WINDOW_START, WINDOW_END)
        self.assertTrue(response["ok"], response)
        self.assertEqual({r["status"] for r in response["data"]}, {"approved", "cancelled"})

    def test_invalid_times_are_structured_errors(self):
        for start, end in [
            (WINDOW_END, WINDOW_START), (WINDOW_START, WINDOW_START),
            ("2026-10-25T07:59:00Z", WINDOW_END),
            (WINDOW_START, "2026-10-25T08:31:00Z"),
            ("2026-10-25 08:00:00", WINDOW_END),
            ("2026-10-25T08:00:00+00:00", WINDOW_END),
            ("2026-10-25T08:99:00Z", WINDOW_END), (True, WINDOW_END),
        ]:
            with self.subTest(start=start, end=end):
                self.assert_error(self.environment.list_alerts(start, end))

    def test_invalid_id_types_and_limits_are_structured_errors(self):
        for ids in (None, True, "svc-a", [], [True], [1], [""], ["svc-a"] * 51):
            with self.subTest(ids=ids):
                self.assert_error(self.environment.get_service_profiles(ids))

    def test_dispatch_does_not_expose_arbitrary_attributes_or_raise(self):
        for name, arguments in [
            ("__class__", {}), ("close", {}), ("_conn", {}),
            ("DROP TABLE alerts", {}), (None, {}), ([], {}),
            ("list_alerts", None), ("list_alerts", []),
            ("list_alerts", {"unexpected": True}),
            ("list_alerts", {"start": WINDOW_START}),
        ]:
            with self.subTest(name=name, arguments=arguments):
                self.assert_error(self.environment.call(name, arguments))
        self.assertTrue(self.environment.list_alerts(WINDOW_START, WINDOW_END)["ok"])

    def test_sql_injection_strings_never_return_other_services(self):
        for identifier in ("svc-a' OR 1=1 --", "'; DROP TABLE services; --"):
            response = self.environment.get_service_profiles([identifier])
            if response["ok"]:
                self.assertEqual(response["data"], [])
            else:
                self.assert_error(response)
        response = self.environment.get_service_profiles(["svc-a"])
        self.assertTrue(response["ok"], response)
        self.assertEqual([r["service_id"] for r in response["data"]], ["svc-a"])


class GeneratedDatabaseTests(unittest.TestCase):
    def test_database_has_real_controls_and_is_deterministic(self):
        with build_database(17) as first, build_database(17) as second:
            self.assertEqual([tuple(r) for r in first.execute("SELECT * FROM request_metrics ORDER BY service_id,bucket_start")],
                             [tuple(r) for r in second.execute("SELECT * FROM request_metrics ORDER BY service_id,bucket_start")])
            severities = {r[0] for r in first.execute("SELECT DISTINCT severity FROM alerts")}
            self.assertTrue({"P0", "P1", "P2"}.issubset(severities))
            self.assertIn("resolved", {r[0] for r in first.execute("SELECT DISTINCT state FROM alerts")})
            self.assertIn("staging", {r[0] for r in first.execute("SELECT DISTINCT environment FROM services")})
            self.assertTrue({"approved", "cancelled"}.issubset(
                {r[0] for r in first.execute("SELECT DISTINCT status FROM maintenance")}))
            self.assertIsNotNone(first.execute(
                "SELECT incident_id FROM alerts GROUP BY incident_id HAVING COUNT(*) > 1").fetchone())


if __name__ == "__main__":
    unittest.main()
