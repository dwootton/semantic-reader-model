import copy
import unittest

from prompts.semantic_outline.contract import RESPONSE_SCHEMA, validate_output
from prompts.semantic_outline.outline_tool import to_hierarchy


class SemanticOutlineContractTests(unittest.TestCase):
    def setUp(self):
        self.output = {
            "page": "Example", "scope": "One captured document; deferred content needs expansion.",
            "outline": [
                {"depth": 0, "label": "Example", "refs": []},
                {"depth": 1, "label": "Product — $10", "refs": ["e1", "e2"]},
                {"depth": 1, "label": "Reviews (partial evidence)", "refs": ["e3"]},
            ],
            "needs_expansion": [{"ref": "e3", "reason": "Review contents were deferred."}],
        }
        self.refs = {"e1", "e2", "e3"}

    def test_grounded_output_is_compatible_with_existing_converter(self):
        self.assertEqual(validate_output(self.output, self.refs), ([], []))
        hierarchy = to_hierarchy(self.output, self.output["outline"])
        self.assertEqual(hierarchy["nodes"][1]["source_refs"], ["e1", "e2"])
        self.assertEqual(hierarchy["nodes"][0]["kind"], "group")

    def test_rejects_reference_from_other_document(self):
        self.output["outline"][1]["refs"].append("other-document")
        self.assertIn("unknown ref other-document", " ".join(validate_output(self.output, self.refs)[0]))

    def test_expansion_reference_must_be_grounded(self):
        self.output["needs_expansion"][0]["ref"] = "invented"
        self.assertIn("unknown ref", " ".join(validate_output(self.output, self.refs)[0]))

    def test_leaf_cannot_own_child_and_groups_cannot_be_empty(self):
        self.output["outline"][2]["depth"] = 2
        self.assertIn("reading unit must be a leaf", " ".join(validate_output(self.output, self.refs)[0]))
        self.output["outline"][2]["refs"] = []
        self.assertIn("group without children", " ".join(validate_output(self.output, self.refs)[0]))

    def test_bad_shapes_fail_without_crashing(self):
        mutations = [
            ("outline", [None]), ("outline", []), ("needs_expansion", [None]),
            ("needs_expansion", [{"ref": [], "reason": "x"}]), ("page", None),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.output)
                data[key] = value
                self.assertTrue(validate_output(data, self.refs)[0])
        for key, value in [("depth", True), ("depth", -1), ("label", None), ("refs", "e1"), ("refs", [None])]:
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.output)
                data["outline"][1][key] = value
                self.assertTrue(validate_output(data, self.refs)[0])

    def test_duplicate_refs_and_unknown_fields_rejected(self):
        self.output["outline"][1]["refs"].append("e1")
        self.output["summary"] = "unexpected"
        errors, _ = validate_output(self.output, self.refs)
        self.assertTrue(any("duplicate refs" in error for error in errors))
        self.assertTrue(any("exactly page" in error for error in errors))

    def test_schema_is_small_and_has_no_source_enum(self):
        self.assertNotIn("enum", repr(RESPONSE_SCHEMA))
        self.assertEqual(set(RESPONSE_SCHEMA["required"]), set(self.output))


if __name__ == "__main__":
    unittest.main()
