import json
import unittest

from inspector.comparison import ComparisonError
from inspector.selection_comparison import _candidates, _decode, run_selection_comparison
from inspector.test_compact_comparison import node


def fixture():
    nodes = [node("a", children=["b"], tag="main"),
             node("b", "a", children=["h", "p"], tag="section"),
             node("h", "b", text="Details", tag="h2"), node("p", "b", text="Keep every word")]
    rendered = '<main data-r="a"><section data-r="b"><h2 data-r="h">Details</h2><p data-r="p">Keep every word</p></section></main>'
    return {"documents": [{"id": "d", "nodes": nodes, "assignable_ids": ["a", "b", "h", "p"],
                            "reference_attribute": "data-r", "html": rendered}]}


class Client:
    def __init__(self):
        self.requests = []

    def generate(self, model, system, prompt, **kwargs):
        task = json.loads(prompt)
        self.requests.append(task)
        return {"keep": [c["id"] for c in task["candidates"]], "needs_expansion": []}, {}


class SelectionTests(unittest.TestCase):
    def proposals(self):
        doc = fixture()["documents"][0]
        return _candidates(doc["html"], "data-r", doc["assignable_ids"], doc["assignable_ids"], doc["nodes"])

    def test_nearest_container_prebinds_title(self):
        self.assertEqual(self.proposals(), [{"id": "c1", "root": "b", "title": "h", "text": "Details"}])

    def test_duplicate_selection_rejected(self):
        doc = fixture()["documents"][0]
        with self.assertRaisesRegex(ComparisonError, "unique"):
            _decode({"keep": ["c1", "c1"], "needs_expansion": []}, self.proposals(), doc["nodes"],
                    doc["assignable_ids"], doc["assignable_ids"], 4, "test")

    def test_aria_heading_can_name_container(self):
        doc = fixture()["documents"][0]
        doc["nodes"][2]["tag"] = "div"
        doc["nodes"][2]["attributes"]["role"] = "heading"
        rendered = doc["html"].replace('<h2 ', '<div role="heading" ').replace('</h2>', '</div>')
        proposals = _candidates(rendered, "data-r", doc["assignable_ids"], doc["assignable_ids"], doc["nodes"])
        self.assertEqual(proposals, [{"id": "c1", "root": "b", "title": "h", "text": "Details"}])

    def test_source_preserved_valid_selection_fallback(self):
        prepared = fixture()
        client = Client()
        result = run_selection_comparison(prepared, "whole", client, "test")
        self.assertEqual(client.requests[0]["html"], prepared["documents"][0]["html"])
        self.assertEqual(result["metrics"]["annotated_source_nodes"], 3)
        self.assertEqual(result["metrics"]["ungrouped_source_nodes"], 1)
        self.assertEqual(result["variant"]["nodes"][1]["labelSourceRefs"], ["h"])

    def test_unobserved_heading_not_proposed(self):
        doc = fixture()["documents"][0]
        self.assertEqual(_candidates('<main data-r="a"></main>', "data-r", ["a"], ["a"], doc["nodes"]), [])

    def test_explicit_name_priority(self):
        doc = fixture()["documents"][0]
        doc["nodes"][1]["attributes"]["aria-label"] = "Section name"
        rendered = doc["html"].replace('data-r="b"', 'data-r="b" aria-label="Section name"')
        candidates = _candidates(rendered, "data-r", doc["assignable_ids"], doc["assignable_ids"], doc["nodes"])
        self.assertEqual(candidates, [{"id": "c1", "root": "b", "title": "b", "text": "Section name"}])

    def test_no_candidates_still_calls_and_keeps_fallback(self):
        prepared = fixture()
        prepared["documents"][0]["nodes"][2]["tag"] = "p"
        prepared["documents"][0]["html"] = prepared["documents"][0]["html"].replace("h2", "p")
        client = Client()
        result = run_selection_comparison(prepared, "whole", client, "test")
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(result["metrics"]["annotation_coverage"], 0)


if __name__ == "__main__":
    unittest.main()
