"""Evidence blinding, citation validation, and incomplete-run reporting."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from harness.annotate import (
    MAX_PROMPT_CHARS, AnnotationError, annotate_episode, create_report,
    evidence_payload, validate_evidence,
)


def episode():
    return {
        "episode_id": "hidden-episode", "task": {"id": 123, "intent": "Find the invoice"},
        "condition": "hidden-condition", "model": "hidden-model", "status": "finished",
        "evaluation": {"strict_success": True, "expected": "hidden-evaluator"},
        "totals": {"navigation_moves": 2, "words": 36, "choices": 7},
        "steps": [
            {"step": 1, "observation": {"items": [{"id": "g:account", "label": "Account"}]},
             "decision": {"purpose": "hidden-purpose", "expectation": "hidden-expectation",
                          "cue_ids": ["hidden-cue"], "action": {"op": "expand", "target": "g:account"}},
             "result": {"items": [{"id": "s:profile", "label": "Profile"}], "reward": "hidden-reward"}},
            {"step": 2, "observation": {"items": [{"id": "s:profile", "label": "Profile"}]},
             "decision": {"purpose": "Return", "expectation": "See other branches", "cue_ids": [], "action": {"op": "up"}},
             "result": {"items": [{"id": "g:account", "label": "Account"}]}},
        ],
    }


def evidence():
    return {"segments": [{"step_ids": [1, 2], "effect": "uncertain",
            "observed_behavior": "Opened Account, then returned.",
            "evidence": [{"step": 1, "channel": "observation", "detail": "Account is a visible label."},
                         {"step": 2, "channel": "action", "detail": "The action is up."}],
            "hierarchy_hypothesis": "The label may have been insufficiently specific.",
            "alternative_explanation": "The visit may be verification.", "uncertainty": "Intent is not observed."}],
            "open_observations": [], "limitations": ["One episode."]}


def comparison():
    return {"comparisons": [{"segment_index": 0, "agreement": "adds_context", "step_ids": [1],
            "self_report_evidence": [{"step": 1, "field": "expectation", "detail": "The navigator stated an expectation."}],
            "interpretation": "A self-report adds context but is unverified.", "uncertainty": "Explanation may be unfaithful."}],
            "open_observations": [], "limitations": []}


class FakeClient:
    def __init__(self, responses=None):
        self.responses = responses or [evidence(), comparison()]
        self.requests = []

    def generate(self, model, system, prompt, *, purpose, max_tokens):
        self.requests.append((model, system, json.loads(prompt), purpose, max_tokens))
        return copy.deepcopy(self.responses[len(self.requests) - 1]), {"usage": {"totalTokenCount": 42}}


class AnnotationTests(unittest.TestCase):
    def test_first_pass_blinds_explanations_outcome_and_identities(self):
        data = episode()
        original = copy.deepcopy(data)
        client = FakeClient()
        result = annotate_episode(data, client, "judge")
        self.assertEqual(result["status"], "complete")
        first = json.dumps(client.requests[0][2])
        for hidden in ("hidden-episode", "hidden-condition", "hidden-model", "hidden-evaluator",
                       "hidden-purpose", "hidden-expectation", "hidden-cue", "hidden-reward"):
            self.assertNotIn(hidden, first)
        self.assertIn("g:account", first)
        self.assertIn("observation_ref", first)
        second = json.dumps(client.requests[1][2])
        self.assertIn("hidden-expectation", second)
        self.assertNotIn("hidden-evaluator", second)
        self.assertEqual(data, original)
        self.assertEqual(result["independent_evidence"]["validation"]["evidence_entries"], 2)
        self.assertEqual(len(result["usage"]), 2)

    def test_observations_stored_once_with_stable_channels_and_error_fallback(self):
        data = episode()
        payload = evidence_payload(data)
        first, second = payload["steps"]
        self.assertEqual(first["result"], second["observation"])
        self.assertNotIn("next_observation", first)
        self.assertEqual(len(payload["observations"]), 2)
        output = evidence()
        output["segments"][0]["evidence"][0]["channel"] = "result"
        validate_evidence(output, payload)
        data["steps"][0]["result"] = {"observation": data["steps"][1]["observation"],
                                      "browser_action": {"kind": "click", "bid": "42"},
                                      "state_changed": True}
        payload = evidence_payload(data)
        first, second = payload["steps"]
        self.assertEqual(first["result"]["observation"], second["observation"])
        self.assertEqual(first["result"]["browser_action"]["bid"], "42")
        self.assertNotIn("next_observation", first)
        data["steps"][0]["result"] = {"error": "Undisclosed target"}
        payload = evidence_payload(data)
        first, second = payload["steps"]
        self.assertEqual(first["next_observation"], second["observation"])
        self.assertEqual(first["result"], {"error": "Undisclosed target"})
        output["segments"][0]["evidence"][0]["channel"] = "next_observation"
        validate_evidence(output, payload)

    def test_full_28_step_12_item_trace_fits_both_passes(self):
        data = episode()
        views = []
        for page in range(29):
            snapshot_id = f"{page:032x}"
            items = [{"id": f"s:{snapshot_id}:ax:{10000 + index}", "kind": "source",
                      "label": f"Invoice {10000 + index} — September statement — awaiting customer payment",
                      "role": "link", "value": "", "expandable": False, "actions": ["activate"]}
                     for index in range(12)]
            views.append({"snapshot_id": snapshot_id, "url": "http://localhost:7780/admin/orders",
                          "location": {"kind": "controls", "target": None, "label": "controls", "depth": 2},
                          "items": items, "page": page + 1, "pages": 29,
                          "available_ops": ["source", "headings", "landmarks", "controls", "up", "next", "activate"],
                          "accounting": {"words": 250, "choices": 12},
                          "totals": {"words": 250 * (page + 1), "choices": 12 * (page + 1),
                                     "observations": page + 1, "navigation_moves": page, "browser_actions": 0}})
        data["steps"] = [{"step": index + 1, "observation": views[index],
                          "decision": {"purpose": "Inspect the next invoice records",
                                       "expectation": "Find a matching customer and invoice number",
                                       "cue_ids": [views[index]["items"][0]["id"]], "action": {"op": "next"}},
                          "result": views[index + 1]} for index in range(28)]
        client = FakeClient()
        annotation = annotate_episode(data, client, "judge")
        self.assertEqual(annotation["status"], "complete")
        self.assertEqual(len(client.requests), 2)
        for request in client.requests:
            self.assertLess(len(json.dumps(request[2], ensure_ascii=False, sort_keys=True)), MAX_PROMPT_CHARS)
        payload = client.requests[0][2]
        self.assertEqual(len(payload["observations"]), 29)
        for index, step in enumerate(payload["steps"][:-1]):
            self.assertEqual(step["result"], payload["steps"][index + 1]["observation"])
            self.assertNotIn("next_observation", step)

    def test_unknown_step_or_unavailable_channel_is_rejected(self):
        payload = evidence_payload(episode())
        for change in ("unknown_step", "missing_channel", "empty_evidence"):
            output = evidence()
            if change == "unknown_step":
                output["segments"][0]["evidence"][0]["step"] = 99
            elif change == "missing_channel":
                output["segments"][0]["evidence"][1]["channel"] = "next_observation"
            else:
                output["segments"][0]["evidence"] = []
            with self.subTest(change=change), self.assertRaises(AnnotationError):
                validate_evidence(output, payload)

    def test_invalid_first_pass_stays_invalid_and_does_not_call_second(self):
        output = evidence()
        output["segments"][0]["step_ids"] = [99]
        client = FakeClient([output])
        result = annotate_episode(episode(), client, "judge")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["independent_evidence"]["status"], "error")
        self.assertIn("unknown step", result["independent_evidence"]["error"])
        self.assertEqual(result["independent_evidence"]["raw_output"], output)
        self.assertEqual(len(client.requests), 1)

    def test_second_pass_error_preserves_first(self):
        output = comparison()
        output["comparisons"][0]["self_report_evidence"][0]["field"] = "hidden_thought"
        result = annotate_episode(episode(), FakeClient([evidence(), output]), "judge")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["independent_evidence"]["output"], evidence())
        self.assertEqual(result["with_self_report"]["status"], "error")

    def test_complete_trace_and_size_limits_are_explicit(self):
        data = episode()
        data["steps"] = [dict(copy.deepcopy(data["steps"][0]), step=index) for index in range(1, 29)]
        payload = evidence_payload(data)
        self.assertEqual(len(payload["steps"]), 28)
        self.assertFalse(payload["coverage"]["truncated"])
        data["steps"].append(dict(copy.deepcopy(data["steps"][0]), step=29))
        client = FakeClient()
        result = annotate_episode(data, client, "judge")
        self.assertEqual(result["status"], "error")
        self.assertIn("split explicitly", result["error"])
        self.assertEqual(client.requests, [])
        data = episode()
        data["steps"][0]["observation"]["large"] = "x" * 150_000
        result = annotate_episode(data, client, "judge")
        self.assertIn("split explicitly", result["independent_evidence"]["error"])
        self.assertEqual(client.requests, [])

    def test_report_separates_unavailable_verdict_and_partial_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run.json").write_text(json.dumps({"status": "running"}))
            for index, evaluation in enumerate(({"strict_success": True}, {}, {"status": "error", "strict_success": False})):
                path = root / "episodes" / str(index)
                path.mkdir(parents=True)
                data = episode()
                data["evaluation"] = evaluation
                (path / "episode.json").write_text(json.dumps(data))
                if index == 0:
                    annotation = annotate_episode(data, FakeClient(), "judge")
                    (path / "annotation.json").write_text(json.dumps(annotation))
            report = create_report(root).read_text()
            self.assertIn("**running**", report)
            self.assertIn("| 3 | 1 | 0 | 2 |", report)
            self.assertIn("step 1 observation", report)
            self.assertIn("Evidence annotation unavailable", report)
            self.assertIn("not establish", report)
            self.assertIn("Accepted evidence passes: 1/3", report)

    def test_empty_run_creates_report_with_artifact_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            report = create_report(directory).read_text()
            self.assertIn("Recorded episodes: **0**", report)
            self.assertIn("Artifact issues", report)


if __name__ == "__main__":
    unittest.main()
