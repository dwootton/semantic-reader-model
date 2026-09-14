import copy
import json
from pathlib import Path
import tempfile
import unittest

from training.data import assign_splits, build_snapshot, canonical, recompute_metrics, sha256, student_messages, validate_issue_critic


class TrainingDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "annotation" / "scale"
        self.document = {
            "html": '<html><body data-r="r1"><p data-r="r2">Visible source</p></body></html>',
            "reference_attribute": "data-r", "assignable_ids": ["r1", "r2", "not-in-html"], "capture_partial": True,
            "nodes": [{"id": "r1", "children": ["r2"], "tag": "body"}, {"id": "r2", "parent": "r1", "children": [], "tag": "p"}],
        }
        self.outline = {
            "page": "PRIVATE_TEACHER_TITLE", "scope": "Captured document",
            "outline": [{"depth": 0, "label": "PRIVATE_TEACHER_TITLE", "refs": []},
                        {"depth": 1, "label": "PRIVATE_TEACHER_LABEL", "refs": ["r2"]}],
            "needs_expansion": [],
        }
        self.inventory = {"page": "PRIVATE_TEACHER_TITLE", "units": [
            {"id": "u1", "label": "PRIVATE_TEACHER_LABEL", "refs": ["r2"], "source_coverage": ["r2"]}]}

    def write(self, relative, value):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def fixture(self, status="review_candidate", critic=None):
        self.write("selection.json", {"samples": [{"sample_id": "one", "domain": "example.org"}]})
        self.write("job.json", {"model": "teacher", "code_hashes": {"pipeline.py": "frozen-code"}})
        rights = {"accepted_for_training": False, "legal_clearance": "not_determined"}
        self.write("inputs/one.json", {"sample_id": "one", "page_url": "https://example.org/", "document": self.document,
                                       "registrable_domain": "example.org", "source_rights": rights})
        self.final = {"sample_id": "one", "status": status, "gold": False, "human_review": "pending",
                      "source_rights": rights, "model": "teacher", "critic_incomplete": False,
                      "label_validation": {"valid": True, "errors": []},
                      "stage_completion": {"unit_review": True, "labels": True, "final_critic": True},
                      "inventory": self.inventory, "outline": self.outline}
        self.write("pages/one/final.json", self.final)
        self.write("pages/one/base-inventory.json", {**self.inventory, "diagnostics": {"unresolved_refs": []}})
        user = {"inventory": self.inventory, "candidate": self.outline, "source_html": self.document["html"],
                "browser_observation": {"browser_accessibility_summary": [{"role": "text", "name": "Visible source"}], "limitations": "No screenshots"}}
        payload = {"systemInstruction": {"parts": [{"text": "Exact teacher critic system."}]},
                   "contents": [{"role": "user", "parts": [{"text": json.dumps(user)}]}]}
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        self.request = {"model": "teacher", "payload": payload, "request_sha256": digest}
        self.write("calls/one-final-critic/request.json", self.request)
        self.write("calls/one-final-critic/result.json", {"status": "completed", "request_sha256": digest,
                                                         "response": critic if critic is not None else {"issues": []}})
        self.write("calls/one-units/result.json", {"status": "completed", "response": {"patches": []}})
        self.write("calls/one-labels/result.json", {"status": "completed", "response": {"labels": []}})

    def rows(self, output, prefix):
        return [json.loads(line) for path in output.glob(prefix) for line in path.read_text().splitlines()]

    def test_student_has_full_source_and_exact_observation_but_no_teacher_labels(self):
        self.fixture()
        out = self.root / "data"
        manifest = build_snapshot([self.source], out)
        rows = self.rows(out, "student-*.jsonl")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        prompt = canonical(row["prompt"])
        self.assertNotIn("PRIVATE_TEACHER", prompt)
        self.assertNotIn("inventory", json.loads(row["prompt"][1]["content"]))
        self.assertEqual(json.loads(row["prompt"][1]["content"])["source_html"], self.document["html"])
        self.assertEqual(json.loads(row["completion"][0]["content"]), self.outline)
        self.assertEqual(len(row["completion"]), 1)
        self.assertEqual([message["role"] for message in row["prompt"]], ["system", "user"])
        self.assertNotIn("messages", row)
        self.assertEqual(row["valid_refs"], ["r1", "r2"])
        self.assertFalse(row["source_rights"]["accepted_for_training"])
        self.assertFalse(row["gold"])
        self.assertIn(str((self.source / "pages/one/final.json").resolve()), manifest["source_artifact_sha256"])
        judge = self.rows(out, "judge-*.jsonl")[0]
        self.assertEqual(judge["prompt"][1]["content"], self.request["payload"]["contents"][0]["parts"][0]["text"])
        self.assertEqual(judge["completion"], [{"role": "assistant", "content": '{"issues":[]}'}])
        self.assertEqual(judge["label_source"], "saved_final_issue_critic")

    def test_malformed_critic_is_excluded_from_student_and_judge(self):
        self.fixture(critic={"issues": [{"severity": "major", "units": [], "category": "coverage", "reason": "bad"}]})
        out = self.root / "data"
        build_snapshot([self.source], out)
        self.assertFalse(self.rows(out, "student-*.jsonl"))
        self.assertFalse(self.rows(out, "judge-*.jsonl"))
        self.assertIn("critic_issue_0_invalid", self.rows(out, "candidates.jsonl")[0]["exclusion_reasons"])

    def test_major_critic_is_retained_for_judge_but_not_sft(self):
        self.fixture(critic={"issues": [{"severity": "major", "units": ["u1"], "category": "grouping", "reason": "bad grouping"}]})
        out = self.root / "data"
        build_snapshot([self.source], out)
        self.assertFalse(self.rows(out, "student-*.jsonl"))
        self.assertEqual(len(self.rows(out, "judge-*.jsonl")), 1)

    def test_recomputes_missing_atoms_instead_of_trusting_saved_status(self):
        self.fixture()
        baseline = copy.deepcopy(self.inventory)
        baseline["units"][0]["source_coverage"].append("r1")
        self.write("pages/one/base-inventory.json", baseline)
        out = self.root / "data"
        build_snapshot([self.source], out)
        candidate = self.rows(out, "candidates.jsonl")[0]
        self.assertFalse(candidate["sft_eligible"])
        self.assertIn("metric_missing_outline_atoms", candidate["exclusion_reasons"])

    def test_output_collision_is_immutable(self):
        self.fixture()
        out = self.root / "data"
        build_snapshot([self.source], out)
        original = (out / "manifest.json").read_bytes()
        self.write("pages/one/final.json", {"status": "changed"})
        with self.assertRaises(FileExistsError):
            build_snapshot([self.source], out)
        self.assertEqual((out / "manifest.json").read_bytes(), original)

    def test_domains_templates_and_document_duplicates_form_transitive_families(self):
        rows = [{"id": str(i), "domain": f"d{i}", "template_sha256": f"t{i}", "document_sha256": f"h{i}"} for i in range(12)]
        rows[1]["domain"] = rows[0]["domain"]
        rows[2]["template_sha256"] = rows[1]["template_sha256"]
        rows[3]["document_sha256"] = rows[2]["document_sha256"]
        split = assign_splits(rows)
        self.assertEqual(len({split[str(i)]["family_id"] for i in range(4)}), 1)
        self.assertEqual(split, assign_splits(list(reversed(rows))))
        self.assertEqual({r["split"] for r in split.values()}, {"train", "dev", "test"})

    def test_split_assignment_does_not_change_when_final_arrives(self):
        self.fixture()
        self.write("selection.json", {"samples": [{"sample_id": "one"}, {"sample_id": "two"}]})
        row = json.loads((self.source / "inputs/one.json").read_text())
        row["sample_id"] = "two"
        self.write("inputs/two.json", row)
        first, second = self.root / "first", self.root / "second"
        build_snapshot([self.source], first)
        self.write("pages/two/final.json", {"sample_id": "two", "status": "pipeline_failed"})
        build_snapshot([self.source], second)
        self.assertEqual((first / "split-manifest.json").read_bytes(), (second / "split-manifest.json").read_bytes())

    def test_unknown_reference_not_admitted_even_if_in_assignable_ids(self):
        document = copy.deepcopy(self.document)
        messages, refs = student_messages(document, {})
        self.assertNotIn("not-in-html", refs)
        self.assertNotIn("not-in-html", messages[1]["content"])

    def test_strict_critic_rejects_extra_fields_and_unknown_units(self):
        self.assertTrue(validate_issue_critic({"issues": [], "score": 5}, self.inventory))
        self.assertTrue(validate_issue_critic({"issues": [{"severity": "major", "category": "coverage", "units": ["wrong"], "reason": "missing"}]}, self.inventory))

    def test_cross_leaf_ownership_is_recomputed(self):
        outline = copy.deepcopy(self.outline)
        outline["outline"].append({"depth": 1, "label": "Wrapper", "refs": ["r1"]})
        inventory = copy.deepcopy(self.inventory)
        inventory["units"].append({"id": "u2", "label": "Wrapper", "refs": ["r1"], "source_coverage": []})
        metrics = recompute_metrics(self.document, inventory, outline, self.inventory, ["r1", "r2"])
        self.assertEqual(metrics["cross_leaf_ancestor_overlap"], [[0, 1]])

    def test_incomplete_stage_rejects_sft_but_preserves_valid_critic(self):
        self.fixture()
        self.write("calls/one-labels/result.json", {"status": "failed"})
        out = self.root / "data"
        build_snapshot([self.source], out)
        self.assertFalse(self.rows(out, "student-*.jsonl"))
        self.assertEqual(len(self.rows(out, "judge-*.jsonl")), 1)
        self.assertIn("stage_labels_incomplete", self.rows(out, "candidates.jsonl")[0]["exclusion_reasons"])

    def test_modified_frozen_input_fails_before_snapshot_is_written(self):
        self.fixture()
        self.write("job.json", {"input_hashes": {"one": "wrong"}})
        out = self.root / "data"
        with self.assertRaisesRegex(ValueError, "Frozen labeler input hash mismatch"):
            build_snapshot([self.source], out)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
