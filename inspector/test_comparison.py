import copy
import json
import os
from pathlib import Path
import unittest

try:
    from .comparison import ComparisonError, MAX_CONTEXT, MAX_GROUPS, prepare_capture, run_comparison
except ImportError:
    from comparison import ComparisonError, MAX_CONTEXT, MAX_GROUPS, prepare_capture, run_comparison


def node(key, parent=None, children=(), tag="p", text="", **extras):
    return {"id": key, "parent": parent, "children": list(children), "tag": tag,
            "ownText": text, "text": text, "attributes": {}, **extras}


def fixture(count=5):
    children = ["e" + str(i) for i in range(count)]
    return {"id": "fixture", "label": "Reference label must not enter prompts",
            "dom": {"roots": ["root"], "nodes": [node("root", children=children, tag="main")]
                    + [node(key, "root", text="Observed " + key) for key in children]},
            "variants": {"revised": {"rootId": "REFERENCE_SECRET", "nodes": [
                {"id": "REFERENCE_SECRET", "label": "AUTHORED ANSWER SECRET", "sourceRefs": ["e0"]}]}}}


def group(key="g1", refs=("e0",), parent=None, label="Observed group"):
    return {"id": key, "label": label, "parent": parent, "source_ids": list(refs)}


class FakeClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.requests = []

    def generate(self, model, system, prompt, **kwargs):
        task = json.loads(prompt)
        self.requests.append({"model": model, "system": system, "task": task, **kwargs})
        if self.responses:
            answer = self.responses.pop(0)
        elif "local_groups" in task:
            roots = [g["id"] for g in task["local_groups"] if g["parent"] is None]
            answer = {"groups": [{"id": "upper", "label": "Observed page", "parent": None}] if roots else [],
                      "parents": [{"id": key, "parent": "upper"} for key in roots]}
        else:
            observed = task.get("owned_nodes", task.get("nodes"))
            answer = {"groups": [group(refs=[n["id"] for n in observed])]}
        return answer, {"usage": {"promptTokenCount": 10, "candidatesTokenCount": 5}, "model_version": model}


