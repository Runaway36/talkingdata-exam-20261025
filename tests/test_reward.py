import copy
import json
import unittest
from unittest.mock import patch

from alert_rlvr import verifier
from alert_rlvr.config import MAX_ANSWER_BYTES, make_task, snapshot_id
from alert_rlvr.environment import AlertEnvironment
from examples.reference_agent import solve
from tests.fixtures import fixture_database, manual_answer


class GeneratedSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.answers = {}
        for seed in (17, 23, 91):
            with AlertEnvironment(seed) as environment:
                cls.answers[seed] = solve(environment)

    def test_reference_solver_full_reward_for_three_seeds(self):
        for seed, answer in self.answers.items():
            with self.subTest(seed=seed):
                report = verifier.evaluate(make_task(seed), answer)
                self.assertEqual(report["reward"], 1.0, report)
                self.assertTrue(report["valid"])
                self.assertEqual(verifier.compute_reward(make_task(seed), answer), 1.0)

    def test_different_seeds_change_business_numbers(self):
        values = []
        for answer in self.answers.values():
            values.append(tuple(sorted(row["excess_failed_requests"]
                                       for row in answer["incidents"])))
        self.assertEqual(len(set(values)), 3)

    def test_solver_is_deterministic(self):
        with AlertEnvironment(17) as environment:
            self.assertEqual(solve(environment), self.answers[17])

    def test_details_and_service_order_are_semantically_irrelevant(self):
        answer = copy.deepcopy(self.answers[17])
        self.assertTrue(any(len(row["service_ids"]) > 1 for row in answer["incidents"]),
                        "Control must include a real multi-service incident")
        answer["incidents"].reverse()
        for row in answer["incidents"]:
            row["service_ids"].reverse()
        self.assertEqual(verifier.compute_reward(make_task(), answer), 1.0)
        self.assertEqual(verifier.compute_reward(make_task(), json.dumps(answer)), 1.0)


