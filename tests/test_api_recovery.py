import io
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

from harness.model import LabClient, ModelError
from harness.lab_config import LabConfig


def throttled(retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return urllib.error.HTTPError(
        "https://aiplatform.googleapis.com", 429, "capacity", headers,
        io.BytesIO(b'{"error":{"message":"Resource exhausted"}}'),
    )


def answer():
    return io.BytesIO(json.dumps({
        "candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}],
        "usageMetadata": {"promptTokenCount": 2},
    }).encode())


class ApiRecoveryTests(unittest.TestCase):
    def setUp(self):
        lab = patch("harness.model._require_lab_config", return_value=LabConfig(
            "test-user@example.com", "semantic-test-project", "semantic-test"))
        lab.start()
        self.addCleanup(lab.stop)

    def test_recovers_after_three_consecutive_capacity_errors(self):
        clock = SimpleNamespace(value=0.0)

        def sleep(seconds):
            clock.value += seconds

        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, max_calls=6)
            with (
                patch.object(client, "_token", return_value="test-credential"),
                patch("harness.model.time.monotonic", side_effect=lambda: clock.value),
                patch("harness.model.time.sleep", side_effect=sleep),
                patch("harness.model.urllib.request.urlopen", side_effect=[
                    throttled(), throttled(), throttled(), answer(),
                ]) as request,
            ):
                output, _ = client.generate("gemini-3.8-flash", "system", "input", purpose="test")
            self.assertTrue(output["ok"])
            self.assertEqual(request.call_count, 4)
            self.assertGreaterEqual(clock.value, 60)
            logs = [json.loads(line) for line in (client.output_dir / "model_calls.jsonl").read_text().splitlines()]
            self.assertEqual(sum("error" in event for event in logs), 3)

    def test_paces_successful_requests_and_honors_retry_after(self):
        clock = SimpleNamespace(value=0.0)

        def sleep(seconds):
            clock.value += seconds

        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, max_calls=5)
            with (
                patch.object(client, "_token", return_value="test-credential"),
                patch("harness.model.time.monotonic", side_effect=lambda: clock.value),
                patch("harness.model.time.sleep", side_effect=sleep),
                patch("harness.model.urllib.request.urlopen", side_effect=[answer(), throttled(45), answer()]),
            ):
                client.generate("gemini-3.8-flash", "system", "one", purpose="test")
                client.generate("gemini-3.8-flash", "system", "two", purpose="test")
            self.assertGreaterEqual(clock.value, 55)

    def test_request_cap_still_bounds_capacity_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, max_calls=2)
            with (
                patch.object(client, "_token", return_value="test-credential"),
                patch("harness.model.time.sleep"),
                patch("harness.model.urllib.request.urlopen", side_effect=[throttled(), throttled()]) as request,
            ):
                with self.assertRaises(ModelError):
                    client.generate("gemini-3.8-flash", "system", "input", purpose="test")
            self.assertEqual(request.call_count, 2)

    def test_deadline_prevents_a_retry_that_would_exceed_time_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, max_calls=6)
            client.deadline = 5
            with (
                patch.object(client, "_token", return_value="test-credential"),
                patch("harness.model.time.monotonic", return_value=0),
                patch("harness.model.time.sleep") as sleep,
                patch("harness.model.urllib.request.urlopen", side_effect=throttled()) as request,
            ):
                with self.assertRaisesRegex(ModelError, "time budget"):
                    client.generate("gemini-3.8-flash", "system", "input", purpose="test")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.kwargs["timeout"], 5)
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