class PreparationTests(unittest.TestCase):
    def test_partition_unique_exhaustive_bounded_and_deterministic(self):
        data = fixture(210)
        prepared = prepare_capture(data, 80)
        self.assertEqual(prepared, prepare_capture(data, 80))
        owned = [key for r in prepared["regions"] for key in r["owned_ids"]]
        self.assertEqual(len(owned), len(set(owned)))
        self.assertEqual(set(owned), {n["id"] for n in prepared["nodes"]})
        for region in prepared["regions"]:
            self.assertLessEqual(len(region["owned_ids"]), 80)
            self.assertLessEqual(len(region["context_ids"]), MAX_CONTEXT)
            self.assertFalse(set(region["owned_ids"]) & set(region["context_ids"]))

    def test_fitting_source_subtree_is_not_split(self):
        data = fixture(100)
        data["dom"]["nodes"].append(node("section", "root", ["s1", "s2"], tag="section"))
        data["dom"]["nodes"].extend([node("s1", "section", text="First"), node("s2", "section", text="Second")])
        data["dom"]["nodes"][0]["children"].insert(79, "section")
        regions = prepare_capture(data, 80)["regions"]
        owner = next(r for r in regions if "section" in r["owned_ids"])
        self.assertTrue({"section", "s1", "s2"} <= set(owner["owned_ids"]))

    def test_hard_region_limit_never_truncates(self):
        with self.assertRaisesRegex(ComparisonError, "larger region size.*No source nodes were truncated"):
            prepare_capture(fixture(1000), 80)
        self.assertEqual(prepare_capture(fixture(1000), 160)["stats"]["retained_nodes"], 1001)

    def test_filters_code_and_collapses_wrapper_preserving_source_ids(self):
        data = {"dom": {"nodes": [node("body", children=["wrapper", "code"], tag="body"),
                    node("wrapper", "body", ["text"], tag="div"),
                    node("text", "wrapper", text="Actual text"),
                    node("code", "body", tag="script", text="DO NOT SEND THIS CODE")]}}
        prepared = prepare_capture(data)
        lookup = {n["id"]: n for n in prepared["nodes"]}
        self.assertEqual(set(lookup), {"body", "text"})
        self.assertEqual(lookup["text"]["parent"], "body")
        self.assertEqual(lookup["body"]["children"], ["text"])
        self.assertNotIn("DO NOT SEND THIS CODE", json.dumps(prepared))

    def test_legacy_aggregate_text_is_only_retained_at_leaves(self):
        data = fixture(1)
        for n in data["dom"]["nodes"]:
            n["ownTextAvailable"] = False
        data["dom"]["nodes"][0]["text"] = "AGGREGATE SECRET"
        prepared = prepare_capture(data)
        self.assertEqual(prepared["nodes"][0]["text"], "")
        self.assertEqual(prepared["nodes"][1]["text"], "Observed e0")
        self.assertEqual(prepared["stats"]["aggregate_text_removed"], 1)

    def test_hidden_relation_target_text_is_preserved_with_state(self):
        data = fixture(2)
        data["dom"]["nodes"][1]["attributes"] = {"aria-labelledby": "label-dom-id", "disabled": True}
        data["dom"]["nodes"][2].update(hidden=True, attributes={"id": "label-dom-id"})
        prepared = prepare_capture(data)
        target = next(n for n in prepared["nodes"] if n["id"] == "e1")
        self.assertTrue(target["hidden"])
        self.assertEqual(target["text"], "Observed e1")
        self.assertEqual(prepared["stats"]["retained_hidden_relation_nodes"], 1)

    def test_hidden_unrelated_evidence_is_explicitly_counted(self):
        data = fixture(2)
        data["dom"]["nodes"][2]["hidden"] = True
        prepared = prepare_capture(data)
        self.assertEqual(prepared["stats"]["excluded_hidden_nodes"], 1)
        self.assertNotIn("e1", {n["id"] for n in prepared["nodes"]})

    def test_multi_document_order_and_relation_scope_are_preserved(self):
        data = {"dom": {"nodes": [
            node("first", children=["control", "label1"], tag="body", document="one"),
            node("control", "first", tag="button", document="one", attributes={"aria-labelledby": "label"}),
            node("label1", "first", text="Right label", document="one", hidden=True, attributes={"id": "label"}),
            node("second", children=["label2"], tag="body", document="two"),
            node("label2", "second", text="Wrong label", document="two", hidden=True, attributes={"id": "label"}),
        ]}}
        prepared = prepare_capture(data)
        self.assertEqual([n["id"] for n in prepared["nodes"]], ["first", "control", "label1", "second"])
        self.assertEqual(prepared["stats"]["ambiguous_relation_references"], 0)

    def test_duplicate_html_ids_are_reported_without_arbitrary_resolution(self):
        data = fixture(3)
        data["dom"]["nodes"][1]["attributes"] = {"aria-labelledby": "duplicate"}
        for n in data["dom"]["nodes"][2:]:
            n.update(attributes={"id": "duplicate"}, hidden=True)
        prepared = prepare_capture(data)
        self.assertEqual(prepared["stats"]["ambiguous_relation_references"], 1)
        self.assertEqual(prepared["stats"]["retained_hidden_relation_nodes"], 0)

    def test_attributes_geometry_and_below_viewport_evidence_remain(self):
        data = fixture(1)
        data["dom"]["nodes"][1].update(attributes={"aria-expanded": "false", "href": "/next", "class": "layout"},
                                       rect={"x": 1, "y": 3000, "width": 100, "height": 10})
        observed = prepare_capture(data)["nodes"][1]
        self.assertEqual(observed["attrs"], {"aria-expanded": "false", "href": "/next"})
        self.assertEqual(observed["rect"]["y"], 3000)

    def test_malformed_source_is_rejected(self):
        data = fixture(1)
        data["dom"]["nodes"][1]["parent"] = "absent"
        with self.assertRaisesRegex(ComparisonError, "Inconsistent source"):
            prepare_capture(data)

    @unittest.skipUnless(os.environ.get("SEMANTIC_LOCAL_CORPUS_TESTS") == "1",
                         "Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original 14-site corpus")
    def test_all_repository_captures_fit_largest_region_size(self):
        catalog = json.loads((Path(__file__).parent / "data/catalog.json").read_text())
        self.assertEqual(len(catalog["datasets"]), 14)
        for path in (Path(__file__).parent / "data").glob("*.json"):
            data = json.loads(path.read_text())
            if "dom" in data:
                with self.subTest(capture=path.stem):
                    prepared = prepare_capture(data, 320)
                    self.assertLessEqual(len(prepared["regions"]), 12)


