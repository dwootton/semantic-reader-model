import copy
import html
import json
import unittest

from inspector.compact_comparison import (ComparisonError, MAX_CONTEXT, _assemble,
                                          _regional_html, _regions, run_compact_comparison)


def node(key, parent=None, children=(), *, text="", tag="p", attributes=None, content=None):
    return {"id": key, "parent": parent, "children": list(children), "tag": tag,
            "text": text, "ownText": text, "attributes": attributes or {"data-r": key},
            "content": content if content is not None else [text, *({"id": child} for child in children)]}


def fixture(count=72, prefix="d0"):
    keys = [f"{prefix}:{index + 1:x}" for index in range(count)]
    root = f"{prefix}:0"
    nodes = [node(root, children=keys, tag="main", attributes={"data-r": root, "data-deferred": "content"})]
    nodes.extend(node(key, root, text=f"Observed café {index}") for index, key in enumerate(keys))
    rendered = '<main data-r="' + root + '" data-deferred="content">' + "".join(
        '<p data-r="' + key + '">' + html.escape(nodes[index + 1]["text"]) + '</p>' for index, key in enumerate(keys)) + '</main>'
    document = {"id": prefix, "nodes": nodes, "roots": [root], "assignable_ids": [root, *keys],
                "reference_attribute": "data-r", "html": rendered, "audit": {"secret": "AUDIT_SECRET"}}
    return {"documents": [document], "dataset": {"secret": "AUTHORED_VARIANT_SECRET"},
            "provenance": {"sourceMap": "SOURCE_MAP_SECRET", "original_source": "ORIGINAL_HTML_SECRET"},
            "metrics": {"original_nodes": 2000, "source_bytes": 99999, "html_bytes": len(rendered.encode())}}


def group(key="g1", refs=(), parent=None, label="Observed group"):
    return {"id": key, "label": label, "source_ids": list(refs), "parent": parent}


class FakeClient:
    def __init__(self, output=None):
        self.output = output
        self.requests = []

    def generate(self, model, system, prompt, **kwargs):
        task = json.loads(prompt)
        schema = kwargs["response_schema"]
        self.requests.append({"task": task, "system": system, **kwargs})
        allowed = schema["properties"]["groups"]["items"]["properties"]["source_ids"]["items"]["enum"]
        output = self.output if self.output is not None else {"groups": [group(refs=allowed)], "needs_expansion": []}
        return copy.deepcopy(output), {"usage": {"promptTokenCount": 11, "candidatesTokenCount": 7}, "backend": "ollama"}