class ProtocolAndPartialCreditTests(unittest.TestCase):
    def setUp(self):
        self.database_patch = patch("alert_rlvr.verifier.build_database", fixture_database)
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        self.task = make_task()
        self.answer = manual_answer()

    def assert_protocol_rejected(self, answer):
        report = verifier.evaluate(self.task, answer)
        self.assertEqual(report["reward"], 0.0, report)
        self.assertFalse(report["valid"], report)
        self.assertTrue(report["errors"], report)

    def test_manual_gold_is_perfect_without_reference_solver(self):
        report = verifier.evaluate(self.task, self.answer)
        self.assertEqual(report["reward"], 1.0, report)
        self.assertEqual(report["matched_count"], 3)
        self.assertEqual(report["priority_matches"], 2)
        self.assertEqual(report["extra_count"], 0)
        self.assertEqual(report["components"], {"incidents": 1.0, "priority": 1.0})

    def test_missing_nonpriority_event_has_partial_credit(self):
        self.answer["incidents"] = [r for r in self.answer["incidents"]
                                    if r["incident_id"] != "INC-C"]
        report = verifier.evaluate(self.task, self.answer)
        self.assertTrue(report["valid"], report)
        self.assertAlmostEqual(report["reward"], 4 / 5)

    def test_extra_event_cannot_receive_perfect_reward(self):
        extra = copy.deepcopy(self.answer["incidents"][0])
        extra["incident_id"] = "INC-UNKNOWN"
        self.answer["incidents"].append(extra)
        report = verifier.evaluate(self.task, self.answer)
        self.assertTrue(report["valid"], report)
        self.assertAlmostEqual(report["reward"], 5 / 6)
        self.assertEqual(report["extra_count"], 1)

    def test_wrong_priority_event_count_loses_incident_and_position_credit(self):
        # INC-A is the second priority item: its wrong count invalidates both
        # the incident and that priority claim even though the ID is in place.
        self.answer["incidents"][0]["excess_failed_requests"] += 1
        report = verifier.evaluate(self.task, self.answer)
        self.assertTrue(report["valid"], report)
        self.assertAlmostEqual(report["reward"], 3 / 5)
        self.assertEqual(report["matched_count"], 2)
        self.assertEqual(report["priority_matches"], 1)

    def test_wrong_nonpriority_event_count_loses_one_incident(self):
        self.answer["incidents"][2]["excess_failed_requests"] += 1
        report = verifier.evaluate(self.task, self.answer)
        self.assertTrue(report["valid"], report)
        self.assertAlmostEqual(report["reward"], 4 / 5)
        self.assertEqual(report["matched_count"], 2)
        self.assertEqual(report["priority_matches"], 2)

    def test_all_counts_zero_gets_zero_even_with_correct_priority(self):
        for row in self.answer["incidents"]:
            row["excess_failed_requests"] = 0
        report = verifier.evaluate(self.task, self.answer)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["reward"], 0.0)
        self.assertEqual(report["matched_count"], 0)
        self.assertEqual(report["priority_matches"], 0)

    def test_guessing_only_incident_ids_and_severities_gets_zero(self):
        for row in self.answer["incidents"]:
            row["service_ids"] = []
            row["excess_failed_requests"] = 0
        self.answer["priority"] = []
        report = verifier.evaluate(self.task, self.answer)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["reward"], 0.0)

    def test_complete_incident_requires_correct_severity_and_services(self):
        for field, wrong in (("severity", "P1"), ("service_ids", ["svc-a"])):
            with self.subTest(field=field):
                answer = copy.deepcopy(self.answer)
                answer["incidents"][2][field] = wrong
                report = verifier.evaluate(self.task, answer)
                self.assertTrue(report["valid"], report)
                self.assertAlmostEqual(report["reward"], 4 / 5)
                self.assertEqual(report["matched_count"], 2)

    def test_correcting_wrong_counts_cannot_reduce_reward(self):
        answer = copy.deepcopy(self.answer)
        for row in answer["incidents"]:
            row["excess_failed_requests"] = 0
        previous = verifier.compute_reward(self.task, answer)
        self.assertEqual(previous, 0.0)
        # Repair the nonpriority event first, then each priority event, while
        # holding every other submitted field and the ranking unchanged.
        for index in (2, 0, 1):
            with self.subTest(repaired_incident=answer["incidents"][index]["incident_id"]):
                answer["incidents"][index]["excess_failed_requests"] = (
                    self.answer["incidents"][index]["excess_failed_requests"])
                repaired = verifier.compute_reward(self.task, answer)
                self.assertGreaterEqual(repaired, previous)
                previous = repaired
        self.assertEqual(previous, 1.0)

    def test_wrong_priority_order_loses_position_credit(self):
        self.answer["priority"].reverse()
        report = verifier.evaluate(self.task, self.answer)
        self.assertTrue(report["valid"], report)
        self.assertAlmostEqual(report["reward"], 3 / 5)

    def test_missing_priority_can_receive_partial_credit(self):
        self.answer["priority"] = self.answer["priority"][:1]
        report = verifier.evaluate(self.task, self.answer)
        self.assertTrue(report["valid"], report)
        self.assertAlmostEqual(report["reward"], 4 / 5)

    def test_empty_submission_not_perfect(self):
        report = verifier.evaluate(self.task, {
            "snapshot_id": snapshot_id(), "incidents": [], "priority": []})
        self.assertEqual(report["reward"], 0.0)

    def test_duplicate_incident_service_and_priority_are_rejected(self):
        variants = []
        duplicate_row = copy.deepcopy(self.answer)
        duplicate_row["incidents"].append(copy.deepcopy(duplicate_row["incidents"][0]))
        variants.append(duplicate_row)
        duplicate_service = copy.deepcopy(self.answer)
        duplicate_service["incidents"][0]["service_ids"] *= 2
        variants.append(duplicate_service)
        duplicate_priority = copy.deepcopy(self.answer)
        duplicate_priority["priority"] = ["INC-A", "INC-A"]
        variants.append(duplicate_priority)
        for answer in variants:
            with self.subTest(answer=answer):
                self.assert_protocol_rejected(answer)

    def test_numeric_protocol_rejects_bool_float_negative_and_nonfinite(self):
        for bad in (True, False, -1, 1.5, float("nan"), float("inf"), "40", None):
            with self.subTest(bad=bad):
                answer = copy.deepcopy(self.answer)
                answer["incidents"][0]["excess_failed_requests"] = bad
                self.assert_protocol_rejected(answer)

    def test_equivalent_integer_json_number_forms_receive_full_reward(self):
        raw = json.dumps(self.answer)
        for token in ("40.0", "4e1", "400e-1"):
            with self.subTest(token=token):
                equivalent = raw.replace('"excess_failed_requests": 40',
                                         '"excess_failed_requests": ' + token, 1)
                self.assertEqual(verifier.compute_reward(self.task, equivalent), 1.0)
        self.answer["incidents"][0]["excess_failed_requests"] = 40.0
        self.assertEqual(verifier.compute_reward(self.task, self.answer), 1.0)

    def test_tiny_fraction_is_not_rounded_into_a_correct_integer(self):
        raw = json.dumps(self.answer).replace('"excess_failed_requests": 40',
                                              '"excess_failed_requests": 40.000000000000000001', 1)
        self.assert_protocol_rejected(raw)

    def test_public_answer_size_boundary(self):
        self.assertIn(str(MAX_ANSWER_BYTES), self.task)
        raw = json.dumps(self.answer)
        at_limit = raw + " " * (MAX_ANSWER_BYTES - len(raw.encode("utf-8")))
        self.assertEqual(verifier.compute_reward(self.task, at_limit), 1.0)
        self.assert_protocol_rejected(at_limit + " ")

    def test_json_nonfinite_numbers_and_duplicate_keys_are_rejected(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            raw = json.dumps(self.answer).replace('"excess_failed_requests": 40',
                                                  '"excess_failed_requests": ' + token, 1)
            self.assert_protocol_rejected(raw)
        raw = json.dumps(self.answer)
        duplicate_top = raw[:-1] + ', "snapshot_id": "' + snapshot_id() + '"}'
        duplicate_nested = raw.replace('"excess_failed_requests": 40',
                                       '"excess_failed_requests": 40, "excess_failed_requests": 40', 1)
        self.assert_protocol_rejected(duplicate_top)
        self.assert_protocol_rejected(duplicate_nested)

    def test_snapshot_mismatch_unknown_fields_and_bad_priority_rejected(self):
        variants = []
        wrong_snapshot = copy.deepcopy(self.answer)
        wrong_snapshot["snapshot_id"] = snapshot_id(23)
        variants.append(wrong_snapshot)
        unknown_field = copy.deepcopy(self.answer)
        unknown_field["reasoning"] = "extra key"
        variants.append(unknown_field)
        unknown_nested = copy.deepcopy(self.answer)
        unknown_nested["incidents"][0]["extra"] = 1
        variants.append(unknown_nested)
        bad_priority = copy.deepcopy(self.answer)
        bad_priority["priority"] = ["INC-NOT-SUBMITTED"]
        variants.append(bad_priority)
        too_long_priority = copy.deepcopy(self.answer)
        too_long_priority["priority"] = ["INC-A", "INC-C", "INC-B"]
        variants.append(too_long_priority)
        for answer in variants:
            with self.subTest(answer=answer):
                self.assert_protocol_rejected(answer)

    def test_bad_top_level_and_unknown_task_do_not_raise(self):
        for bad in (None, True, 42, [], "not json", "null", "[]"):
            with self.subTest(answer=bad):
                self.assert_protocol_rejected(bad)
        for task in (None, {}, "unknown", self.task + "\nchanged"):
            report = verifier.evaluate(task, self.answer)
            self.assertEqual(report["reward"], 0.0, report)
            self.assertFalse(report["valid"], report)

    def test_canonical_task_accepts_crlf_and_outer_whitespace(self):
        equivalent = "\r\n " + self.task.replace("\n", "\r\n") + " \r\n"
        self.assertEqual(verifier.compute_reward(equivalent, self.answer), 1.0)

    def test_v2_task_is_not_accepted_by_v3_scorer(self):
        previous_version = self.task.replace("alert-impact-v3-seed-", "alert-impact-v2-seed-", 1)
        self.assertNotEqual(previous_version, self.task)
        report = verifier.evaluate(previous_version, self.answer)
        self.assertFalse(report["valid"], report)
        self.assertEqual(report["reward"], 0.0)
        self.assertTrue(report["errors"])


class BusinessBoundaryTests(unittest.TestCase):
    def score_control(self, mutation=None, answer=None):
        def build(seed):
            connection = fixture_database(seed)
            if mutation is not None:
                mutation(connection)
                connection.commit()
            return connection
        with patch("alert_rlvr.verifier.build_database", build):
            return verifier.evaluate(make_task(), answer or manual_answer())

    def test_manual_control_covers_dedupe_maintenance_environment_and_ties(self):
        report = self.score_control()
        self.assertEqual(report["reward"], 1.0, report)
        self.assertEqual(report["expected_count"], 3)

    def test_reference_solver_matches_independent_hand_calculation_through_api_only(self):
        with patch("alert_rlvr.environment.build_database", fixture_database):
            with AlertEnvironment() as environment:
                class BusinessOnlyView:
                    __slots__ = ("snapshot_id", "call")
                view = BusinessOnlyView()
                view.snapshot_id = environment.snapshot_id
                view.call = environment.call
                answer = solve(view)
        self.assertEqual(answer, manual_answer())

    def test_no_qualifying_events_accepts_empty_answer(self):
        answer = {"snapshot_id": snapshot_id(), "incidents": [], "priority": []}
        report = self.score_control(lambda db: db.execute("DELETE FROM alerts"), answer)
        self.assertEqual(report["expected_count"], 0)
        self.assertEqual(report["reward"], 1.0, report)
        self.assertEqual(report["components"], {"incidents": 1.0, "priority": 1.0})

    def test_no_qualifying_events_rejects_extra_event_with_zero_reward(self):
        answer = {"snapshot_id": snapshot_id(),
                  "incidents": [copy.deepcopy(manual_answer()["incidents"][0])],
                  "priority": []}
        report = self.score_control(lambda db: db.execute("DELETE FROM alerts"), answer)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["expected_count"], 0)
        self.assertEqual(report["extra_count"], 1)
        self.assertEqual(report["reward"], 0.0)
        self.assertEqual(report["components"], {"incidents": 0.0, "priority": 1.0})

    def test_ended_alert_cannot_raise_incident_severity_at_window_end(self):
        # The P0 alerts ended during the window; only the P1 remains active.
        def build(seed):
            connection = fixture_database(seed)
            connection.execute(
                "UPDATE alerts SET ended_at='2026-10-25T08:10:00Z' "
                "WHERE alert_id IN ('alert-a2', 'alert-a3')")
            connection.commit()
            return connection
        expected = manual_answer()
        expected["incidents"][0]["severity"] = "P1"
        expected["priority"] = ["INC-B", "INC-C"]
        with patch("alert_rlvr.environment.build_database", build):
            with AlertEnvironment() as environment:
                actual = solve(environment)
        self.assertEqual(actual, expected)
        with patch("alert_rlvr.verifier.build_database", build):
            self.assertEqual(verifier.compute_reward(make_task(), expected), 1.0)

    def test_removing_duplicate_alert_does_not_change_answer(self):
        report = self.score_control(lambda db: db.execute(
            "DELETE FROM alerts WHERE alert_id='alert-a3'"))
        self.assertEqual(report["reward"], 1.0, report)

    def test_redundant_host_notifications_titles_retry_and_latency_do_not_change_truth(self):
        def mutate(db):
            db.execute("UPDATE alerts SET title='P0 high error count wrong service', description='noise'")
            db.execute("UPDATE request_metrics SET retry_count=999999, latency_p95_ms=999999")
            db.execute("INSERT INTO host_metrics VALUES ('host-1', 100, 100, '2026-10-25T08:00:00Z')")
            db.execute("INSERT INTO notification_history VALUES ('n1', 'INC-A', 'wechat', 0, '2026-10-25T08:00:00Z')")
        self.assertEqual(self.score_control(mutate)["reward"], 1.0)

    def test_three_necessary_sources_change_the_correct_answer(self):
        # Keep the old answer fixed. Removing relationships, changing service
        # baselines, or changing observations must each invalidate that answer.
        controls = {
            "incident_services": "DELETE FROM incident_services WHERE incident_id='INC-A'",
            "service_profiles": "UPDATE services SET baseline_failure_bps=2000 WHERE service_id='svc-a'",
            "request_metrics": "UPDATE request_metrics SET failed_requests=0 WHERE service_id='svc-a'",
            "maintenance": "DELETE FROM maintenance WHERE maintenance_id='maint-full-bucket'",
        }
        for name, sql in controls.items():
            with self.subTest(source=name):
                report = self.score_control(lambda db, sql=sql: db.execute(sql))
                self.assertLess(report["reward"], 1.0, report)

    def test_approved_full_bucket_changes_request_count_but_cancelled_and_partial_do_not(self):
        # Removing a partial/cancelled maintenance row must leave the answer.
        for maintenance_id in ("maint-partial", "maint-cancelled"):
            report = self.score_control(lambda db, mid=maintenance_id: db.execute(
                "DELETE FROM maintenance WHERE maintenance_id=?", (mid,)))
            self.assertEqual(report["reward"], 1.0, report)
        answer = manual_answer()
        answer["incidents"][0]["excess_failed_requests"] = 60
        report = self.score_control(lambda db: db.execute(
            "DELETE FROM maintenance WHERE maintenance_id='maint-full-bucket'"), answer)
        self.assertEqual(report["reward"], 1.0, report)

    def test_partial_incident_bucket_is_excluded(self):
        # Moving A's end to 08:24 excludes the entire 08:20..08:25 bucket.
        answer = manual_answer()
        answer["incidents"][0]["excess_failed_requests"] = 30
        answer["priority"] = ["INC-B", "INC-C"]
        report = self.score_control(lambda db: db.execute(
            "UPDATE incident_services SET impact_end='2026-10-25T08:24:00Z' "
            "WHERE incident_id='INC-A' AND service_id='svc-a'"), answer)
        self.assertEqual(report["reward"], 1.0, report)


if __name__ == "__main__":
    unittest.main()
