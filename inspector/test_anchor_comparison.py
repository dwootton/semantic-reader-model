import json
import unittest

from inspector.anchor_comparison import _decode, _labels, run_anchor_comparison
from inspector.compact_comparison import _regional_html, _regions
from inspector.comparison import ComparisonError
from inspector.test_compact_comparison import fixture, node


class Client:
    def __init__(self, empty=False):
        self.requests = []
        self.empty = empty

    def generate(self, model, system, prompt, **kwargs):
        task = json.loads(prompt)
        self.requests.append(task)
        props = kwargs["response_schema"]["properties"]["regions"]["items"]["properties"]
        roots = props["root"]["enum"]
        titles = props["title"]["enum"]
        root = next((r for r in roots if r in titles), None)
        return {"regions": [] if self.empty or root is None else [{"root": root, "title": root}],
                "needs_expansion": []}, {"usage": {"promptTokenCount": 10, "candidatesTokenCount": 5}}


class AnchorTests(unittest.TestCase):
    def test_nested_roots_use_deepest_membership(self):
        nodes = [node("a", children=["b", "d"]), node("b", "a", children=["c"]),
                 node("c", "b"), node("d", "a")]
        normalized, titles = _decode({"regions": [{"root": "b", "title": "c"}, {"root": "a", "title": "a"}],
                                      "needs_expansion": []}, nodes, ["a", "b", "c", "d"],
                                     ["a", "b", "c", "d"], {"a": "Outer", "c": "Inner"}, 4, "test")
        self.assertEqual(normalized["groups"], [
            {"id": "g1", "label": "Outer", "parent": None, "source_ids": ["a", "d"]},
            {"id": "g2", "label": "Inner", "parent": "g1", "source_ids": ["b", "c"]}])
        self.assertEqual(titles, ["a", "c"])

    def test_other_region_descendants_not_assigned(self):
        nodes = [node("a", children=["b", "c"]), node("b", "a"), node("c", "a")]
        result, _ = _decode({"regions": [{"root": "a", "title": "a"}], "needs_expansion": []},
                            nodes, ["a", "b"], ["a", "b"], {"a": "Visible"}, 4, "test")
        self.assertEqual(result["groups"][0]["source_ids"], ["a", "b"])

    def test_titles_use_visible_text_and_attributes(self):
        labels = _labels('<main data-r="a"><h2 data-r="b">Observed &amp; title</h2>'
                         '<input data-r="c" aria-label="Search"></main>', "data-r", ["a", "b", "c"])
        self.assertEqual(labels["b"], "Observed & title")
        self.assertEqual(labels["c"], "Search")
        self.assertEqual(_labels('<p data-r="a"></p>', "data-r", ["a"]), {})

    def test_duplicates_wrong_titles_and_foreign_roots_rejected(self):
        nodes = [node("a", children=["b", "c"]), node("b", "a"), node("c", "a")]
        invalid = [[{"root": "b", "title": "b"}] * 2,
                   [{"root": "b", "title": "c"}], [{"root": "x", "title": "b"}],
                   [{"root": "b", "title": "missing"}]]
        for regions in invalid:
            with self.subTest(regions=regions), self.assertRaises(ComparisonError):
                _decode({"regions": regions, "needs_expansion": []}, nodes, ["a", "b", "c"],
                        ["a", "b", "c"], {"b": "B", "c": "C"}, 4, "test")

    def test_html_unchanged_and_provenance_recorded(self):
        prepared = fixture(20)
        client = Client()
        result = run_anchor_comparison(prepared, "regions", client, "test")
        document = prepared["documents"][0]
        expected = [_regional_html(document, r)[0] for r in _regions(document, 160)]
        self.assertEqual([r["html"] for r in client.requests], expected)
        self.assertEqual(result["input_mode"], "compact-anchors")
        for call in result["calls"]:
            self.assertIn("regions", call["output"])
            self.assertIn("groups", call["normalized_output"])
            self.assertNotIn("SECRET", call["prompt"])
        self.assertTrue(all(n["labelSourceRefs"] for n in result["variant"]["nodes"]
                            if n["origin"] == "model-regions"))

    def test_empty_selection_retains_all_fallback(self):
        result = run_anchor_comparison(fixture(20), "whole", Client(empty=True), "test")
        self.assertEqual(result["metrics"]["annotation_coverage"], 0)
        self.assertEqual(result["metrics"]["ungrouped_source_nodes"], 21)
        self.assertEqual(result["metrics"]["composition_calls"], 0)


if __name__ == "__main__":
    unittest.main()
