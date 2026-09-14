import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from training import judge


def fixture(candidate_id="student", split="train", rating=3):
    target = {"page": "Guide", "scope": "Captured guide.", "outline": [
        {"depth": 0, "label": "Guide", "refs": []},
        {"depth": 1, "label": "Install", "refs": ["d0:1"]},
    ], "needs_expansion": []}
    row = {"id": "guide-1", "domain": "docs.example", "split": split,
           "prompt": [{"role": "system", "content": "Produce a grounded outline."},
                      {"role": "user", "content": '<p data-ref="d0:1">Install the tool.</p>'}],
           "completion": [{"role": "assistant", "content": "SECRET_REFERENCE_TARGET"}],
           "valid_refs": ["d0:1"]}
    packet = judge.build_packet(row, {"id": row["id"], "candidate_id": candidate_id, "output": target})
    evidence = [{"kind": "prompt", "pointer": "/1/content", "quote": "Install the tool."},
                {"kind": "candidate", "pointer": "/outline/1/label", "quote": "Install"}]
    result = {"rubric_version": judge.VERSION, "id": row["id"], "candidate_id": candidate_id,
              "complete_review": True, "source_sufficient": True,
              "criteria": {c: {"status": "assessed", "score": rating,
                                "reason": "Supported by the supplied source and candidate.",
                                "evidence": copy.deepcopy(evidence)} for c in judge.CRITERIA},
              "hard_errors": []}
    return row, packet, result


