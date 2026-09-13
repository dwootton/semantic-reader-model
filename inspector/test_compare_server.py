"""Boundary and persistence tests; no credentials or model requests."""

import json
import hashlib
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from inspector.compare_server import ComparisonHandler, ComparisonJobs


class ServerBoundaryTests(unittest.TestCase):
    def allowed(self, headers, mutation=False):
        handler = SimpleNamespace(headers=headers, server=SimpleNamespace(server_address=("127.0.0.1", 8766)))
        return ComparisonHandler._allowed(handler, mutation)

    def test_only_matching_loopback_origin_can_start_requests(self):
        self.assertTrue(self.allowed({"Host": "127.0.0.1:8766", "Origin": "http://127.0.0.1:8766"}, True))
        self.assertTrue(self.allowed({"Host": "localhost:8766"}, True))
        for headers in (
            {"Host": "evil.example:8766"},
            {"Host": "127.0.0.1:8766", "Origin": "https://evil.example"},
            {"Host": "127.0.0.1:8766", "Origin": "http://127.0.0.1:9999"},
            {"Host": "127.0.0.1:8766", "Origin": "null"},
            {"Host": "127.0.0.1:8766", "Sec-Fetch-Site": "cross-site"},
            {"Host": "127.0.0.1:bad"},
        ):
            with self.subTest(headers=headers):
                self.assertFalse(self.allowed(headers, True))

    def test_error_messages_do_not_include_arbitrary_subprocess_output(self):
        class ExternalFailure(OSError):
            pass
        self.assertNotIn("secret", ComparisonJobs._safe_error(ExternalFailure("secret")))


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # All persistence tests use a synthetic catalog, including when a private
        # capture corpus happens to exist in the developer workspace.
        data = Path(self.temp.name) / "data"
        data.mkdir()
        (data / "catalog.json").write_text(json.dumps({"datasets": [{"id": "synthetic-page"}]}))
        source = {"id": "synthetic-page", "synthetic": True, "variants": {},
                  "dom": {"roots": ["e0"], "nodes": [
                      {"id": "e0", "parent": None, "children": [], "tag": "p",
                       "text": "Synthetic source", "attributes": {}}]}}
        (data / "synthetic-page.json").write_text(json.dumps(source))
        data_patch = patch("inspector.compare_server.DATA", data)
        data_patch.start()
        self.addCleanup(data_patch.stop)
        compact_node = {"id": "d0:1", "parent": None, "children": [], "tag": "p",
                        "text": "Synthetic compact source", "attributes": {"data-r": "d0:1"}}
        self.compact = {"dataset": {"id": "synthetic-page", "synthetic": True,
                                   "variants": {}, "dom": {"roots": ["d0:1"], "nodes": [compact_node]}},
                        "documents": [{"id": "d0", "nodes": [compact_node], "roots": ["d0:1"],
                                       "html": '<p data-r="d0:1">Synthetic compact source</p>'}],
                        "provenance": {"synthetic": True}}
        compact_patch = patch("inspector.compact_input.load_compact", return_value=self.compact)
        self.load_compact = compact_patch.start()
        self.addCleanup(compact_patch.stop)

    @staticmethod
    def finish(jobs, job_id):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = jobs.get(job_id)
            if job["status"] != "running":
                return job
            time.sleep(.01)
        raise AssertionError("Fixture job did not finish")

    def jobs(self, runner):
        return ComparisonJobs(self.temp.name, client_factory=lambda _: SimpleNamespace(), runner=runner)

    def test_both_strategies_use_same_capture_and_client_and_survive_reload(self):
        calls = []

        def run(dataset, strategy, client, model, **kwargs):
            calls.append((id(dataset), strategy, id(client), model, kwargs["region_size"]))
            kwargs["progress"]("Fixture progress")
            return {"strategy": strategy, "fixture": True}

        jobs = self.jobs(run)
        job = jobs.create({"capture_id": "synthetic-page", "strategy": "both", "region_size": 160})
        result = self.finish(jobs, job["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(set(result["results"]), {"whole", "regions"})
        self.assertEqual(len(result["capture_hash"]), 64)
        self.assertEqual(result["capture_hash"], hashlib.sha256(jobs.source(job["id"])).hexdigest())
        self.assertEqual(json.loads(jobs.source(job["id"]))["id"], "synthetic-page")
        self.assertEqual(calls[0][0], calls[1][0])
        self.assertEqual(calls[0][2], calls[1][2])
        self.assertIsNone(jobs.active_job)
        self.assertEqual(self.jobs(run).get(job["id"]), result)

    def test_failed_strategy_keeps_other_result(self):
        def run(dataset, strategy, *args, **kwargs):
            if strategy == "regions":
                raise ValueError("Unknown source ID n999")
            return {"strategy": strategy}
        jobs = self.jobs(run)
        created = jobs.create({"capture_id": "synthetic-page", "strategy": "both"})
        result = self.finish(jobs, created["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("whole", result["results"])
        self.assertEqual(result["errors"], {"regions": "Unknown source ID n999"})

    def test_rejected_model_output_stays_available_without_rendering_a_tree(self):
        def client_factory(directory):
            return SimpleNamespace(directory=directory)
        def run(dataset, strategy, client, *args, **kwargs):
            (client.directory / "model_calls.jsonl").write_text(json.dumps({
                "purpose": "hierarchy-comparison:whole", "response": {"groups": [{"source_ids": ["SOURCE_ID"]}]},
                "request": {"messages": []}, "metadata": {"backend": "ollama"},
            }) + "\n")
            raise ValueError("unknown source ID SOURCE_ID")
        jobs = ComparisonJobs(self.temp.name, client_factory=client_factory, runner=run)
        created = jobs.create({"capture_id": "synthetic-page", "strategy": "whole"})
        result = self.finish(jobs, created["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["results"], {})
        self.assertEqual(result["failed_calls"]["whole"][0]["response"]["groups"][0]["source_ids"], ["SOURCE_ID"])

    def test_single_active_job_and_invalid_requests_never_start_work(self):
        release = threading.Event()
        self.addCleanup(release.set)
        jobs = self.jobs(lambda *args, **kwargs: release.wait(2) or {})
        for request in (None, [], {"capture_id": "../AGENTS", "strategy": "whole"},
                        {"capture_id": "synthetic-page", "strategy": "unknown"},
                        {"capture_id": "synthetic-page", "strategy": "whole", "region_size": True}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                jobs.create(request)
        first = jobs.create({"capture_id": "synthetic-page", "strategy": "whole"})
        with self.assertRaisesRegex(RuntimeError, first["id"]):
            jobs.create({"capture_id": "synthetic-page", "strategy": "whole"})
        release.set()
        self.finish(jobs, first["id"])

    def test_interrupted_jobs_are_reported_as_failed_after_restart(self):
        job_id = "a" * 32
        path = Path(self.temp.name) / job_id
        path.mkdir()
        (path / "job.json").write_text(json.dumps({"id": job_id, "status": "running", "results": {}}))
        recovered = self.jobs(lambda *args: {}).get(job_id)
        self.assertEqual(recovered["status"], "failed")
        self.assertIn("server stopped", recovered["error"])

    def test_local_default_never_constructs_cloud_client(self):
        seen = []
        jobs = ComparisonJobs(self.temp.name, "qwen3.5:0.8b", backend="ollama",
                              runner=lambda data, strategy, client, model, **kwargs: seen.append(model) or {})
        with patch("harness.ollama_model.OllamaClient", return_value=SimpleNamespace()) as local, \
                patch("inspector.compare_server.LabClient", side_effect=AssertionError("cloud client requested")):
            created = jobs.create({"capture_id": "synthetic-page", "strategy": "both"})
            result = self.finish(jobs, created["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["backend"], "ollama")
        self.assertEqual(seen, ["qwen3.5:0.8b", "qwen3.5:0.8b"])
        local.assert_called_once()
        self.assertEqual(jobs.config()["models"][0]["backend"], "ollama")

    def test_explicit_flash_selection_uses_saved_job_model(self):
        seen = []
        jobs = ComparisonJobs(self.temp.name, "qwen3.5:0.8b", backend="ollama",
                              runner=lambda data, strategy, client, model, **kwargs: seen.append(model) or {})
        with patch("inspector.compare_server.LabClient", return_value=SimpleNamespace()) as cloud, \
                patch("harness.ollama_model.OllamaClient", side_effect=AssertionError("local client requested")):
            created = jobs.create({"capture_id": "synthetic-page", "strategy": "whole",
                                   "backend": "lab", "model": "gemini-3.8-flash"})
            result = self.finish(jobs, created["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["backend"], "lab")
        self.assertEqual(seen, ["gemini-3.8-flash"])
        cloud.assert_called_once()

    def test_unconfigured_models_and_backend_pairs_are_rejected(self):
        jobs = ComparisonJobs(self.temp.name, "qwen3.5:0.8b", backend="ollama")
        for backend, model in [("ollama", "uninstalled:latest"), ("ollama", "gemma4:31b-cloud"),
                               ("lab", "qwen3.5:0.8b"), ([], "qwen3.5:0.8b")]:
            with self.subTest(backend=backend, model=model), self.assertRaises(ValueError):
                jobs.create({"capture_id": "synthetic-page", "strategy": "whole", "backend": backend, "model": model})
        self.assertIsNone(jobs.active_job)

    def test_compact_run_uses_a_separate_verified_source_namespace(self):
        seen = []
        def run(prepared, strategy, *args, **kwargs):
            seen.append((id(prepared), strategy, prepared["documents"][0]["html"]))
            return {"strategy": strategy, "input_mode": "compact-budget"}
        jobs = ComparisonJobs(self.temp.name, input_mode="compact-budget", runner=run,
                              client_factory=lambda _: SimpleNamespace())
        job = jobs.create({"capture_id": "synthetic-page", "strategy": "both"})
        result = self.finish(jobs, job["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["input_mode"], "compact-budget")
        self.assertEqual(seen[0][0], seen[1][0])
        source = jobs.source(job["id"])
        self.assertEqual(hashlib.sha256(source).hexdigest(), result["capture_hash"])
        self.assertNotEqual(result["capture_hash"], result["catalog_capture_hash"])
        ids = {node["id"] for node in json.loads(source)["dom"]["nodes"]}
        self.assertIn("d0:1", ids)
        self.load_compact.assert_called_once_with("synthetic-page", profile="budget")
        self.assertNotIn("e0", ids)
        self.assertIn("/source", result["source_url"])
        self.assertTrue(result["input_provenance"])

    def test_unknown_input_mode_rejected_before_job_creation(self):
        jobs = self.jobs(lambda *args, **kwargs: {})
        with self.assertRaisesRegex(ValueError, "input mode"):
            jobs.create({"capture_id": "synthetic-page", "strategy": "both", "input_mode": "unknown"})
        self.assertEqual(jobs.jobs, {})


if __name__ == "__main__":
    unittest.main()
