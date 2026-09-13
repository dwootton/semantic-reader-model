"""Behavioral contracts for snapshot disclosure and navigation accounting."""

import copy
import json
import unittest

from harness.reader import Reader, ReaderError, baseline_projection, validate_projection


def snapshot():
    def node(sid, role, name, children=(), bid=None, value=""):
        return dict(id=sid, role=role, name=name, children=list(children), bid=bid, value=value)
    return {
        "snapshot_id": "snapshot-one", "url": "http://site.local/orders",
        "nodes": [node("root", "RootWebArea", "Store", ["main", "footer"]),
                  node("main", "main", "Orders", ["heading", "input", "save", "text"]),
                  node("heading", "heading", "Order history"),
                  node("input", "textbox", "Order number", bid="b-input"),
                  node("save", "button", "Save order", bid="b-save"),
                  node("text", "StaticText", "Private-until-revealed detail", bid="wrapper"),
                  node("footer", "contentinfo", "Help", ["link"]),
                  node("link", "link", "Contact support", bid="b-link"),
                  node("orphan", "StaticText", "Disconnected capture content")],
        "roots": ["root"],
    }


def projection():
    return {"groups": [
        dict(id="orders", label="Find and edit orders", parent=None, source_ids=["heading", "input", "save"]),
        dict(id="edit", label="Edit order", parent="orders", source_ids=["input", "save"]),
    ]}


