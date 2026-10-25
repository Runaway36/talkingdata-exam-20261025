"""Scoring infrastructure failures must not become training zero rewards."""
import copy
import sqlite3
import unittest
from unittest.mock import patch

from alert_rlvr import verifier
from alert_rlvr.config import make_task
from tests.fixtures import fixture_database, manual_answer


class VerifierFailureTests(unittest.TestCase):
    def test_evaluate_identifies_trusted_snapshot_failure(self):
        with patch("alert_rlvr.verifier.build_database",
                   side_effect=sqlite3.OperationalError("synthetic database failure")):
            report = verifier.evaluate(make_task(), manual_answer())
        self.assertFalse(report["valid"])
        self.assertEqual(report["error_code"], "TRUSTED_SNAPSHOT_UNAVAILABLE")
        self.assertEqual(report["errors"], ["trusted snapshot could not be evaluated"])
        self.assertNotIn("synthetic database failure", str(report))

    def test_compute_reward_raises_infrastructure_error_instead_of_zero(self):
        with patch("alert_rlvr.verifier.build_database",
                   side_effect=RuntimeError("synthetic infrastructure failure")):
            with self.assertRaises(verifier.VerifierInfrastructureError) as caught:
                verifier.compute_reward(make_task(), manual_answer())
        self.assertEqual(caught.exception.error_code, "TRUSTED_SNAPSHOT_UNAVAILABLE")

    def test_unknown_task_stays_zero_and_does_not_access_snapshot(self):
        with patch("alert_rlvr.verifier.build_database") as build:
            report = verifier.evaluate("unknown task", manual_answer())
            self.assertEqual(verifier.compute_reward("unknown task", manual_answer()), 0.0)
        build.assert_not_called()
        self.assertNotIn("error_code", report)

    def test_wrong_and_malformed_answers_stay_zero_without_infrastructure_marker(self):
        wrong = copy.deepcopy(manual_answer())
        for row in wrong["incidents"]:
            row["excess_failed_requests"] = 0
        with patch("alert_rlvr.verifier.build_database", fixture_database):
            for answer in (wrong, "not JSON"):
                with self.subTest(answer=answer):
                    self.assertEqual(verifier.compute_reward(make_task(), answer), 0.0)
                    self.assertNotIn("error_code", verifier.evaluate(make_task(), answer))

    def test_correct_answer_report_remains_unchanged(self):
        with patch("alert_rlvr.verifier.build_database", fixture_database):
            report = verifier.evaluate(make_task(), manual_answer())
            self.assertEqual(verifier.compute_reward(make_task(), manual_answer()), 1.0)
        self.assertEqual(report, {
            "reward": 1.0, "valid": True,
            "components": {"incidents": 1.0, "priority": 1.0},
            "errors": [], "expected_count": 3, "matched_count": 3,
            "priority_matches": 2, "extra_count": 0,
        })


if __name__ == "__main__":
    unittest.main()
