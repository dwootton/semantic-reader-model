import io
import json
import tempfile
import unittest
from unittest.mock import patch

from harness.model import LabClient, ModelError
from harness.lab_config import LabConfig


class InputLimitTests(unittest.TestCase):
    def setUp(self):
        lab = patch("harness.model._require_lab_config", return_value=LabConfig(
            "test-user@example.com", "semantic-test-project", "semantic-test"))
        lab.start()
        self.addCleanup(lab.stop)

    def test_observed_customer_page_size_is_supported_without_truncation(self):
        prompt = "x" * 635000
        response = io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"{\\"ok\\":true}"}]}}]}')
        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, max_calls=1)
            with (
                patch.object(client, "_token", return_value="test-token"),
                patch("harness.model.urllib.request.urlopen", return_value=response) as network,
            ):
                result, _ = client.generate("gemini-3.8-flash", "system", prompt, purpose="test")
            self.assertTrue(result["ok"])
            self.assertIn(prompt.encode(), network.call_args.args[0].data)
            self.assertNotIn("responseSchema", json.loads(network.call_args.args[0].data)["generationConfig"])

    def test_optional_output_schema_is_sent_to_vertex(self):
        schema = {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}, "required": ["ok"]}
        response = io.BytesIO(json.dumps({"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]}).encode())
        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, max_calls=1)
            with (
                patch.object(client, "_token", return_value="test-token"),
                patch("harness.model.urllib.request.urlopen", return_value=response) as network,
            ):
                client.generate("gemini-3.8-flash", "system", "prompt", purpose="test", response_schema=schema)
            config = json.loads(network.call_args.args[0].data)["generationConfig"]
            self.assertEqual(config["responseSchema"], schema)
            self.assertEqual(config["responseMimeType"], "application/json")

    def test_inputs_over_the_new_bounded_limit_still_fail_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, max_calls=1)
            with patch("harness.model.urllib.request.urlopen") as network:
                with self.assertRaisesRegex(ModelError, "size cap"):
                    client.generate("gemini-3.8-flash", "system", "x" * 1000001, purpose="test")
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
