import json
import os
import unittest
from pathlib import Path

import tempfile

from build_data import dom, import_datasets, validate, variant


class DataExportTests(unittest.TestCase):
    def fixture(self):
        return {"dom": {"roots": ["a"], "nodes": [
            {"id": "a", "parent": None, "children": ["b"]},
            {"id": "b", "parent": "a", "children": []}]},
            "variants": {"revised": {"rootId": "g", "nodes": [
                {"id": "g", "children": [], "sourceRefs": ["a", "b"]}]}}}

    def test_missing_source_ref_is_rejected(self):
        fixture = self.fixture()
        fixture["variants"]["revised"]["nodes"][0]["sourceRefs"].append("invented")
        with self.assertRaisesRegex(AssertionError, "dangling source reference invented"):
            validate(fixture)

    def test_broken_parent_link_is_rejected(self):
        fixture = self.fixture()
        fixture["dom"]["nodes"][1]["parent"] = None
        with self.assertRaisesRegex(AssertionError, "nonreciprocal child"):
            validate(fixture)

    def test_unreachable_hierarchy_is_rejected(self):
        fixture = self.fixture()
        fixture["variants"]["revised"]["nodes"].append({"id": "orphan", "children": [], "sourceRefs": []})
        with self.assertRaisesRegex(AssertionError, "unreachable nodes"):
            validate(fixture)

    def test_script_style_text_is_not_exported(self):
        for tag in ("script", "style"):
            result = dom({"elements": [{"id": "a", "tag": tag, "text": "source code", "own_text": "source code"}]})
            self.assertEqual(result["nodes"][0]["text"], "")
            self.assertEqual(result["nodes"][0]["ownText"], "")

    def test_variant_keeps_multiple_source_refs_and_order(self):
        result = variant({"root_id": "g", "nodes": [{"id": "g", "source_refs": ["b", "a", "b"]}]})
        self.assertEqual(result["nodes"][0]["sourceRefs"], ["b", "a", "b"])

    @unittest.skipUnless(os.environ.get("SEMANTIC_LOCAL_CORPUS_TESTS") == "1",
                         "Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original 14-site corpus")
    def test_every_export_and_screenshot(self):
        directory = Path(__file__).parent / "data"
        catalog = json.loads((directory / "catalog.json").read_text())["datasets"]
        self.assertGreaterEqual(len(catalog), 14)
        for entry in catalog:
            dataset = json.loads((directory / f"{entry['id']}.json").read_text())
            with self.subTest(dataset=entry["id"]):
                self.assertGreater(validate(dataset), 0)
                self.assertEqual(entry["domCount"], len(dataset["dom"]["nodes"]))
                if entry["hasScreenshot"]:
                    image = directory.parent / dataset["screenshot"]["url"]
                    self.assertEqual(image.read_bytes()[:3], b"\xff\xd8\xff")
                if entry["id"] == "ewh-dashboard":
                    self.assertEqual(len(dataset["dom"]["roots"]), 2)
                    self.assertIsNone(dataset["screenshot"])
                if entry["id"] == "nyt-homepage":
                    self.assertEqual(list(dataset["variants"]), ["revised", "condensed"])
                if entry["id"].startswith("sft109-"):
                    self.assertEqual(list(dataset["variants"]), ["sft-109", "silver-reference", "gold"])
                    self.assertEqual([v.get("setting") for v in entry["variants"]], [None, None, "gold"])
                    self.assertEqual(dataset["screenshot"]["kind"], "wireframe")
                    for tree in dataset["variants"].values():
                        self.assertFalse(tree["provenance"].get("unmapped_refs"))
                    self.assertEqual(dataset["variants"]["gold"]["provenance"]["kind"], "authored-gold-candidate")

    def import_fixture(self):
        return {"id": "demo", "label": "Demo", "url": "", "screenshot": None, "limitations": [],
                "dom": {"roots": ["a"], "nodes": [
                    {"id": "a", "parent": None, "children": ["b"], "tag": "body"},
                    {"id": "b", "parent": "a", "children": [], "tag": "p"}]},
                "variants": {"sft-109": {"rootId": "g", "nodes": [
                    {"id": "g", "kind": "group", "label": "Page", "children": ["u"], "sourceRefs": ["a"]},
                    {"id": "u", "kind": "dom", "label": "Text", "children": [], "sourceRefs": ["b"]}]}}}

    def test_import_datasets_adds_catalog_entry_and_rejects_bad_trees(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, source = Path(tmp) / "out", Path(tmp) / "src"
            output.mkdir()
            source.mkdir()
            (output / "catalog.json").write_text(json.dumps({"datasets": [{"id": "other", "variants": []}]}))
            (source / "demo.json").write_text(json.dumps(self.import_fixture()))
            import_datasets(output, source)
            catalog = json.loads((output / "catalog.json").read_text())["datasets"]
            self.assertEqual([e["id"] for e in catalog], ["other", "demo"])
            self.assertEqual(catalog[1]["variants"], [{"id": "sft-109", "label": "Qwen3.5-9B SFT-109 output"}])
            gated = self.import_fixture()
            gated["variantSettings"] = {"sft-109": "gold"}
            (source / "demo.json").write_text(json.dumps(gated))
            import_datasets(output, source)
            catalog = json.loads((output / "catalog.json").read_text())["datasets"]
            self.assertEqual(catalog[1]["variants"][0]["setting"], "gold")
            self.assertFalse(catalog[1]["hasScreenshot"])
            self.assertEqual(catalog[1]["domCount"], 2)
            broken = self.import_fixture()
            broken["variants"]["sft-109"]["nodes"][1]["sourceRefs"] = ["missing"]
            (source / "demo.json").write_text(json.dumps(broken))
            with self.assertRaises(ValueError):
                import_datasets(output, source)
            # A rejected import must not disturb the earlier export.
            self.assertEqual(json.loads((output / "demo.json").read_text())["variants"]["sft-109"]["nodes"][1]["sourceRefs"], ["b"])


if __name__ == "__main__":
    unittest.main()
