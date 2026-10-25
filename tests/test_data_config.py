"""Bucket configuration drives actual data, with default snapshot regression."""

from datetime import datetime
import hashlib
import unittest
from unittest.mock import patch

from alert_rlvr import config
from alert_rlvr.data import build_database
from alert_rlvr.environment import AlertEnvironment
from alert_rlvr.verifier import expected_answer, evaluate
from examples.reference_agent import solve


class DataConfigurationTests(unittest.TestCase):
    def test_default_snapshot_matches_prechange_all_table_dumps(self):
        expected = {
            0: "4cc5a918ee8a0bee7811373a29ecefc4aaaef3dcd1718656270bcc9ab24f33bb",
            17: "df8abeb6243e6c6043eb2e25c49ee5c4051c98563f79ae3c81b95e077c7f1177",
            42: "7119e61ad01d75d3d94b98e0f25b5fc7e60f72f0a6778d464423eb95b745cf1f",
            99: "308ca08f4271fad6f21f7b94c33123e6ac943c4ec69951b84bd27b92869d369d",
            9999: "2e54b0f74c2f880930307bf10e29d0ee7b085d588a8d15b411bfca980080fb4e",
        }
        for seed, digest in expected.items():
            with self.subTest(seed=seed):
                connection = build_database(seed)
                try:
                    actual = hashlib.sha256("\n".join(connection.iterdump()).encode("utf-8")).hexdigest()
                    self.assertEqual(actual, digest)
                finally:
                    connection.close()

    def test_ten_minute_configuration_changes_actual_buckets(self):
        with patch.object(config, "BUCKET_MINUTES", 10):
            connection = build_database(17)
            try:
                rows = list(connection.execute("SELECT * FROM request_metrics"))
                self.assertEqual(len(rows), 11 * 3)
                for row in rows:
                    start = datetime.fromisoformat(row["bucket_start"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(row["bucket_end"].replace("Z", "+00:00"))
                    self.assertEqual((end - start).total_seconds(), 600)
            finally:
                connection.close()
            with AlertEnvironment(17) as env:
                answer = solve(env)
                self.assertEqual(answer, expected_answer(env.task))
                self.assertEqual(evaluate(env.task, answer)["reward"], 1)

    def test_invalid_bucket_configuration_raises_explicit_error(self):
        for value in (0, -1, True, 2.5, "5", 7, 60):
            with self.subTest(value=value), patch.object(config, "BUCKET_MINUTES", value):
                with self.assertRaisesRegex(ValueError, "BUCKET_MINUTES|complete buckets"):
                    build_database()

    def test_invalid_or_non_integral_window_raises_explicit_error(self):
        for end in (config.WINDOW_START, "2026-10-25T07:00:00Z", "2026-10-25T08:30:01Z", "2026-10-27T08:30:00Z", "not-a-time"):
            with self.subTest(end=end), patch.object(config, "WINDOW_END", end):
                with self.assertRaises(ValueError):
                    build_database()


if __name__ == "__main__":
    unittest.main()
