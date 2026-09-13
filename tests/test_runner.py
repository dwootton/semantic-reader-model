import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from harness.model import ACCOUNT, PROJECT
from harness.run import RESUME_PROTOCOL_FIELDS, main, prepare_resume, reset_site, save, validate_resume


class SiteResetTests(unittest.TestCase):
    def test_retries_connection_reset_while_new_container_starts(self):
        ready = MagicMock()
        ready.__enter__.return_value.status = 200
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("harness.run.Path.read_text", return_value="am1n3e/webarena-verified-shopping_admin@sha256:test"),
                patch("harness.run.subprocess.run") as command,
                patch("harness.run.urllib.request.urlopen", side_effect=[ConnectionResetError(104, "starting"), ready]) as request,
                patch("harness.run.time.sleep") as sleep,
            ):
                result = reset_site(Path(directory) / "reset.log")
        self.assertEqual(result["method"], "container_recreation")
        self.assertEqual(command.call_count, 2)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(3)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source, self.target = Path(self.temp.name) / "c", Path(self.temp.name) / "d"
        self.config = {
            "tasks": "94", "conditions": "source,purpose", "models": "navigator",
            "generator": "flash", "judge": "pro", "max_steps": 28,
            "max_browser_actions": 8, "page_size": 12, "request_interval": 10.0,
            "max_attempts": 6, "seed": 42, "max_calls": 100, "max_minutes": 150,
        }
        self.args = SimpleNamespace(**{**self.config, "max_calls": 95})
        self.task = {"task_id": 94, "intent": "Find invoice"}
        self.specs = [{"episode_id": f"t94-{condition}-navigator", "task": self.task,
                       "condition": condition, "model": "navigator"}
                      for condition in ("source", "purpose")]
        self.run = {"run_id": "c", "status": "stopped_after_repeated_errors",
                    "config": self.config, "model_calls": 5, "episodes": self.specs,
                    "account": ACCOUNT, "project": PROJECT}
        save(self.source / "run.json", self.run)
        self.episode = {
            **self.specs[0], "status": "completed", "evaluation": {"strict_success": True},
            "steps": [{"step": 1, "observation": {"items": []},
                       "decision": {"purpose": "Find invoice", "expectation": "Invoice value",
                                    "cue_ids": [], "action": {"op": "finish", "answer": {}}},
                       "model_call": {"call": 1, "model_version": "navigator"},
                       "result": {"finished": True}}], "totals": {"navigation_moves": 3},
        }
        self.annotation = {
            "status": "complete", "judge_model": "pro",
            "coverage": {"total_steps": 1, "included_steps": [1], "truncated": False},
            "independent_evidence": {
                "status": "valid", "metadata": {"call": 2, "model_version": "pro"},
                "output": {"segments": [{"step_ids": [1], "effect": "uncertain",
                    "observed_behavior": "Finished", "evidence": [{"step": 1, "channel": "action", "detail": "finish"}],
                    "hierarchy_hypothesis": "Unresolved", "alternative_explanation": "Task is simple",
                    "uncertainty": "One step"}], "open_observations": [], "limitations": []}},
            "with_self_report": {
                "status": "valid", "metadata": {"call": 3, "model_version": "pro"},
                "output": {"comparisons": [{"segment_index": 0, "step_ids": [1], "agreement": "unresolved",
                    "self_report_evidence": [{"step": 1, "field": "purpose", "detail": "Find invoice"}],
                    "interpretation": "Unresolved", "uncertainty": "Self-report only"}],
                    "open_observations": [], "limitations": []}},
        }
        self.write_episode(self.specs[0], self.episode, self.annotation)
        self.write_episode(self.specs[1], {**self.specs[1], "status": "error", "steps": []}, None)
        (self.source / "model_calls.jsonl").write_text('{"call": 1}\n')

    def write_episode(self, spec, episode, annotation):
        folder = self.source / "episodes" / spec["episode_id"]
        save(folder / "episode.json", episode)
        if annotation is not None:
            save(folder / "annotation.json", annotation)

    def test_runner_preserves_complete_episode_without_executing_it_and_reruns_errors(self):
        argv = ["run", "--output", str(self.target), "--resume-from", str(self.source)]
        for key, value in vars(self.args).items():
            argv.extend(["--" + key.replace("_", "-"), str(value)])

        def execute(spec, root, *_):
            episode = {**self.episode, **spec}
            save(root / "episodes" / spec["episode_id"] / "episode.json", episode)
            return episode

        with (patch("sys.argv", argv), patch("harness.run.list_tasks", return_value=[self.task]),
              patch("harness.run.LabClient", return_value=SimpleNamespace(calls=0, usage={})),
              patch("harness.run.run_episode", side_effect=execute) as execute_mock,
              patch("harness.annotate.annotate_episode", return_value=self.annotation),
              patch("harness.annotate.create_report") as report, patch("builtins.print")):
            main()
        self.assertEqual(execute_mock.call_count, 1)
        self.assertEqual(execute_mock.call_args.args[0]["episode_id"], self.specs[1]["episode_id"])
        run = json.loads((self.target / "run.json").read_text())
        self.assertEqual(run["completed_episodes"], 2)
        self.assertEqual(len(run["episodes"]), 2)
        self.assertEqual(run["status"], "completed")
        report.assert_called_once_with(self.target)
        copied = json.loads((self.target / "episodes" / self.specs[0]["episode_id"] / "episode.json").read_text())
        self.assertEqual(copied["totals"], self.episode["totals"])
        self.assertEqual(copied["origin_run"], "c")
        self.assertEqual(copied["steps"][0]["model_call"]["origin_run"], "c")
        self.assertNotIn("origin_run", json.loads((self.source / "episodes" / self.specs[0]["episode_id"] / "episode.json").read_text()))

    def test_protocol_or_experiment_changes_are_rejected(self):
        for key in (*RESUME_PROTOCOL_FIELDS, "tasks", "conditions", "models"):
            with self.subTest(key=key):
                args = copy.deepcopy(self.args)
                setattr(args, key, "changed")
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    validate_resume(self.source, self.target, args, self.specs)
        changed_specs = copy.deepcopy(self.specs)
        changed_specs[0]["task"]["intent"] = "A different task"
        with self.assertRaisesRegex(ValueError, "specifications"):
            validate_resume(self.source, self.target, self.args, changed_specs)

    def test_missing_partial_or_invalid_annotations_are_not_reused(self):
        for corruption in ("missing", "partial", "coverage", "evidence"):
            with self.subTest(corruption=corruption):
                annotation = copy.deepcopy(self.annotation)
                if corruption == "missing":
                    annotation = {}
                elif corruption == "partial":
                    annotation["status"] = "partial"
                elif corruption == "coverage":
                    annotation["coverage"]["included_steps"] = []
                else:
                    annotation["independent_evidence"]["output"]["segments"][0]["evidence"][0]["step"] = 99
                self.write_episode(self.specs[0], self.episode, annotation)
                manifest = prepare_resume(self.source, self.target / corruption, self.args, self.specs)
                self.assertEqual(manifest["preserved_episodes"], [])
                self.assertEqual(manifest["annotation_backlog"], [])

    def test_opt_in_backlog_copies_navigation_and_archives_partial_annotation(self):
        for state in ("missing", "partial"):
            with self.subTest(state=state):
                spec = self.specs[1]
                episode = {**self.episode, **spec, "evaluation": {"strict_success": False}}
                annotation = copy.deepcopy(self.annotation)
                annotation["status"] = "partial"
                annotation["with_self_report"] = {"status": "error", "error": "HTTP 429"}
                self.write_episode(spec, episode, annotation if state == "partial" else None)
                target = self.target / state
                manifest = prepare_resume(self.source, target, self.args, self.specs,
                                          include_annotation_backlog=True)
                self.assertEqual(manifest["preserved_episodes"], [self.specs[0]["episode_id"]])
                self.assertEqual(manifest["annotation_backlog"], [spec["episode_id"]])
                self.assertEqual(manifest["rerun_episodes"], {})
                folder = target / "episodes" / spec["episode_id"]
                copied = json.loads((folder / "episode.json").read_text())
                self.assertTrue(copied["annotation_pending"])
                self.assertEqual(copied["steps"][0]["decision"], episode["steps"][0]["decision"])
                self.assertEqual(copied["evaluation"], episode["evaluation"])
                self.assertEqual(copied["totals"], episode["totals"])
                self.assertEqual(copied["steps"][0]["model_call"]["origin_run"], "c")
                self.assertFalse((folder / "annotation.json").exists())
                archived = folder / "annotation-before-retry.json"
                self.assertEqual(archived.exists(), state == "partial")
                if archived.exists():
                    previous = json.loads(archived.read_text())
                    self.assertEqual(previous["status"], "partial")
                    self.assertEqual(previous["independent_evidence"]["metadata"]["origin_run"], "c")
                original = json.loads((self.source / "episodes" / spec["episode_id"] / "episode.json").read_text())
                self.assertNotIn("annotation_pending", original)

    def test_opt_in_backlog_still_reruns_incomplete_navigation_and_unavailable_verdicts(self):
        for status in ("error", "running", "not_started", "evaluation_error", "completed"):
            with self.subTest(status=status):
                episode = {**self.episode, "status": status, "evaluation": {"strict_success": None}}
                self.write_episode(self.specs[0], episode, {})
                manifest = prepare_resume(self.source, self.target / status, self.args, self.specs,
                                          include_annotation_backlog=True)
                self.assertEqual(manifest["preserved_episodes"], [])
                self.assertEqual(manifest["annotation_backlog"], [])
                self.assertIn(self.specs[0]["episode_id"], manifest["rerun_episodes"])

    def test_budget_ended_research_episode_is_reused_with_complete_annotations(self):
        episode = {**self.episode, "status": "step_budget", "evaluation": None}
        self.write_episode(self.specs[0], episode, self.annotation)
        manifest = prepare_resume(self.source, self.target, self.args, self.specs)
        self.assertEqual(manifest["preserved_episodes"], [self.specs[0]["episode_id"]])

    def test_cache_origins_ledgers_and_hashes_are_preserved(self):
        for key, metadata in (("a" * 64, {"call": 1, "model_version": "flash", "origin_run": "b"}),
                              ("b" * 64, {"call": 4, "model_version": "flash"})):
            save(self.source / "projection_cache" / f"{key}.json", {"projection": {"groups": []}, "metadata": metadata})
        manifest = prepare_resume(self.source, self.target, self.args, self.specs)
        for key, origin in (("a" * 64, "b"), ("b" * 64, "c")):
            cache = json.loads((self.target / "projection_cache" / f"{key}.json").read_text())
            self.assertEqual(cache["metadata"]["origin_run"], origin)
            self.assertIn(f"projection_cache/{key}.json", manifest["source_artifact_hashes"])
        self.assertEqual((self.target / "provenance/c/model_calls.jsonl").read_bytes(),
                         (self.source / "model_calls.jsonl").read_bytes())
        self.assertIn("harness/run.py", manifest["source_hashes"])
        self.assertIn("Transport/runtime recovery", manifest["comparison_note"])

    def test_existing_run_and_expanded_call_budget_are_rejected(self):
        self.args.max_calls = 96
        with self.assertRaisesRegex(ValueError, "95 new model calls"):
            validate_resume(self.source, self.target, self.args, self.specs)
        save(self.target / "run.json", {"retain": True})
        with self.assertRaisesRegex(ValueError, "never replaced"):
            validate_resume(self.source, self.target, self.args, self.specs)
        self.assertEqual(json.loads((self.target / "run.json").read_text()), {"retain": True})


if __name__ == "__main__":
    unittest.main()
