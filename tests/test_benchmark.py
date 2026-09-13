import copy
import importlib.util
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from harness.benchmark import (
    Benchmark,
    allowed_request,
    list_tasks,
    normalize_ax,
    strict_verdict,
)


class NormalizeAXTests(unittest.TestCase):
    def test_preserves_all_nodes_and_only_uses_verified_browser_ids(self):
        observation = {
            "url": "http://localhost/admin",
            "axtree_object": {
                "nodes": [
                    {
                        "nodeId": "1",
                        "ignored": True,
                        "role": {"value": "none"},
                        "childIds": ["2", "3"],
                    },
                    {
                        "nodeId": "2",
                        "role": {"value": "StaticText"},
                        "name": {"value": "Invoice total: $36.39"},
                    },
                    {
                        "nodeId": "3",
                        "role": {"value": "textbox"},
                        "name": {"value": "Search"},
                        "value": {"value": "invoice"},
                        "browsergym_id": "47",
                    },
                    {
                        "nodeId": "4",
                        "role": {"value": "StaticText"},
                        "name": {"value": "Detached readable root"},
                    },
                ]
            },
        }
        snapshot = normalize_ax(observation, "state1")
        self.assertEqual(len(snapshot["nodes"]), 4)
        self.assertEqual(snapshot["roots"], ["state1:ax:1", "state1:ax:4"])
        self.assertEqual(
            snapshot["nodes"][0]["children"], ["state1:ax:2", "state1:ax:3"]
        )
        self.assertIsNone(snapshot["nodes"][1]["bid"])
        self.assertEqual(snapshot["nodes"][2]["bid"], "47")
        self.assertEqual(snapshot["nodes"][2]["value"], "invoice")
        self.assertTrue(snapshot["nodes"][0]["ignored"])
        self.assertNotEqual(
            snapshot["nodes"][0]["id"],
            normalize_ax(observation, "state2")["nodes"][0]["id"],
        )

    def test_ambiguous_or_dangling_ax_references_fail_closed(self):
        for nodes in (
            [
                {"nodeId": "1", "name": {"value": "First"}},
                {"nodeId": "1", "name": {"value": "Conflicting"}},
            ],
            [{"nodeId": "1", "childIds": ["missing"]}],
        ):
            with self.assertRaises(ValueError):
                normalize_ax({"url": "example", "axtree_object": {"nodes": nodes}}, "s")

    def test_exact_duplicate_records_coalesce_without_altering_raw_capture(self):
        text_node = {
            "nodeId": "-42",
            "role": {"value": "InlineTextBox"},
            "name": {"value": "Readable text"},
        }
        observation = {
            "url": "example",
            "axtree_object": {
                "nodes": [
                    {"nodeId": "1", "childIds": ["-42"]},
                    text_node,
                    copy.deepcopy(text_node),
                    copy.deepcopy(text_node),
                ]
            },
        }
        original = copy.deepcopy(observation)
        snapshot = normalize_ax(observation, "s")
        self.assertEqual(observation, original)
        self.assertEqual(
            [node["id"] for node in snapshot["nodes"]], ["s:ax:1", "s:ax:-42"]
        )
        self.assertEqual(snapshot["nodes"][0]["children"], ["s:ax:-42"])
        self.assertEqual(snapshot["roots"], ["s:ax:1"])
        self.assertEqual(
            snapshot["capture_metadata"],
            {
                "raw_ax_record_count": 4,
                "unique_ax_node_count": 2,
                "exact_duplicate_records_coalesced": 2,
                "duplicated_ax_id_count": 1,
            },
        )


class StrictVerdictTests(unittest.TestCase):
    def test_only_application_origin_requests_are_permitted(self):
        site = "http://localhost:7780/admin"
        self.assertTrue(allowed_request("http://localhost:7780/static/icon.png", site))
        for url in (
            "http://localhost:8877/reset",
            "http://metadata.google.internal/",
            "http://example.com/",
            "file:///etc/passwd",
            "http://localhost:7780.evil.test/admin",
        ):
            self.assertFalse(allowed_request(url, site))

    def test_partial_rewards_never_become_success(self):
        result = {
            "status": "failure",
            "score": 0,
            "evaluators_results": [
                {"status": "success", "score": 1, "expected": "private"},
                {"status": "failure", "score": 0},
            ],
        }
        self.assertFalse(strict_verdict(result)["strict_success"])
        self.assertNotIn("strict_success", result)
        self.assertEqual(
            strict_verdict(result)["evaluators_results"][0]["expected"], "private"
        )

    def test_only_complete_official_pass_succeeds(self):
        result = {
            "status": "success",
            "score": 1,
            "evaluators_results": [{"status": "success", "score": 1}],
        }
        self.assertTrue(strict_verdict(result)["strict_success"])
        for changes in (
            {"status": "error"},
            {"score": 0.5},
            {"evaluators_results": []},
            {"evaluators_results": [{"status": "error", "score": 1}]},
        ):
            self.assertFalse(strict_verdict(result | changes)["strict_success"])

    def test_public_descriptors_do_not_leak_evaluation(self):
        with patch(
            "harness.benchmark._dataset",
            return_value=[
                {"task_id": 157, "intent": "View customers", "eval": "private"}
            ],
        ):
            self.assertEqual(
                list_tasks([157]), [{"task_id": 157, "intent": "View customers"}]
            )
        with self.assertRaises(ValueError):
            Benchmark(470)


class UpstreamIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("SEMANTIC_BROWSER_INTEGRATION") == "1",
        "Opt-in delayed-grid browser regression",
    )
    def test_capture_settles_delayed_grid_and_rejects_persistent_loading(self):
        from browsergym.core import _get_global_playwright, _set_global_playwright
        from browsergym.core.env import BrowserEnv
        from browsergym.core.task import OpenEndedTask

        class DelayedGridHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/grid":
                    time.sleep(1.2)
                    content = (
                        b"<h1>Invoices ready</h1><p>Invoice fixture value 12.34</p>"
                    )
                else:
                    content = b"""<div id="mask" data-role="spinner" class="admin__data-grid-loading-mask"><span>Loading grid</span></div>
                    <main hidden id="result"></main>
                    <button id="reload" onclick="loadGrid()">Reload invoices</button>
                    <button id="stall" onclick="mask.style.display='block'">Stall grid</button>
                    <script>function loadGrid(){mask.style.display='block';result.hidden=true;
                    fetch('/grid').then(r=>r.text()).then(html=>{result.innerHTML=html;result.hidden=false;mask.style.display='none'})}loadGrid()</script>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), DelayedGridHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        benchmark = Benchmark(157)
        benchmark._env = BrowserEnv(
            task_entrypoint=OpenEndedTask,
            task_kwargs={
                "start_url": f"http://127.0.0.1:{server.server_port}/",
                "goal": "Fixture",
            },
            slow_mo=0,
            headless=True,
        )
        try:
            observation, _ = benchmark._env.reset(seed=42)
            self.assertFalse(
                any(
                    n.get("name", {}).get("value") == "Invoices ready"
                    for n in observation["axtree_object"]["nodes"]
                )
            )
            snapshot = benchmark._capture(observation)
            self.assertTrue(
                any(n["name"] == "Invoices ready" for n in snapshot["nodes"])
            )
            self.assertEqual(
                snapshot["capture_metadata"]["settling"]["status"], "ready"
            )
            reload_node = next(
                n
                for n in snapshot["nodes"]
                if n["role"] == "button" and n["name"] == "Reload invoices"
            )
            next_snapshot = benchmark.act(
                {
                    "kind": "click",
                    "bid": reload_node["bid"],
                    "snapshot_id": snapshot["snapshot_id"],
                }
            )
            self.assertTrue(
                any(n["name"] == "Invoices ready" for n in next_snapshot["nodes"])
            )
            self.assertNotEqual(snapshot["snapshot_id"], next_snapshot["snapshot_id"])
            self.assertEqual(
                benchmark.raw_capture()["axtree_object"],
                benchmark._observation["axtree_object"],
            )

            # A real click error still reaches the recorder after recapture.
            reload_node = next(
                n
                for n in next_snapshot["nodes"]
                if n["role"] == "button" and n["name"] == "Reload invoices"
            )
            benchmark._env.page.locator("#reload").evaluate(
                "element => element.disabled = true"
            )
            error_snapshot = benchmark.act({"kind": "click", "bid": reload_node["bid"]})
            self.assertIn("TimeoutError", benchmark.last_action_error)
            self.assertEqual(
                benchmark.last_action_error, benchmark._env.last_action_error
            )
            self.assertEqual(
                error_snapshot["capture_metadata"]["settling"]["status"], "ready"
            )

            from harness.benchmark import CaptureNotReady

            stall_node = next(
                n
                for n in error_snapshot["nodes"]
                if n["role"] == "button" and n["name"] == "Stall grid"
            )
            with (
                patch("harness.benchmark.SETTLING_TIMEOUT_MS", 600),
                patch("harness.benchmark.NETWORK_IDLE_TIMEOUT_MS", 200),
            ):
                with self.assertRaises(CaptureNotReady) as failure:
                    benchmark.act({"kind": "click", "bid": stall_node["bid"]})
            self.assertEqual(
                failure.exception.capture_metadata["settling"]["status"],
                "capture_not_ready",
            )
            self.assertTrue(
                failure.exception.capture_metadata["settling"]["loading_mask_timeout"]
            )
            self.assertIsNone(benchmark._snapshot)
            self.assertIn("axtree_object", benchmark.raw_capture())
        finally:
            benchmark.close()
            server.shutdown()
            server.server_close()
            _get_global_playwright().stop()
            _set_global_playwright(None)

    @unittest.skipUnless(
        os.environ.get("SEMANTIC_BROWSER_INTEGRATION") == "1",
        "Opt-in full adapter fixture with pinned browser and tokenizer installed",
    )
    def test_full_adapter_scores_only_at_finish_and_requires_navigation(self):
        from browsergym.core import _get_global_playwright, _set_global_playwright

        class FixtureHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b'<main><h1>Fixture admin</h1><a href="/admin/customer/index/">Customers</a></main>'
                )

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        fixture_environment = {
            "WA_SHOPPING_ADMIN": f"http://127.0.0.1:{server.server_port}/admin",
            "PW_EXTRA_HEADERS": "",
            "SEMANTIC_READER_EXTRA_HEADERS": '{"X-M2-Admin-Auto-Login":"fixture-only"}',
        }
        benchmark = Benchmark(157)
        try:
            with patch.dict(os.environ, fixture_environment):
                for navigate_first in (False, True):
                    snapshot = benchmark.reset()
                    if navigate_first:
                        node = next(
                            n
                            for n in snapshot["nodes"]
                            if n["role"] == "link" and n["name"] == "Customers"
                        )
                        benchmark.act(
                            {
                                "kind": "click",
                                "bid": node["bid"],
                                "snapshot_id": snapshot["snapshot_id"],
                            }
                        )
                    verdict = benchmark.finish(
                        {
                            "task_type": "NAVIGATE",
                            "status": "SUCCESS",
                            "retrieved_data": None,
                        }
                    )
                    self.assertIs(verdict["strict_success"], navigate_first)
                    self.assertNotEqual(verdict["status"], "error")
        finally:
            benchmark.close()
            server.shutdown()
            server.server_close()
            _get_global_playwright().stop()
            _set_global_playwright(None)

    @unittest.skipUnless(
        importlib.util.find_spec("webarena_verified"),
        "Install infra/benchmark-requirements.txt to exercise the official evaluator",
    )
    def test_official_retrieval_evaluator_accepts_oracle_and_rejects_wrong_answer(self):
        # This fixture validates the scorer, not agent task performance. The
        # packaged hidden answer never enters any model context or output log.
        from webarena_verified.api import (
            WebArenaVerifiedDataReader,
            WebArenaVerifiedEvaluator,
        )
        from webarena_verified.types.config import (
            EnvironmentConfig,
            WebArenaVerifiedConfig,
        )
        from webarena_verified.types.tracing import NetworkTrace

        config = WebArenaVerifiedConfig(
            environments={
                "shopping_admin": EnvironmentConfig(
                    urls=["http://localhost:7780/admin"]
                )
            }
        )
        reader = WebArenaVerifiedDataReader(config)
        evaluator = WebArenaVerifiedEvaluator(config=config, reader=reader)
        task = reader.get_task_by_id(94)
        oracle = task.eval[0].expected.model_dump(mode="json")
        trace = NetworkTrace(
            is_playwright=False, src_file=Path("scorer-fixture"), events=()
        )
        incorrect = {
            "task_type": "RETRIEVE",
            "status": "SUCCESS",
            "retrieved_data": [-999],
        }
        for response, expected in ((oracle, True), (incorrect, False)):
            verdict = strict_verdict(
                evaluator.evaluate_task(
                    task_id=94, agent_response=response, network_trace=trace
                )
            )
            self.assertIs(verdict["strict_success"], expected)
            self.assertNotEqual(verdict["status"], "error")

    @unittest.skipUnless(
        os.environ.get("SEMANTIC_BROWSER_INTEGRATION") == "1",
        "Opt-in real Chromium fixture",
    )
    def test_real_ax_bids_resolve_to_their_marked_dom_elements(self):
        from browsergym.core.observation import (
            _post_extract,
            _pre_extract,
            extract_merged_axtree,
        )
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(
                    '<main><h1>Invoices</h1><p>Readable total 12.34</p><label>Search<input value="saved"></label><button>Open record</button></main>'
                )
                _pre_extract(page, tags_to_mark="all")
                ax = extract_merged_axtree(page)
                _post_extract(page)
                snapshot = normalize_ax(
                    {"url": page.url, "axtree_object": ax}, "fixture"
                )
                self.assertEqual(len(snapshot["nodes"]), len(ax["nodes"]))
                self.assertTrue(
                    any(
                        n["role"] == "StaticText" and "12.34" in n["name"]
                        for n in snapshot["nodes"]
                    )
                )
                for node in snapshot["nodes"]:
                    if node["bid"] is not None:
                        self.assertEqual(
                            page.locator(f'[bid="{node["bid"]}"]').count(), 1
                        )
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