class CompactComparisonTests(unittest.TestCase):
    def test_inputs_are_single_html_without_original_or_duplicate_nodes(self):
        prepared = fixture()
        before = copy.deepcopy(prepared)
        for strategy in ("whole", "regions"):
            client = FakeClient()
            result = run_compact_comparison(prepared, strategy, client, "local")
            for request in client.requests:
                self.assertEqual(set(request["task"]), {"task", "reference_attribute", "group_budget", "html"})
                self.assertEqual(request["task"]["html"].count("<main "), 1)
                trace = json.dumps(request)
                for secret in ("AUTHORED_VARIANT_SECRET", "AUDIT_SECRET", "SOURCE_MAP_SECRET", "ORIGINAL_HTML_SECRET"):
                    self.assertNotIn(secret, trace)
                self.assertNotIn("SOURCE_ID", trace)
                self.assertNotIn("REFERENCE", trace)
            if strategy == "whole":
                self.assertEqual(client.requests[0]["task"]["html"], prepared["documents"][0]["html"])
            self.assertEqual(result["metrics"]["annotation_coverage"], 1)
            self.assertEqual(result["metrics"]["coverage_scope"], "exposed_compact_references")
            self.assertEqual(result["metrics"]["retained_nodes"], 73)
            self.assertEqual(result["metrics"]["original_nodes"], 2000)
        self.assertEqual(before, prepared)

    def test_partitions_are_exhaustive_unique_deterministic_and_bounded(self):
        for count in (4, 72, 200, 600):
            document = fixture(count)["documents"][0]
            regions = _regions(document, 80)
            self.assertEqual(regions, _regions(document, 80))
            owned = [key for region in regions for key in region["owned_ids"]]
            self.assertEqual(owned, document["assignable_ids"])
            self.assertEqual(len(owned), len(set(owned)))
            for region in regions:
                self.assertLessEqual(len(region["owned_ids"]), 80)
                self.assertLessEqual(len(region["context_ids"]), MAX_CONTEXT)
                self.assertFalse(set(region["owned_ids"]) & set(region["context_ids"]))
        self.assertEqual(len(_regions(fixture(72)["documents"][0], 160)), 3)

    def test_small_subtrees_are_not_split(self):
        document = fixture(72)["documents"][0]
        # Replace the first leaf with a small semantic subtree.
        document["nodes"][1].update(tag="section", children=["d0:aa", "d0:ab"],
                                     content=[{"id": "d0:aa"}, {"id": "d0:ab"}])
        document["nodes"][2:2] = [node("d0:aa", "d0:1", text="First"), node("d0:ab", "d0:1", text="Second")]
        document["assignable_ids"][2:2] = ["d0:aa", "d0:ab"]
        owner = next(region for region in _regions(document, 80) if "d0:1" in region["owned_ids"])
        self.assertTrue({"d0:1", "d0:aa", "d0:ab"} <= set(owner["owned_ids"]))

    def test_schema_prohibits_context_membership_and_allocates_real_group_ids(self):
        client = FakeClient()
        result = run_compact_comparison(fixture(), "regions", client, "local")
        for request, region in zip(client.requests, result["regions"]):
            props = request["response_schema"]["properties"]
            group_props = props["groups"]["items"]["properties"]
            self.assertEqual(group_props["source_ids"]["items"]["enum"], region["owned_ids"])
            self.assertFalse(set(group_props["source_ids"]["items"]["enum"]) & set(region["context_ids"]))
            self.assertEqual(group_props["id"]["enum"], [f"g{i + 1}" for i in range(request["task"]["group_budget"])])
            self.assertTrue(group_props["parent"]["nullable"])
        self.assertEqual(sum(request["task"]["group_budget"] for request in client.requests), 46)
        self.assertEqual(result["metrics"]["calls"], len(result["regions"]))
        self.assertEqual(result["metrics"]["composition_calls"], 0)
        self.assertTrue(all("compose" not in request["purpose"] for request in client.requests))

    def test_invalid_output_is_rejected_despite_transport_schema(self):
        for answer, error in [
            ({"groups": [group(refs=["unavailable"])], "needs_expansion": []}, "unknown or out-of-region"),
            ({"groups": [group("invented", refs=["d0:1"])], "needs_expansion": []}, "not allocated"),
            ({"groups": [group(refs=["d0:1", "d0:1"])], "needs_expansion": []}, "duplicate source"),
            ({"groups": [group(refs=["d0:1"], parent="g1")], "needs_expansion": []}, "cycle"),
            ({"groups": [], "needs_expansion": ["raw-hidden-id"]}, "observed source"),
        ]:
            with self.subTest(error=error), self.assertRaisesRegex(ComparisonError, error):
                run_compact_comparison(fixture(), "whole", FakeClient(answer), "local")

    def test_expansion_is_recorded_without_second_call_or_raw_source(self):
        client = FakeClient({"groups": [group(refs=["d0:1"])], "needs_expansion": ["d0:0"]})
        result = run_compact_comparison(fixture(), "whole", client, "local")
        self.assertEqual(result["needs_expansion"], ["d0:0"])
        self.assertEqual(result["completeness"], "partial")
        self.assertEqual(len(client.requests), 1)
        self.assertTrue(any("raw source expansion was not sent" in warning for warning in result["warnings"]))
        fallback = next(node for node in result["variant"]["nodes"] if node["origin"] == "source-fallback")
        self.assertEqual(fallback["label"], "Ungrouped compact source")
        self.assertEqual(len(fallback["sourceRefs"]), 72)

    def test_regional_html_keeps_mixed_order_and_all_inherited_markers(self):
        document = fixture()["documents"][0]
        root = document["nodes"][0]
        root["attributes"].update({"data-excerpt": "text", "data-omitted-items": "9", "data-preview": "Visible preview",
                                    "data-relations-deferred": "aria-controls", "data-organizer-context": "original"})
        child = document["nodes"][1]
        child.update(tag="p", children=["d0:aa"], content=["before ", {"id": "d0:aa"}, " after"])
        document["nodes"].insert(2, node("d0:aa", "d0:1", tag="em", text="inside"))
        document["assignable_ids"].insert(2, "d0:aa")
        region = {"owned_ids": ["d0:1", "d0:aa"], "context_ids": ["d0:0"]}
        rendered, context_marker, slice_marker = _regional_html(document, region)
        self.assertEqual(context_marker, "data-organizer-context-1")
        self.assertIn('before <em data-r="d0:aa">inside</em> after', rendered)
        self.assertIn(f'{context_marker}="read-only"', rendered)
        self.assertIn(f'{slice_marker}="partial"', rendered)
        for marker in root["attributes"]:
            self.assertIn(marker, rendered)
        self.assertNotIn('data-r="d0:2"', rendered)

    def test_multidocument_calls_keep_source_namespaces_and_budget(self):
        prepared = fixture(2)
        prepared["documents"].extend(fixture(2, "d1")["documents"])
        client = FakeClient()
        result = run_compact_comparison(prepared, "whole", client, "local")
        self.assertEqual(len(client.requests), 2)
        self.assertNotIn("d1:", client.requests[0]["task"]["html"])
        self.assertNotIn("d0:", client.requests[1]["task"]["html"])
        self.assertEqual(sum(request["task"]["group_budget"] for request in client.requests), 46)
        self.assertEqual(result["metrics"]["annotated_source_nodes"], 6)

    def test_synthetic_nodes_are_context_only_and_never_fallback(self):
        prepared = fixture()
        document = prepared["documents"][0]
        document["nodes"][0]["parent"] = "d0:synthetic-0"
        document["nodes"].insert(0, node("d0:synthetic-0", children=["d0:0"], tag="html", attributes={"lang": "en"}))
        document["roots"] = ["d0:synthetic-0"]
        result = run_compact_comparison(prepared, "regions", FakeClient(), "local")
        self.assertNotIn("d0:synthetic-0", [ref for item in result["variant"]["nodes"] for ref in item["sourceRefs"]])
        self.assertTrue(all("d0:synthetic-0" in region["context_ids"] for region in result["regions"]))

    def test_assembly_preserves_local_tree_and_attaches_only_contained_roots(self):
        nodes = [node("main", children=["section", "aside"]), node("section", "main", ["a", "b"]),
                 node("a", "section"), node("b", "section"), node("aside", "main")]
        groups = [group("parent", ["section"]), group("local", ["a"]), group("nested", ["b"], "local"),
                  group("sibling", ["aside"])]
        before = copy.deepcopy(groups)
        count = _assemble(groups, nodes, {"parent": "r1", "local": "r2", "nested": "r2", "sibling": "r3"})
        self.assertEqual(count, 1)
        self.assertEqual(groups[1]["parent"], "parent")
        self.assertEqual(groups[2]["parent"], "local")
        self.assertIsNone(groups[3]["parent"])
        for new, old in zip(groups, before):
            self.assertEqual(new["source_ids"], old["source_ids"])
            self.assertEqual(new["label"], old["label"])

    def test_readonly_heading_keeps_text_in_nested_inline_descendants(self):
        document = fixture(2)["documents"][0]
        document["nodes"][1].update(tag="h2", children=["d0:aa"],
                                     content=["About ", {"id": "d0:aa"}, " today"])
        document["nodes"].extend([
            node("d0:aa", "d0:1", ["d0:ab"], tag="span", content=["the ", {"id": "d0:ab"}]),
            node("d0:ab", "d0:aa", tag="strong", text="service"),
        ])
        document["assignable_ids"].extend(["d0:aa", "d0:ab"])
        region = {"owned_ids": ["d0:2"], "context_ids": ["d0:0", "d0:1", "d0:aa", "d0:ab"]}
        rendered, context_marker, _ = _regional_html(document, region)
        self.assertIn("About ", rendered)
        self.assertIn(">the <strong", rendered)
        self.assertIn(">service</strong></span> today</h2>", rendered)
        self.assertEqual(rendered.count(f'{context_marker}="read-only"'), 4)

    def test_context_omissions_are_marked_and_excess_ancestry_is_rejected(self):
        document = fixture(1)["documents"][0]
        document["nodes"][0]["content"].insert(0, "Context introduction")
        rendered, _, slice_marker = _regional_html(document, {"owned_ids": ["d0:1"], "context_ids": ["d0:0"]})
        self.assertNotIn("Context introduction", rendered)
        self.assertIn(f'{slice_marker}="partial"', rendered)
        length = MAX_CONTEXT * 3
        nodes = [node(f"d0:{i}", f"d0:{i-1}" if i else None,
                      [f"d0:{i+1}"] if i < length - 1 else [], tag="section") for i in range(length)]
        document.update(nodes=nodes, roots=["d0:0"], assignable_ids=[node["id"] for node in nodes])
        with self.assertRaisesRegex(ComparisonError, "no inherited scope was discarded"):
            _regions(document, 80)

    def test_compact_reference_attribute_is_not_assumed(self):
        prepared = fixture(2)
        document = prepared["documents"][0]
        document["reference_attribute"] = "data-source-ref"
        document["html"] = document["html"].replace("data-r=", "data-source-ref=")
        for item in document["nodes"]:
            item["attributes"]["data-source-ref"] = item["attributes"].pop("data-r")
        client = FakeClient()
        run_compact_comparison(prepared, "regions", client, "local")
        self.assertEqual(client.requests[0]["task"]["reference_attribute"], "data-source-ref")
        self.assertIn('data-source-ref="d0:1"', client.requests[0]["task"]["html"])
        self.assertNotIn("data-r=", client.requests[0]["task"]["html"])

    def test_usage_and_input_bytes_are_actual_separate_from_preparation(self):
        result = run_compact_comparison(fixture(), "regions", FakeClient(), "local")
        self.assertEqual(result["metrics"]["input_tokens"], 33)
        self.assertEqual(result["metrics"]["output_tokens"], 21)
        self.assertEqual(result["metrics"]["input_bytes"], sum(
            len(call["system"].encode()) + len(call["prompt"].encode()) for call in result["calls"]))
        self.assertEqual(result["metrics"]["preparation"]["source_bytes"], 99999)
        self.assertGreater(result["metrics"]["input_bytes"], result["metrics"]["input_chars"])


if __name__ == "__main__":
    unittest.main()