class TrainingJudgeTests(unittest.TestCase):
    def test_primary_scoring_cannot_see_target(self):
        row, packet, _ = fixture()
        self.assertEqual(packet["prompt"], row["prompt"])
        self.assertNotIn("SECRET_REFERENCE_TARGET", json.dumps(packet))
        self.assertEqual(set(packet["valid_refs"]), {"d0:1"})

    def test_json_encoded_html_has_lossless_source_evidence_without_target(self):
        row, original, result = fixture()
        source = {"assignable_refs": ["d0:1"], "capture_partial": True,
                  "reference_attribute": "data-r",
                  "source_html": '<p data-r="d0:1">Install the tool.</p>',
                  "browser_observation": {"summary": "Captured article."}}
        row["prompt"][1]["content"] = json.dumps(source)
        row["source_input"] = {"forged": "SECRET_REFERENCE_TARGET"}
        packet = judge.build_packet(row, {"id": row["id"], "candidate_id": "student",
                                          "output": original["candidate"]})
        self.assertEqual(packet["source_input"], source)
        self.assertEqual(packet["prompt"], row["prompt"])
        self.assertNotIn(source["source_html"], row["prompt"][1]["content"])
        self.assertNotIn("SECRET_REFERENCE_TARGET", json.dumps(packet))
        for criterion in result["criteria"].values():
            criterion["evidence"][0] = {"kind": "source", "pointer": "/source_html",
                                        "quote": source["source_html"]}
        result["criteria"]["grounding"]["evidence"][1] = {
            "kind": "candidate", "pointer": "/outline/1/refs/0", "quote": "d0:1"}
        score = judge.score_packet(packet, json.dumps(result))
        self.assertEqual(score["decision"], "accept")
        self.assertEqual(judge.validated_score(score), result)
        self.assertEqual(judge.resolve_evidence(packet, {"kind": "source",
                         "pointer": "/browser_observation/summary", "quote": "Captured article."}),
                         "Captured article.")
        packet["source_input"]["source_html"] += " Invented markup."
        score["packet_hash"] = judge.digest(packet)
        with self.assertRaisesRegex(ValueError, "was changed"):
            judge.validated_score(score)

    def test_candidate_ref_array_is_rejected_but_individual_ref_is_citable(self):
        _, packet, _ = fixture()
        with self.assertRaisesRegex(ValueError, "referenced string"):
            judge.resolve_evidence(packet, {"kind": "candidate", "pointer": "/outline/1/refs",
                                            "quote": '["d0:1"]'})
        self.assertEqual(judge.resolve_evidence(packet, {"kind": "candidate",
                         "pointer": "/outline/1/refs/0", "quote": "d0:1"}), "d0:1")

    def test_plain_text_user_source_keeps_prompt_evidence(self):
        _, packet, result = fixture()
        self.assertIsNone(packet["source_input"])
        self.assertEqual(judge.score_packet(packet, result)["decision"], "accept")

    def test_strict_json_rejects_duplicates_nonfinite_and_fences(self):
        for value in ('{"a": 1, "a": 2}', '{"a": NaN}', '```json\n{}\n```'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                judge.strict_json(value)

    def test_structural_failure_dominates_claimed_perfect_judgment(self):
        row, packet, result = fixture()
        packet["candidate"]["outline"][1]["refs"] = ["another-document"]
        packet = judge.build_packet(row, {"id": row["id"], "candidate_id": "student",
                                          "output": packet["candidate"]})
        score = judge.score_packet(packet, result)
        self.assertEqual(score["decision"], "reject")
        self.assertIsNone(score["result"])
        self.assertFalse(score["reward_eligible"])

    def test_assessed_criteria_require_resolvable_source_and_candidate_quotes(self):
        _, packet, result = fixture()
        for mutation in ("missing", "pointer", "quote", "bool", "extra"):
            raw = copy.deepcopy(result)
            criterion = raw["criteria"]["coverage"]
            if mutation == "missing":
                criterion["evidence"] = criterion["evidence"][1:]
            elif mutation == "pointer":
                criterion["evidence"][0]["pointer"] = "/99/content"
            elif mutation == "quote":
                criterion["evidence"][0]["quote"] = "Fabricated source quote"
            elif mutation == "bool":
                criterion["score"] = True
            else:
                raw["decision"] = "accept"
            with self.subTest(mutation=mutation):
                self.assertEqual(judge.score_packet(packet, raw)["decision"], "invalid_judgment")

    def test_unknown_is_not_zero_or_a_reward(self):
        _, packet, result = fixture()
        result["criteria"]["coverage"].update(status="insufficient_evidence", score=None)
        score = judge.score_packet(packet, result)
        self.assertEqual(score["decision"], "insufficient_evidence")
        self.assertIsNone(score["reward"])
        self.assertEqual(list(judge.export_accepted([score])), [])
        with self.assertRaisesRegex(ValueError, "uncalibrated"):
            judge.reward_for_score(score)

    def test_task_instructions_do_not_count_as_source_evidence(self):
        _, packet, result = fixture()
        result["criteria"]["coverage"]["evidence"][0] = {
            "kind": "prompt", "pointer": "/0/content", "quote": "grounded outline"}
        self.assertEqual(judge.score_packet(packet, result)["decision"], "invalid_judgment")

    def test_hard_error_and_rating_must_agree(self):
        _, packet, result = fixture()
        result["hard_errors"] = [{"criterion": "grounding", "reason": "Invented state.",
                                   "evidence": result["criteria"]["grounding"]["evidence"]}]
        self.assertEqual(judge.score_packet(packet, result)["decision"], "invalid_judgment")
        result["criteria"]["grounding"]["score"] = 0
        self.assertEqual(judge.score_packet(packet, result)["decision"], "reject")
        result["hard_errors"] = []
        self.assertEqual(judge.score_packet(packet, result)["decision"], "invalid_judgment")

    def candidates(self, split="train"):
        _, pa, ra = fixture("a", split, 3)
        row, pb, rb = fixture("b", split, 2)
        pb["candidate"]["scope"] += " Another formulation."
        pb = judge.build_packet(row, {"id": row["id"], "candidate_id": "b", "output": pb["candidate"]})
        return judge.score_packet(pa, ra), judge.score_packet(pb, rb)

    def test_preferences_require_same_prompt_train_split_and_clear_dominance(self):
        a, b = self.candidates()
        pairs = list(judge.export_preferences([a, b]))
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["chosen_candidate_id"], "a")
        self.assertEqual(pairs[0]["split"], "train")
        self.assertEqual(pairs[0]["domain"], "docs.example")
        for split in ("dev", "test"):
            self.assertEqual(list(judge.export_preferences(self.candidates(split))), [])
        b["packet"]["prompt"][1]["content"] += " Different scope."
        self.assertEqual(list(judge.export_preferences([a, b])), [])

    def test_ties_tradeoffs_unknown_and_hard_failures_abstain(self):
        a, b = self.candidates()
        for criterion in b["result"]["criteria"].values():
            criterion["score"] = 3
        self.assertEqual(list(judge.export_preferences([a, b])), [])
        a["result"]["criteria"]["coverage"]["score"] = 2
        b["result"]["criteria"]["labels"]["score"] = 2
        self.assertEqual(list(judge.export_preferences([a, b])), [])
        b["result"]["source_sufficient"] = False
        b["decision"] = "insufficient_evidence"
        self.assertEqual(list(judge.export_preferences([a, b])), [])

    def test_modified_score_or_preflight_cannot_admit_invalid_candidate(self):
        a, b = self.candidates()
        a["packet"]["candidate"]["outline"][1]["refs"] = ["forged-ref"]
        a["packet_hash"] = judge.digest(a["packet"])
        self.assertEqual(list(judge.export_preferences([a, b])), [])
        self.assertEqual(list(judge.export_accepted([a])), [])

    def test_rejection_sft_exports_only_accepted_train_candidates(self):
        a, _ = self.candidates()
        output = list(judge.export_accepted([a]))
        self.assertEqual(len(output), 1)
        self.assertEqual(json.loads(output[0]["completion"][0]["content"]), a["packet"]["candidate"])
        self.assertEqual(list(judge.export_accepted(self.candidates("test"))), [])

    def test_synthetic_or_train_reviews_cannot_calibrate(self):
        _, packet, result = fixture(split="dev")
        score = judge.score_packet(packet, result)
        review = {"id": score["id"], "candidate_id": score["candidate_id"], "split": "dev",
                  "decision": "accept", "score_hash": judge.digest(score), "human_reviewed": True,
                  "synthetic": True, "reviewer": "test", "reviewed_at": "2026-09-13",
                  "evidence_uri": "test-fixture-not-real-review"}
        with self.assertRaisesRegex(ValueError, "actual held-out human review"):
            judge.calibrate([score], [review])
        review["synthetic"] = False
        calibration = judge.calibrate([score], [review])
        self.assertEqual(calibration["status"], "uncalibrated")
        with self.assertRaisesRegex(ValueError, "uncalibrated"):
            judge.reward_for_score(score, calibration)
        review["split"] = "train"
        with self.assertRaisesRegex(ValueError, "held out"):
            judge.calibrate([score], [review])

    def test_self_declared_calibration_without_evidence_cannot_enable_reward(self):
        score, _ = self.candidates()
        calibration = {"status": "reviewed_pilot_gate_passed", "model": score["model"],
                       "rubric_version": judge.VERSION, "rubric_hash": score["rubric_hash"]}
        with self.assertRaisesRegex(ValueError, "reviewed calibration evidence"):
            judge.reward_for_score(score, calibration)

    def test_final_test_split_cannot_calibrate_or_supply_calibration_metrics(self):
        _, packet, result = fixture(split="test")
        score = judge.score_packet(packet, result)
        review = {"id": score["id"], "candidate_id": score["candidate_id"], "split": "test",
                  "decision": "accept", "score_hash": judge.digest(score), "human_reviewed": True,
                  "synthetic": False, "reviewer": "test", "reviewed_at": "2026-09-13",
                  "evidence_uri": "fixture-used-only-to-test-rejection"}
        with self.assertRaisesRegex(ValueError, "requires dev"):
            judge.calibrate([score], [review])
        evidence = [{"review": review, "model": score["model"], "domain": score["domain"],
                     "predicted": "accept"}]
        with self.assertRaisesRegex(ValueError, "reviewed calibration evidence"):
            judge._calibration_metrics(evidence)

    def test_offline_cli_is_blinded_and_never_constructs_client(self):
        row, packet, result = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            judge.write_jsonl(root / "data.jsonl", [row])
            judge.write_jsonl(root / "predictions.jsonl", [{"id": row["id"], "candidate_id": "student",
                                                            "output": packet["candidate"]}])
            judge.write_jsonl(root / "results.jsonl", [{"id": row["id"], "candidate_id": "student",
                                                        "packet_hash": judge.digest(packet), "result": result}])
            with patch("harness.model.LabClient", side_effect=AssertionError("No cloud access")):
                judge.main(["score", "--data", str(root / "data.jsonl"), "--predictions",
                            str(root / "predictions.jsonl"), "--judge-results", str(root / "results.jsonl"),
                            "--output", str(root / "scores.jsonl")])
            score = judge.read_jsonl(root / "scores.jsonl")[0]
            self.assertEqual(score["decision"], "accept")
            self.assertEqual(score["judgment_source"], "offline")
            self.assertNotIn("SECRET_REFERENCE_TARGET", (root / "scores.jsonl").read_text())
            self.assertFalse(score["reward_eligible"])

    def test_zero_call_budget_leaves_valid_candidates_unjudged(self):
        row, packet, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            judge.write_jsonl(root / "data.jsonl", [row])
            judge.write_jsonl(root / "predictions.jsonl", [{"id": row["id"], "candidate_id": "student",
                                                            "output": packet["candidate"]}])
            with patch("harness.model.LabClient.generate", side_effect=AssertionError("No cloud access")):
                judge.main(["score", "--data", str(root / "data.jsonl"), "--predictions",
                            str(root / "predictions.jsonl"), "--max-calls", "0",
                            "--output", str(root / "scores.jsonl")])
            score = judge.read_jsonl(root / "scores.jsonl")[0]
            self.assertEqual(score["decision"], "unjudged")
            self.assertIn("budget exhausted", score["error"])


if __name__ == "__main__":
    unittest.main()