class ReaderTests(unittest.TestCase):
    def test_local_disclosure_and_undisclosed_action_rejection(self):
        reader = Reader(snapshot(), projection())
        first = reader.view()
        self.assertEqual([item["id"] for item in first["items"]], ["g:orders"])
        self.assertNotIn("Private-until-revealed", json.dumps(first))
        with self.assertRaises(ReaderError):
            reader.step(dict(op="activate", target="s:save"))
        second = reader.step(dict(op="expand", target="g:orders"))
        self.assertEqual([item["id"] for item in second["items"]], ["g:edit", "s:heading"])
        reader.step(dict(op="expand", target="g:edit"))
        result = reader.step(dict(op="fill", target="s:input", value="123"))
        self.assertEqual(result["browser_action"], dict(kind="fill", bid="b-input", value="123"))
        self.assertEqual(reader.step(dict(op="activate", target="s:save"))["browser_action"], dict(kind="click", bid="b-save"))

    def test_every_source_node_reachable_even_if_projection_omits_it(self):
        reader = Reader(snapshot(), {"groups": []}, page_size=2)
        view = reader.step(dict(op="source"))
        observed = set()

        def traverse(page):
            while True:
                for item in page["items"]:
                    observed.add(item["id"][2:])
                    if item["expandable"]:
                        traverse(reader.step(dict(op="expand", target=item["id"])))
                        reader.step(dict(op="up"))
                if page["page"] == page["pages"]:
                    return
                page = reader.step(dict(op="next"))

        traverse(view)
        self.assertEqual(observed, {node["id"] for node in snapshot()["nodes"]})

    def test_pagination_restores_cursor_and_rejects_off_page_targets(self):
        reader = Reader(snapshot(), projection(), page_size=1)
        first = reader.step(dict(op="controls"))
        self.assertEqual(first["items"][0]["id"], "s:input")
        second = reader.step(dict(op="next"))
        self.assertEqual(second["items"][0]["id"], "s:save")
        with self.assertRaises(ReaderError):
            reader.step(dict(op="fill", target="s:input", value="3"))
        reader.step(dict(op="headings"))
        self.assertEqual(reader.step(dict(op="up"))["page"], 2)
        self.assertEqual(reader.step(dict(op="previous"))["items"][0]["id"], "s:input")
        with self.assertRaises(ReaderError):
            reader.step(dict(op="previous"))

    def test_metrics_charge_repeated_observations_and_separate_actions(self):
        reader = Reader(snapshot(), projection())
        first = reader.view()
        payload = {key: value for key, value in first.items() if key not in {"accounting", "totals"}}
        expected = len(json.dumps(payload, ensure_ascii=False, sort_keys=True).split())
        self.assertEqual(first["accounting"], dict(words=expected, choices=1))
        repeated = reader.view()
        self.assertEqual(repeated["totals"]["words"], expected * 2)
        self.assertEqual(repeated["totals"]["choices"], 2)
        reader.step(dict(op="controls"))
        result = reader.step(dict(op="activate", target="s:save"))
        self.assertEqual(result["totals"]["navigation_moves"], 1)
        self.assertEqual(result["totals"]["browser_actions"], 1)
        self.assertEqual(result["totals"]["observations"], 3)
        self.assertEqual(result["accounting"], dict(words=0, choices=0))
        self.assertNotIn("items", result)

    def test_bid_on_static_wrapper_does_not_make_it_actionable(self):
        reader = Reader(snapshot(), {"groups": [dict(id="text", label="Text", parent=None, source_ids=["text"])]})
        reader.view()
        view = reader.step(dict(op="expand", target="g:text"))
        self.assertEqual(view["items"][0]["actions"], [])
        with self.assertRaises(ReaderError):
            reader.step(dict(op="activate", target="s:text"))

    def test_fill_requires_an_exposed_editable_role_and_string_value(self):
        reader = Reader(snapshot(), projection())
        reader.step(dict(op="controls"))
        for action in [dict(op="fill", target="s:save", value="text"), dict(op="fill", target="s:input", value=123)]:
            with self.subTest(action=action), self.assertRaises(ReaderError):
                reader.step(action)

    def test_native_description_and_scalar_states_preserved_without_dom_relations(self):
        source = snapshot()
        source["nodes"][3].update(
            description="Enter the order identifier from your receipt.",
            properties=[
                {"name": "required", "value": {"value": True}},
                {"name": "invalid", "value": {"value": "false"}},
                {"name": "valuemin", "value": {"value": 0}},
                {"name": "valuetext", "value": {"value": "Three orders"}},
                {"name": "checked", "value": {"value": ["not", "scalar"]}},
                {"name": "labelledby", "value": {"value": "hidden-dom-id"}},
            ],
        )
        view = Reader(source, projection()).step(dict(op="controls"))
        item = next(item for item in view["items"] if item["id"] == "s:input")
        self.assertEqual(item["description"], source["nodes"][3]["description"])
        self.assertEqual(item["states"], dict(required=True, invalid="false", valuemin=0, valuetext="Three orders"))
        self.assertNotIn("hidden-dom-id", json.dumps(view))

    def test_native_shortcuts_identical_across_projections(self):
        source = snapshot()
        for op in ("headings", "landmarks", "controls"):
            generated = Reader(source, projection()).step(dict(op=op))
            baseline = Reader(source, baseline_projection(source)).step(dict(op=op))
            self.assertEqual(generated, baseline)

    def test_snapshot_revision_and_external_mutations_do_not_expose_stale_ids(self):
        source = snapshot()
        reader = Reader(source, projection())
        reader.step(dict(op="controls"))
        source["nodes"][3]["bid"] = "changed"
        self.assertEqual(reader.step(dict(op="activate", target="s:input"))["browser_action"]["bid"], "b-input")
        source["snapshot_id"] = "snapshot-two"
        fresh = Reader(source, projection())
        fresh.view()
        with self.assertRaises(ReaderError):
            fresh.step(dict(op="activate", target="s:input"))

    def test_rejects_invalid_projection_and_source_topology(self):
        bad_variants = []
        unknown_source = projection()
        unknown_source["groups"][0]["source_ids"].append("missing")
        bad_variants.append(unknown_source)
        duplicate = projection()
        duplicate["groups"].append(copy.deepcopy(duplicate["groups"][0]))
        bad_variants.append(duplicate)
        cycle = projection()
        cycle["groups"][0]["parent"] = "edit"
        bad_variants.append(cycle)
        unknown_parent = projection()
        unknown_parent["groups"][0]["parent"] = "missing"
        bad_variants.append(unknown_parent)
        for bad in bad_variants:
            with self.subTest(projection=bad), self.assertRaises(ReaderError):
                validate_projection(snapshot(), bad)
        source = snapshot()
        source["nodes"][0]["children"].append("root")
        with self.assertRaises(ReaderError):
            Reader(source, projection())
        source = snapshot()
        source["nodes"].append(copy.deepcopy(source["nodes"][0]))
        with self.assertRaises(ReaderError):
            Reader(source, projection())

    def test_invalid_operations_leave_counters_unchanged(self):
        reader = Reader(snapshot(), projection())
        reader.view()
        before = dict(reader.totals)
        for action in [dict(op="search", value="private"), dict(op="up"), dict(op="activate", target="g:orders")]:
            with self.subTest(action=action), self.assertRaises(ReaderError):
                reader.step(action)
        self.assertEqual(reader.totals, before)


if __name__ == "__main__":
    unittest.main()
