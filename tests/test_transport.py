import io
import json
import unittest

from alert_rlvr.config import WINDOW_START, WINDOW_END, snapshot_id
from alert_rlvr.tools import MAX_REQUEST_BYTES, serve


class TransportTests(unittest.TestCase):
    def exchange(self, lines):
        output = io.StringIO()
        serve(17, io.StringIO("\n".join(lines) + "\n"), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), len(lines))
        for response in responses:
            self.assertEqual(response["snapshot_id"], snapshot_id())
        return responses

    def valid_query(self, request_id="after-error"):
        return json.dumps({"id": request_id, "tool": "list_alerts",
                           "arguments": {"start": WINDOW_START, "end": WINDOW_END}})

    def test_valid_business_request_returns_structured_rows(self):
        response = self.exchange([self.valid_query(7)])[0]
        self.assertEqual(response["id"], 7)
        self.assertTrue(response["ok"], response)
        self.assertIsInstance(response["data"], list)
        self.assertTrue(response["data"])

    def test_bad_json_duplicate_keys_and_wrong_envelopes_recover_on_next_line(self):
        bad_lines = [
            "not json", "[]", "null", "true",
            '{"id": 1, "id": 2, "tool": "list_alerts", "arguments": {}}',
            '{"tool": "get_service_profiles", "arguments": {"service_ids": [], "service_ids": ["svc-pay"]}}',
            '{"id": true, "tool": "list_alerts", "arguments": {}}',
            '{"tool": "list_alerts", "unexpected": 42}',
            " " * (MAX_REQUEST_BYTES + 1),
        ]
        for raw in bad_lines:
            with self.subTest(raw=raw[:100]):
                first, second = self.exchange([raw, self.valid_query()])
                self.assertFalse(first["ok"], first)
                self.assertTrue(first["error"]["code"], first)
                self.assertTrue(second["ok"], second)
                self.assertEqual(second["id"], "after-error")

    def test_private_and_grading_tools_are_not_exposed(self):
        names = ("close", "_connection", "execute", "expected_answer", "compute_reward", "__class__")
        requests = [json.dumps({"id": name, "tool": name, "arguments": {}}) for name in names]
        responses = self.exchange(requests + [self.valid_query()])
        for response in responses[:-1]:
            self.assertFalse(response["ok"], response)
            self.assertIn("error", response)
            self.assertNotIn("data", response)
        self.assertTrue(responses[-1]["ok"])

    def test_invalid_business_arguments_return_error_without_exiting(self):
        request = json.dumps({"id": 1, "tool": "get_service_profiles",
                              "arguments": {"service_ids": True}})
        first, second = self.exchange([request, self.valid_query()])
        self.assertFalse(first["ok"], first)
        self.assertTrue(second["ok"], second)

    def test_escaped_unpaired_surrogate_id_cannot_crash_utf8_transport(self):
        # StringIO accepts invalid Unicode; actual UTF-8 stdout does not.
        raw = '{"id":"\\ud800","tool":"list_alerts","arguments":{}}'
        output_bytes = io.BytesIO()
        output_text = io.TextIOWrapper(output_bytes, encoding="utf-8", errors="strict")
        serve(17, io.StringIO(raw + "\n" + self.valid_query() + "\n"), output_text)
        output_text.flush()
        responses = [json.loads(line) for line in output_bytes.getvalue().decode("utf-8").splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertFalse(responses[0]["ok"])
        self.assertTrue(responses[1]["ok"])


if __name__ == "__main__":
    unittest.main()