class ComparisonTests(unittest.TestCase):
    def test_prompts_use_same_observations_without_authored_variants(self):
        data = fixture(100)
        original = copy.deepcopy(data)
        whole, regional = FakeClient(), FakeClient()
        run_comparison(data, "whole", whole, "test", region_size=80)
        run_comparison(data, "regions", regional, "test", region_size=80)
        whole_nodes = whole.requests[0]["task"]["nodes"]
        region_nodes = [n for req in regional.requests if "owned_nodes" in req["task"]
                        for n in req["task"]["owned_nodes"]]
        self.assertEqual({n["id"]: n for n in whole_nodes}, {n["id"]: n for n in region_nodes})
        trace = json.dumps(whole.requests + regional.requests)
        self.assertNotIn("REFERENCE_SECRET", trace)
        self.assertNotIn("AUTHORED ANSWER SECRET", trace)
        self.assertNotIn("Reference label must not enter prompts", trace)
        self.assertEqual(data, original)

    def test_regional_prompts_have_bounded_local_evidence_and_context(self):
        client = FakeClient()
        result = run_comparison(fixture(210), "regions", client, "test", region_size=80)
        for request in client.requests[:-1]:
            task = request["task"]
            self.assertLessEqual(len(task["owned_nodes"]), 80)
            self.assertLessEqual(len(task["context_nodes"]), MAX_CONTEXT)
            self.assertIn("page_outline", task)
        self.assertEqual(result["metrics"]["calls"], len(result["regions"]) + 1)
        self.assertEqual(client.requests[-1]["task"]["group_budget"], 8)

    def test_composition_preserves_every_local_group_and_membership(self):
        client = FakeClient()
        result = run_comparison(fixture(100), "regions", client, "test", region_size=80)
        summaries = client.requests[-1]["task"]["local_groups"]
        output = {n["id"]: n for n in result["variant"]["nodes"]}
        for local in summaries:
            final = output["comparison:group:" + local["id"]]
            self.assertEqual(final["label"], local["label"])
            self.assertEqual(final["sourceRefs"], local["source_ids"])
        self.assertIn("comparison:group:upper", output)
        self.assertEqual(result["metrics"]["annotation_coverage"], 1)
        self.assertLessEqual(result["metrics"]["final_groups"], MAX_GROUPS)

    def test_fallback_does_not_inflate_annotation_coverage(self):
        client = FakeClient([{"groups": [group()]}])
        result = run_comparison(fixture(4), "whole", client, "test")
        self.assertEqual(result["metrics"]["annotated_source_nodes"], 1)
        self.assertEqual(result["metrics"]["ungrouped_source_nodes"], 4)
        self.assertEqual(result["metrics"]["annotation_coverage"], 0.2)
        fallback = next(n for n in result["variant"]["nodes"] if n["origin"] == "source-fallback")
        self.assertEqual(set(fallback["sourceRefs"]), {"root", "e1", "e2", "e3"})
        root = next(n for n in result["variant"]["nodes"] if n["id"] == result["variant"]["rootId"])
        self.assertEqual(root["children"][-1], fallback["id"])
        self.assertTrue(result["warnings"])

    def test_composed_upper_groups_follow_source_order_before_local_footer(self):
        local = {"groups": [group("footer", ["e2"], label="Footer"),
                            group("header", ["root", "e0"], label="Header"),
                            group("content", ["e1"], label="Content")]}
        composition = {"groups": [{"id": "content-section", "label": "Page content", "parent": None},
                                  {"id": "navigation", "label": "Site navigation", "parent": None}],
                       "parents": [{"id": "r1:footer", "parent": None},
                                   {"id": "r1:header", "parent": "navigation"},
                                   {"id": "r1:content", "parent": "content-section"}]}
        result = run_comparison(fixture(3), "regions", FakeClient([local, composition]), "test")
        variant = result["variant"]
        indexed = {item["id"]: item for item in variant["nodes"]}
        labels = [indexed[key]["label"] for key in indexed[variant["rootId"]]["children"]]
        self.assertEqual(labels, ["Site navigation", "Page content", "Footer"])
        self.assertEqual(result["metrics"]["sibling_order"], "minimum_descendant_source_preorder")

    def test_whole_sibling_groups_and_source_leaves_use_same_source_order(self):
        response = {"groups": [group("later", ["e2"], label="Later"),
                               group("earlier", ["e1", "root", "e0"], label="Earlier")]}
        result = run_comparison(fixture(3), "whole", FakeClient([response]), "test")
        variant = result["variant"]
        indexed = {item["id"]: item for item in variant["nodes"]}
        labels = [indexed[key]["label"] for key in indexed[variant["rootId"]]["children"]]
        self.assertEqual(labels, ["Earlier", "Later"])
        first = indexed["comparison:group:earlier"]
        self.assertEqual([indexed[key]["sourceRefs"][0] for key in first["children"]], ["root", "e0", "e1"])

    def test_nested_groups_sort_with_direct_source_siblings(self):
        response = {"groups": [group("parent", ["root", "e2"]),
                               group("child", ["e1", "e0"], parent="parent")]}
        result = run_comparison(fixture(3), "whole", FakeClient([response]), "test")
        indexed = {item["id"]: item for item in result["variant"]["nodes"]}
        self.assertEqual(indexed["comparison:group:parent"]["children"],
                         ["comparison:source:root", "comparison:group:child", "comparison:source:e2"])

    def test_usage_and_exact_prompts_outputs_are_returned(self):
        client = FakeClient()
        stages = []
        result = run_comparison(fixture(), "whole", client, "test", progress=stages.append)
        self.assertEqual(result["metrics"]["input_tokens"], 10)
        self.assertEqual(result["metrics"]["output_tokens"], 5)
        self.assertEqual(json.loads(result["calls"][0]["prompt"]), client.requests[0]["task"])
        self.assertEqual(result["calls"][0]["output"]["groups"][0]["id"], "g1")
        self.assertEqual(stages, ["whole"])
        self.assertEqual(result["calls"][0]["response_schema"], client.requests[0]["response_schema"])
        schema = client.requests[0]["response_schema"]
        self.assertEqual(schema["type"], "OBJECT")
        self.assertEqual(schema["required"], ["groups"])
        group_schema = schema["properties"]["groups"]["items"]
        self.assertTrue(group_schema["properties"]["parent"]["nullable"])
        self.assertEqual(set(group_schema["required"]), {"id", "label", "parent", "source_ids"})

    def test_whole_input_is_not_blocked_by_regional_call_limit(self):
        result = run_comparison(fixture(1000), "whole", FakeClient(), "test", region_size=80)
        self.assertTrue(result["metrics"]["region_limit_exceeded"])
        self.assertEqual(result["metrics"]["annotated_source_nodes"], 1001)
        self.assertEqual(result["metrics"]["calls"], 1)

    def test_malformed_annotations_are_rejected_without_repair(self):
        cases = [
            ({"groups": [group(refs=["invented"])]}, "unknown"),
            ({"groups": [group(parent="invented")]}, "unknown parent"),
            ({"groups": [group(parent="g2"), group(key="g2", parent="invented", refs=["e1"])]}, "unknown parent"),
            ({"groups": [group(parent="g1")]}, "cycle"),
            ({"groups": [group(), group()]}, "duplicate"),
            ({"groups": [group(), group(key="g2")]}, "duplicate source"),
            ({"groups": [group(refs=["e0", "e0"])]}, "duplicate source"),
            ({"groups": [group(label="x" * 101)]}, "label"),
            ({"groups": [group(refs=[])]}, "no source evidence"),
            ({"groups": [], "extra": "unexpected"}, "only a groups"),
        ]
        for output, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ComparisonError, message):
                    run_comparison(fixture(), "whole", FakeClient([output]), "test")

    def test_cross_region_assignment_is_rejected_even_when_in_context(self):
        data = fixture(100)
        prepared = prepare_capture(data, 80)
        first, second = prepared["regions"]
        responses = [{"groups": [group(refs=first["owned_ids"])]},
                     {"groups": [group(refs=[first["owned_ids"][0]])]}]
        self.assertIn(first["owned_ids"][0], second["context_ids"])
        with self.assertRaisesRegex(ComparisonError, "out-of-region"):
            run_comparison(data, "regions", FakeClient(responses), "test", region_size=80)

    def test_composition_cannot_drop_or_mutate_local_groups(self):
        for output in (
            {"groups": [], "parents": []},
            {"groups": [], "parents": [{"id": "r1:g1", "parent": None, "label": "Changed"}]},
            {"groups": [{"id": "r1:g1", "label": "Changed", "parent": None}], "parents": []},
        ):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ComparisonError, "compose"):
                    run_comparison(fixture(), "regions", FakeClient([{"groups": [group()]}, output]), "test")

    def test_composition_rejects_cycles_and_unattached_upper_groups(self):
        for parent, root_parent, expected in (("upper", "upper", "cycle"), (None, None, "contain a local")):
            output = {"groups": [{"id": "upper", "label": "Upper", "parent": parent}],
                      "parents": [{"id": "r1:g1", "parent": root_parent}]}
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ComparisonError, expected):
                    run_comparison(fixture(), "regions", FakeClient([{"groups": [group()]}, output]), "test")

    def test_empty_model_annotation_remains_explicit_source_fallback(self):
        client = FakeClient([{"groups": []}, {"groups": [], "parents": []}])
        result = run_comparison(fixture(), "regions", client, "test")
        self.assertEqual(result["metrics"]["annotation_coverage"], 0)
        self.assertEqual(result["metrics"]["model_groups"], 0)
        self.assertEqual(result["metrics"]["final_groups"], 2)


if __name__ == "__main__":
    unittest.main()
