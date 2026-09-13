import argparse
from concurrent.futures import Future
import json
import os
from pathlib import Path
import queue
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from harness import parallel_run


class ControlledPool:
    def __init__(self, failures=(), invalid=()):
        self.active = {}
        self.submitted = []
        self.finished = []
        self.widths = []
        self.failures = failures
        self.invalid = invalid

    def submit(self, job, spec):
        future = Future()
        self.active[future] = spec
        self.submitted.append(spec["episode_id"])
        self.widths.append(len(self.active))
        return future

    def finish_one(self, futures, **kwargs):
        future = next(iter(futures))
        spec = self.active.pop(future)
        episode_id = spec["episode_id"]
        self.finished.append(episode_id)
        future.set_result({"episode_id": episode_id, "status": "completed",
                           "infrastructure_error": episode_id in self.failures,
                           "annotation_valid": episode_id not in self.invalid})
        return {future}, set(futures) - {future}


class ParallelControllerTests(unittest.TestCase):
    def exercise(self, pool, count=10, preserved=(), rate=0, budget_after=None):
        class Budget:
            def usage(self):
                used = 100 if budget_after is not None and len(pool.finished) >= budget_after else 0
                return {"reserved_calls": used, "max_calls": 100}
        specs = [{"episode_id": str(index)} for index in range(count)]
        run = {"episodes": specs, "preserved_episodes": list(preserved),
               "completed_episodes": len(preserved)}
        args = argparse.Namespace(max_calls=100, deadline=time.monotonic() + 1000, test_workers=4)
        def logs(root):
            attempts = 4 * len(pool.finished)
            return {"attempts": attempts, "http_429": int(attempts * rate), "usage": {}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(parallel_run, "wait", side_effect=pool.finish_one), \
                patch.object(parallel_run, "aggregate_logs", side_effect=logs):
            results = parallel_run.coordinate(pool, Path(directory), args, run, Budget(), job=None)
        return run, results

    def test_two_then_four_and_exactly_once_with_preserved_specs(self):
        pool = ControlledPool()
        run, results = self.exercise(pool, preserved=("0", "1"))
        self.assertEqual(pool.widths[:2], [1, 2])
        # No third submission until both first-batch jobs finish: next width is one.
        self.assertEqual(pool.widths[2:6], [1, 2, 3, 4])
        self.assertEqual(pool.submitted, [str(i) for i in range(2, 10)])
        self.assertEqual(len(set(pool.submitted)), len(results))
        self.assertEqual(run["completed_episodes"], 10)
        self.assertEqual([stage["workers"] for stage in run["concurrency_stages"]], [2, 4])
        self.assertEqual(run["four_worker_test"]["status"], "passed")
        self.assertEqual(run["status"], "completed")

    def test_high_rejection_rate_keeps_two_and_explains(self):
        pool = ControlledPool()
        run, _ = self.exercise(pool, rate=0.5)
        self.assertLessEqual(max(pool.widths), 2)
        self.assertEqual(run["four_worker_test"]["status"], "not_attempted")
        self.assertIn("429", run["four_worker_test"]["reason"])

    def test_invalid_annotations_block_ramp(self):
        pool = ControlledPool(invalid={"0"})
        run, _ = self.exercise(pool)
        self.assertLessEqual(max(pool.widths), 2)
        self.assertIn("annotations", run["four_worker_test"]["reason"])

    def test_infrastructure_error_in_four_worker_stage_demotes(self):
        pool = ControlledPool(failures={"3"})
        run, _ = self.exercise(pool, count=14)
        self.assertEqual([stage["workers"] for stage in run["concurrency_stages"]], [2, 4, 2])
        self.assertEqual(run["four_worker_test"]["status"], "reduced_to_two")
        self.assertLessEqual(max(pool.widths[-3:]), 2)

    def test_shared_budget_prevents_new_submissions_but_preserves_active_work(self):
        pool = ControlledPool()
        run, results = self.exercise(pool, budget_after=1)
        self.assertEqual(pool.submitted, ["0", "1"])
        self.assertEqual(len(results), 2)
        self.assertEqual(run["status"], "budget_exhausted")
        self.assertEqual(run["four_worker_test"]["status"], "not_attempted")

    def test_reject_duplicate_specs_and_unknown_preserved_ids(self):
        with self.assertRaises(ValueError):
            parallel_run.pending_specs([{"episode_id": "x"}, {"episode_id": "x"}], [])
        with self.assertRaises(ValueError):
            parallel_run.pending_specs([{"episode_id": "x"}], ["y"])

    def test_process_claim_has_unique_fixed_origin_and_overrides_parent_environment(self):
        ids = queue.Queue()
        ids.put(1)
        ids.put(4)
        with patch.dict(os.environ, {"WA_SHOPPING_ADMIN": "http://localhost:7780/admin", "WA_REDDIT": "other"}):
            first_id, first = parallel_run.claim_worker(ids)
            self.assertEqual(os.environ["WA_SHOPPING_ADMIN"], first.admin_url)
            self.assertEqual(os.environ["WA_REDDIT"], "todo")
            last_id, last = parallel_run.claim_worker(ids)
            self.assertEqual((first_id, last_id), (1, 4))
            self.assertEqual((first.port, last.port), (7782, 7788))
            self.assertEqual(os.environ["WA_SHOPPING_ADMIN"], last.admin_url)
            self.assertNotEqual(first.name, last.name)

    def test_worker_persists_navigation_annotation_and_idle_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker_dir = root / "workers/worker-1"
            worker_dir.mkdir(parents=True)
            site = parallel_run.SiteConfig("webarena-verified-shopping_admin-worker-1", 7782, 7783)
            args = argparse.Namespace(deadline=time.monotonic() + 100, max_calls=100, judge="judge", site_config=site)
            budget = MagicMock()
            budget.usage.return_value = {"reserved_calls": 1}
            observed = []
            def navigate(spec, destination, client, factory, settings):
                observed.append(json.loads((worker_dir / "status.json").read_text())["phase"])
                self.assertEqual(settings.site_config, site)
                return {**spec, "status": "completed", "steps": [{"step": 1}]}
            def annotate(*unused):
                observed.append(json.loads((worker_dir / "status.json").read_text())["phase"])
                return {"status": "complete"}
            worker = (1, site, root, worker_dir, args, budget, object(), object())
            with patch.object(parallel_run, "_WORKER", worker), \
                    patch.object(parallel_run, "run_episode", side_effect=navigate), \
                    patch("harness.annotate.annotate_episode", side_effect=annotate), \
                    patch.object(parallel_run, "complete_annotation", return_value=True):
                result = parallel_run.execute_episode({"episode_id": "sample"})
            self.assertEqual(observed, ["navigation", "annotation"])
            self.assertTrue(result["annotation_valid"])
            self.assertEqual(json.loads((worker_dir / "status.json").read_text())["phase"], "idle")
            episode = json.loads((root / "episodes/sample/episode.json").read_text())
            self.assertEqual(episode["execution"]["origin"], "http://localhost:7782")

    def test_annotation_backlog_uses_existing_navigation_and_retains_pending_on_failure(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                worker_dir = root / "workers/worker-1"
                worker_dir.mkdir(parents=True)
                site = parallel_run.SiteConfig("webarena-verified-shopping_admin-worker-1", 7782, 7783)
                args = argparse.Namespace(deadline=time.monotonic() + 100, max_calls=100, judge="judge", site_config=site)
                budget = MagicMock()
                budget.usage.return_value = {"reserved_calls": 1}
                original = {"episode_id": "sample", "status": "completed", "steps": [{"step": 1}],
                            "annotation_pending": True, "execution": {"worker": "original"}}
                episode_path = root / "episodes/sample/episode.json"
                parallel_run.save(episode_path, original)
                worker = (1, site, root, worker_dir, args, budget, object(), object())
                with patch.object(parallel_run, "_WORKER", worker), \
                        patch.object(parallel_run, "run_episode") as navigate, \
                        patch("harness.annotate.annotate_episode", return_value={"status": "complete"}) as annotate, \
                        patch.object(parallel_run, "complete_annotation", return_value=valid):
                    result = parallel_run.execute_episode({"episode_id": "sample"})
                navigate.assert_not_called()
                annotate.assert_called_once()
                self.assertTrue(result["annotation_only"])
                episode = json.loads(episode_path.read_text())
                self.assertEqual(episode["steps"], original["steps"])
                self.assertEqual(episode["execution"], original["execution"])
                self.assertEqual(episode["annotation_worker"]["worker"], 1)
                self.assertEqual("annotation_pending" in episode, not valid)

    def test_annotation_backlog_scheduled_after_all_fresh_navigation(self):
        specs = [{"episode_id": str(index)} for index in range(6)]
        pending = parallel_run.pending_specs(specs, ["1"], ["0", "3"])
        self.assertEqual([spec["episode_id"] for spec in pending], ["2", "4", "5", "0", "3"])
        healthy, reason = parallel_run.stage_health(
            [{"annotation_only": True, "infrastructure_error": False, "annotation_valid": True}] * 2,
            {"attempts": 4, "http_429": 0})
        self.assertFalse(healthy)
        self.assertIn("navigation", reason)

    def test_log_merge_ignores_split_utf8_tail_but_rejects_malformed_complete_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = root / "workers/worker-1"
            worker.mkdir(parents=True)
            ledger = worker / "model_calls.jsonl"
            record = json.dumps({"call": 1}).encode() + b"\n"
            ledger.write_bytes(record + b'{"text":"' + bytes([0xE2, 0x82]))
            self.assertEqual(parallel_run.aggregate_logs(root)["attempts"], 1)
            ledger.write_bytes(record + b'{"call":bad}\n')
            with self.assertRaises(json.JSONDecodeError):
                parallel_run.aggregate_logs(root)

    def test_log_merge_preserves_global_ids_usage_and_skips_partial_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for worker in (1, 2):
                (root / "workers" / f"worker-{worker}").mkdir(parents=True)
            a = {"call": 2, "error": {"status": 429}}
            b = {"call": 1, "response": {"usageMetadata": {"totalTokenCount": 8}}}
            (root / "workers/worker-1/model_calls.jsonl").write_text(json.dumps(a) + "\n" + '{"call":3')
            (root / "workers/worker-2/model_calls.jsonl").write_text(json.dumps(b) + "\n")
            stats = parallel_run.aggregate_logs(root)
            merged = [json.loads(line) for line in (root / "model_calls.jsonl").read_text().splitlines()]
            self.assertEqual([event["call"] for event in merged], [1, 2])
            self.assertEqual(stats, {"attempts": 2, "http_429": 1, "usage": {"totalTokenCount": 8}})


if __name__ == "__main__":
    unittest.main()
