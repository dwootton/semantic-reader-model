import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import patch

from harness.model import ModelError
from harness.ollama_model import OllamaClient, _NoRedirect, json_schema


MODEL = "gemma4:12b"


def response(body):
    return io.BytesIO(json.dumps(body).encode())


def installed(**extra):
    return {"models": [{"name": MODEL, "model": MODEL, "digest": "sha256:test", **extra}]}


def shown(**extra):
    return {"model_info": {"gemma4.context_length": 262144}, **extra}


def loaded(**extra):
    return {"models": [{"name": MODEL, "model": MODEL, "digest": "sha256:test",
                        "context_length": 131072, "size_vram": 2_500_000_000, **extra}]}


def generated(**extra):
    return {
        "model": MODEL, "done": True, "done_reason": "stop",
        "message": {"content": '{"groups":[]}'},
        "prompt_eval_count": 100, "eval_count": 12,
        "total_duration": 4_000_000_000, "load_duration": 1_000_000_000,
        "prompt_eval_duration": 2_000_000_000, "eval_duration": 1_000_000_000,
        **extra,
    }


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = OllamaClient(self.directory.name)

    def events(self):
        return [json.loads(line) for line in (Path(self.directory.name) / "model_calls.jsonl").read_text().splitlines()]

    def generate(self, **kwargs):
        return self.client.generate(MODEL, "system", "prompt", purpose="test", **kwargs)

    def test_schema_conversion_preserves_properties_nullable_and_constraints(self):
        schema = {
            "type": "OBJECT", "required": ["groups"],
            "properties": {
                "groups": {"type": "ARRAY", "maxItems": 24, "items": {
                    "type": "OBJECT", "properties": {
                        "parent_id": {"type": "STRING", "nullable": True},
                        "nullable": {"type": "BOOLEAN"},
                        "type": {"type": "STRING", "enum": ["OBJECT", "ARRAY"]},
                    },
                }},
            },
        }
        converted = json_schema(schema)
        self.assertEqual(converted["type"], "object")
        self.assertEqual(converted["required"], ["groups"])
        groups = converted["properties"]["groups"]
        self.assertEqual(groups["maxItems"], 24)
        properties = groups["items"]["properties"]
        self.assertEqual(properties["parent_id"], {"type": ["string", "null"]})
        self.assertEqual(properties["nullable"], {"type": "boolean"})
        self.assertEqual(properties["type"]["enum"], ["OBJECT", "ARRAY"])
        self.assertEqual(schema["type"], "OBJECT")

    def test_local_request_schema_stats_and_complete_logs(self):
        schema = {"type": "OBJECT", "properties": {"groups": {"type": "ARRAY", "items": {"type": "STRING"}}}}
        self.client.deadline = time.monotonic() + 30
        with (
            patch.object(self.client._opener, "open", side_effect=[response(installed()), response(shown()), response(generated()), response(loaded())]) as network,
            patch("harness.model.local_lab_token") as auth,
        ):
            result, metadata = self.generate(response_schema=schema, max_tokens=1234)
        auth.assert_not_called()
        self.assertEqual(result, {"groups": []})
        self.assertEqual(self.client.calls, 1)
        self.assertEqual(metadata["model_digest"], "sha256:test")
        self.assertEqual(metadata["backend"], "ollama")
        self.assertEqual(metadata["model_version"], MODEL)
        self.assertEqual(metadata["usage"], {"promptTokenCount": 100, "candidatesTokenCount": 12, "totalTokenCount": 112})
        self.assertEqual(metadata["load_duration_seconds"], 1)
        self.assertEqual(metadata["prompt_eval_duration_seconds"], 2)
        self.assertEqual(metadata["eval_duration_seconds"], 1)
        self.assertEqual(metadata["done_reason"], "stop")
        self.assertEqual(metadata["native_context_length"], 262144)
        self.assertEqual(metadata["loaded_context_length"], 131072)
        self.assertEqual(metadata["loaded_size_vram"], 2_500_000_000)
        self.assertEqual(metadata["loaded_model_digest"], "sha256:test")
        self.assertEqual(self.client.usage, metadata["usage"])
        self.assertEqual(len(network.call_args_list), 4)
        for call in network.call_args_list:
            self.assertTrue(call.args[0].full_url.startswith("http://127.0.0.1:11434/api/"))
            self.assertFalse(call.args[0].has_header("Authorization"))
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 30)
        request = json.loads(network.call_args_list[2].args[0].data)
        self.assertEqual(request["format"], json_schema(schema))
        self.assertEqual(request["options"], {"temperature": 0, "num_ctx": 131072, "num_predict": 1234})
        self.assertIs(request["stream"], False)
        self.assertIs(request["think"], False)
        self.assertEqual(request["keep_alive"], "5m")
        event = self.events()[0]
        self.assertEqual(event["request"], request)
        self.assertEqual(event["response"], generated())
        self.assertEqual([item["path"] for item in event["validation"]], ["/api/tags", "/api/show", "/api/ps"])
        self.assertEqual(event["validation"][-1]["loaded_context_length"], 131072)
        self.assertIn("conservative", event["input_bound_method"])

    def test_unverified_reduced_or_changed_loaded_model_rejects_sample(self):
        for running, message in (
            ({"models": []}, "Cannot verify"),
            (loaded(context_length=None), "Cannot verify"),
            (loaded(context_length="131072"), "Cannot verify"),
            (loaded(context_length=True), "Cannot verify"),
            (loaded(context_length=32768), "smaller context"),
            (loaded(digest="sha256:different"), "digest differs"),
        ):
            with self.subTest(running=running), patch.object(self.client._opener, "open", side_effect=[response(installed()), response(shown()), response(generated()), response(running)]) as network:
                with self.assertRaisesRegex(ModelError, message):
                    self.generate()
                self.assertEqual(network.call_count, 4)
                self.assertTrue(all(call.args[0].full_url.startswith("http://127.0.0.1:11434/api/") for call in network.call_args_list))
                event = self.events()[-1]
                self.assertEqual(event["validation"][-1]["response"], running)
                self.assertIn("error", event)
                self.assertNotIn("metadata", event)
        self.assertEqual(self.client.usage, {})

    def test_larger_loaded_context_is_accepted(self):
        with patch.object(self.client._opener, "open", side_effect=[response(installed()), response(shown()), response(generated()), response(loaded(context_length=262144))]):
            _, metadata = self.generate()
        self.assertEqual(metadata["num_ctx"], 131072)
        self.assertEqual(metadata["loaded_context_length"], 262144)

    def test_budget_and_deadline_fail_without_network_or_auth(self):
        for budget, deadline in ((0, None), (40, time.monotonic() - 1)):
            with self.subTest(budget=budget):
                self.client.max_calls = budget
                self.client.deadline = deadline
                with patch.object(self.client._opener, "open") as network, patch("harness.model.local_lab_token") as auth:
                    with self.assertRaisesRegex(ModelError, "budget exhausted"):
                        self.generate()
                network.assert_not_called()
                auth.assert_not_called()

    def test_no_remote_model_or_uninstalled_model_is_requested(self):
        with patch.object(self.client._opener, "open") as network:
            for model in ("gemma4:cloud", "gemma4-cloud:12b"):
                with self.subTest(model=model), self.assertRaisesRegex(ModelError, "Cloud-backed"):
                    self.client.generate(model, "system", "prompt", purpose="test")
            network.assert_not_called()
        for bodies, message in (
            ([{"models": []}], "not installed"),
            ([installed(remote_host="https://ollama.com")], "Cloud-backed"),
            ([installed(), shown(remote_model="gemma4:cloud")], "Cloud-backed"),
            ([installed(), shown(remote_host="")], "Cloud-backed"),
        ):
            with self.subTest(bodies=bodies), patch.object(self.client._opener, "open", side_effect=[response(body) for body in bodies]) as network:
                with self.assertRaisesRegex(ModelError, message):
                    self.generate()
                self.assertEqual(network.call_count, len(bodies))
                self.assertTrue(all(not call.args[0].full_url.endswith("/chat") for call in network.call_args_list))
        self.assertEqual(self.client.calls, 0)

    def test_native_context_must_be_verified_and_not_exceeded(self):
        for info, message in (({}, "Cannot verify"), ({"gemma4.context_length": 8192}, "native context")):
            with self.subTest(info=info), patch.object(self.client._opener, "open", side_effect=[response(installed()), response(shown(model_info=info))]) as network:
                with self.assertRaisesRegex(ModelError, message):
                    self.generate()
                self.assertEqual(network.call_count, 2)

    def test_conservative_byte_bound_rejects_without_truncation_or_network(self):
        self.client.num_ctx = 6000
        with patch.object(self.client._opener, "open") as network:
            with self.assertRaisesRegex(ModelError, "no input was truncated or sent"):
                self.client.generate(MODEL, "system", "😸" * 1000, purpose="test", max_tokens=1000)
        network.assert_not_called()
        event = self.events()[0]
        self.assertEqual(event["request"]["messages"][1]["content"], "😸" * 1000)
        self.assertGreater(event["input_token_upper_bound"], 5000)

    def test_length_unfinished_invalid_and_non_object_outputs_are_errors(self):
        for extra, message in (
            ({"done_reason": "length"}, "token limit"),
            ({"done": False}, "did not finish"),
            ({"message": {"content": '{"groups":'}}, "invalid JSON"),
            ({"message": {"content": "[]"}}, "JSON object"),
        ):
            with self.subTest(extra=extra), patch.object(self.client._opener, "open", side_effect=[response(installed()), response(shown()), response(generated(**extra))]) as network:
                with self.assertRaisesRegex(ModelError, message):
                    self.generate()
                self.assertEqual(network.call_count, 3)
                self.assertIn("error", self.events()[-1])
                self.assertEqual(self.events()[-1]["response"], generated(**extra))

    def test_http_failure_has_one_attempt_and_logs_response(self):
        failure = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 500, "failed", {}, io.BytesIO(b'{"error":"out of memory"}'))
        with patch.object(self.client._opener, "open", side_effect=[response(installed()), response(shown()), failure]) as network:
            with self.assertRaisesRegex(ModelError, "HTTP 500: out of memory"):
                self.generate()
        self.assertEqual(network.call_count, 3)
        self.assertEqual(self.client.calls, 1)
        self.assertEqual(self.events()[0]["response_text"], '{"error":"out of memory"}')

    def test_connection_failure_is_readable_and_does_not_retry(self):
        with patch.object(self.client._opener, "open", side_effect=urllib.error.URLError("connection refused")) as network:
            with self.assertRaisesRegex(ModelError, "Start Ollama locally"):
                self.generate()
        network.assert_called_once()

    def test_local_transport_disables_proxies_and_rejects_redirects(self):
        with patch("harness.ollama_model.urllib.request.build_opener") as build:
            OllamaClient(self.directory.name)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], _NoRedirect)
        with self.assertRaisesRegex(ModelError, "redirects are not allowed"):
            _NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://remote.example")


if __name__ == "__main__":
    unittest.main()
