import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from inspector import compact_input
from inspector.compact_input import CompactInputError, load_compact


class CorpusTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("SEMANTIC_LOCAL_CORPUS_TESTS") == "1",
                         "Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original compression artifacts")
    def test_all_budget_documents_have_known_unique_references_and_reciprocal_edges(self):
        report = json.loads((compact_input.ARTIFACT_ROOT / "report.json").read_text())
        datasets = sorted({item["dataset"] for item in report["inventory"]})
        self.assertEqual(len(datasets), 14)
        documents = 0
        for dataset_id in datasets:
            with self.subTest(dataset=dataset_id):
                compact = load_compact(dataset_id)
                documents += len(compact["documents"])
                view = compact["dataset"]
                self.assertEqual(view["variants"], {})
                self.assertIsNone(view["screenshot"])
                nodes = view["dom"]["nodes"]
                by_id = {node["id"]: node for node in nodes}
                self.assertEqual(len(nodes), len(by_id))
                self.assertEqual(set(view["dom"]["roots"]),
                                 {node["id"] for node in nodes if node["parent"] is None})
                for node in nodes:
                    if node["parent"] is not None:
                        self.assertIn(node["id"], by_id[node["parent"]]["children"])
                    for child in node["children"]:
                        self.assertEqual(by_id[child]["parent"], node["id"])
                    self.assertEqual([part["id"] for part in node["content"] if isinstance(part, dict)],
                                     node["children"])
                for doc, provenance in zip(compact["documents"], compact["provenance"]["documents"]):
                    ledger_file = provenance["artifacts"]["sourceMap"]["file"]
                    ledger = json.loads((compact_input.ARTIFACT_ROOT / ledger_file).read_text())
                    retained = {entry["id"] for entry in ledger if entry["disposition"] == "retained"}
                    self.assertTrue(set(provenance["reference_mapping"]) <= retained)
                    self.assertEqual(doc["assignable_ids"],
                                     [node["id"] for node in doc["nodes"] if node["assignable"]])
                    self.assertEqual(set(doc["assignable_ids"]),
                                     set(provenance["reference_mapping"].values()))
                    # Reversing marker namespacing recovers exact audited bytes.
                    html = doc["html"]
                    for old, new in provenance["reference_mapping"].items():
                        html = html.replace(f'{doc["reference_attribute"]}="{new}"',
                                            f'{doc["reference_attribute"]}="{old}"')
                    for old, new in provenance["reference_mapping"].items():
                        html = html.replace(f'data-target-ref="{new}"', f'data-target-ref="{old}"')
                    original = compact_input.ARTIFACT_ROOT / provenance["artifacts"]["html"]["file"]
                    self.assertEqual(html, original.read_text())
                    self.assertNotIn("sourceMap", doc["html"])
                    self.assertNotIn("representedBy", doc["html"])
                    self.assertTrue(all(not node["assignable"] for node in doc["nodes"]
                                        if ":synthetic-" in node["id"]))
                metrics = compact["metrics"]
                self.assertEqual(metrics["original_nodes"],
                                 sum(metrics[key] for key in ("exposed_nodes", "deferred_nodes",
                                                              "collapsed_nodes", "excluded_nodes")))
        self.assertEqual(documents, 15)

    @unittest.skipUnless(os.environ.get("SEMANTIC_LOCAL_CORPUS_TESTS") == "1",
                         "Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original compression artifacts")
    def test_partial_scope_inherits_and_edges_are_from_emitted_html(self):
        compact = load_compact("gov-uk")
        nodes = {node["id"]: node for node in compact["dataset"]["dom"]["nodes"]}
        self.assertNotIn("e0", nodes)
        for node in nodes.values():
            with self.subTest(node=node["id"]):
                self.assertEqual(node["partial"], bool(node["partial_sources"]))
                if node["parent"]:
                    parent = nodes[node["parent"]]
                    self.assertTrue(set(parent["partial_sources"]) <= set(node["partial_sources"]))
                    if parent["hidden"]:
                        self.assertTrue(node["hidden"])

    @unittest.skipUnless(os.environ.get("SEMANTIC_LOCAL_CORPUS_TESTS") == "1",
                         "Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original compression artifacts")
    def test_ewh_contains_both_documents_with_distinct_namespaces(self):
        compact = load_compact("ewh-dashboard")
        self.assertEqual([doc["id"] for doc in compact["documents"]],
                         ["ewh-dashboard--dom", "ewh-dashboard--shell"])
        first, second = compact["documents"]
        self.assertTrue(all(key.startswith("d0:") for key in first["assignable_ids"]))
        self.assertTrue(all(key.startswith("d1:") for key in second["assignable_ids"]))
        self.assertFalse(set(first["assignable_ids"]) & set(second["assignable_ids"]))

    @unittest.skipUnless(os.environ.get("SEMANTIC_LOCAL_CORPUS_TESTS") == "1",
                         "Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original compression artifacts")
    def test_passing_alternate_profiles_can_load(self):
        for profile in ("structure", "excerpt"):
            with self.subTest(profile=profile):
                self.assertGreater(load_compact("gov-uk", profile)["metrics"]["exposed_nodes"], 0)

    def test_mixed_text_order_and_collision_marker_are_preserved(self):
        html = '<html><head></head><body data-r-x="2"><p data-r-x="3">Before <b data-r-x="4">middle</b> after.</p></body></html>'
        ledger = {key: {"id": key, "tag": tag, "disposition": "retained"}
                  for key, tag in (("2", "body"), ("3", "p"), ("4", "b"))}
        parser = compact_input._ObservedHTML(html, "data-r-x", "d0", "test", ledger)
        output = parser.finish()
        paragraph = next(node for node in parser.nodes if node["id"] == "d0:3")
        self.assertEqual(paragraph["text"], "Before middle after.")
        self.assertEqual(paragraph["content"], ["Before ", {"id": "d0:4"}, " after."])
        self.assertIn('data-r-x="d0:4"', output)


class ReferenceParserTests(unittest.TestCase):
    def test_fragment_targets_are_namespaced_but_opaque_destinations_are_not(self):
        html = ('<div data-r="0"><a data-target-ref="2" data-r="1" '
                'data-destination-id="u0" data-missing-aria-describedby="missing">Jump</a>'
                '<p data-r="2">Target</p></div>')
        ledger = {key: {"tag": tag, "disposition": "retained"}
                  for key, tag in (("0", "div"), ("1", "a"), ("2", "p"))}
        for namespace in ("d0", "d1"):
            with self.subTest(namespace=namespace):
                parser = compact_input._ObservedHTML(html, "data-r", namespace, "test", ledger)
                output = parser.finish()
                link = parser.nodes[1]
                self.assertEqual(link["attributes"]["data-target-ref"], f"{namespace}:2")
                self.assertIn(f'data-target-ref="{namespace}:2"', output)
                self.assertIn('data-destination-id="u0"', output)
                self.assertIn('data-missing-aria-describedby="missing"', output)
                restored = output.replace(f'{namespace}:', '')
                self.assertEqual(restored, html)

    def test_target_must_be_emitted_even_when_present_in_ledger(self):
        ledger = {"0": {"tag": "a", "disposition": "retained"},
                  "2": {"tag": "p", "disposition": "retained"}}
        for target in ("2", "u0", "synthetic-0", "d1:2"):
            with self.subTest(target=target), self.assertRaisesRegex(CompactInputError, "target reference"):
                html = f'<a data-r="0" data-target-ref="{target}">Jump</a>'
                compact_input._ObservedHTML(html, "data-r", "d0", "test", ledger).finish()

    def test_svg_text_preserves_nested_order(self):
        html = '<svg data-r="0"><text data-r="1">Sales <tspan data-r="2">up</tspan></text></svg>'
        ledger = {key: {"tag": tag, "disposition": "retained"}
                  for key, tag in (("0", "svg"), ("1", "text"), ("2", "tspan"))}
        parser = compact_input._ObservedHTML(html, "data-r", "d0", "test", ledger)
        parser.finish()
        self.assertEqual(parser.nodes[0]["text"], "Sales up")


@unittest.skipUnless(os.environ.get("SEMANTIC_LOCAL_CORPUS_TESTS") == "1",
                     "Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original compression artifacts")
class IntegrityTests(unittest.TestCase):
    """Mutate isolated evidence copies, never the user's compression artifacts."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="compact-input-test-")
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        artifacts = root / "artifacts"
        artifacts.mkdir()
        original_root = compact_input.ROOT
        original_artifacts = compact_input.ARTIFACT_ROOT
        original_report = json.loads((original_artifacts / "report.json").read_text())
        item = next(item for item in original_report["inventory"] if item["dataset"] == "gov-uk")
        row = next(row for row in original_report["results"]
                   if row["dataset"] == "gov-uk" and row["profile"] == "budget")
        self.report = {**original_report, "inventory": [copy.deepcopy(item)], "results": [copy.deepcopy(row)]}
        scripts = root / "experiments/dom-downsampling"
        scripts.mkdir(parents=True)
        for filename in ("compact.py", "compact.js"):
            shutil.copyfile(original_root / "experiments/dom-downsampling" / filename, scripts / filename)
        for metadata in [row["sourceArtifact"], *row["artifacts"].values()]:
            shutil.copyfile(original_artifacts / metadata["file"], artifacts / metadata["file"])
        self.source = root / "examples/vision-study/captures/gov-uk/page.html"
        self.source.parent.mkdir(parents=True)
        shutil.copyfile(Path(item["path"]), self.source)
        self.report["inventory"][0]["path"] = str(self.source)
        self.report["results"][0]["sourcePath"] = str(self.source)
        self.artifacts = artifacts
        self.root = root
        self.save_report()
        self.addCleanup(patch.stopall)
        patch.object(compact_input, "ROOT", root).start()
        patch.object(compact_input, "ARTIFACT_ROOT", artifacts).start()

    def save_report(self):
        (self.artifacts / "report.json").write_text(json.dumps(self.report))

    def rehash(self, metadata):
        raw = (self.artifacts / metadata["file"]).read_bytes()
        metadata.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.save_report()

    def test_original_current_source_is_checked(self):
        self.source.write_text(self.source.read_text() + "stale")
        with self.assertRaisesRegex(CompactInputError, "current original source"):
            load_compact("gov-uk")

    def test_all_artifact_types_are_hash_checked(self):
        row = self.report["results"][0]
        for metadata in [row["sourceArtifact"], *row["artifacts"].values()]:
            path = self.artifacts / metadata["file"]
            original = path.read_bytes()
            with self.subTest(artifact=path.name):
                path.write_bytes(original + b"tampered")
                with self.assertRaisesRegex(CompactInputError, "size/SHA256 mismatch"):
                    load_compact("gov-uk")
                path.write_bytes(original)

    def test_same_size_hash_tamper_is_detected(self):
        metadata = self.report["results"][0]["artifacts"]["html"]
        path = self.artifacts / metadata["file"]
        original = path.read_bytes()
        path.write_bytes(b"X" + original[1:])
        with self.assertRaisesRegex(CompactInputError, "size/SHA256 mismatch"):
            load_compact("gov-uk")

    def test_compressor_and_runner_changes_require_regeneration(self):
        for filename in ("compact.py", "compact.js"):
            path = self.root / "experiments/dom-downsampling" / filename
            original = path.read_bytes()
            with self.subTest(script=filename):
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(CompactInputError, "SHA256 changed"):
                    load_compact("gov-uk")
                path.write_bytes(original)

    def test_audit_checks_must_be_nonempty_true_booleans(self):
        row = self.report["results"][0]
        for checks in ({}, {"stableHTML": True}, {"stableHTML": 1}, {"stableHTML": "true"}, {"stableHTML": False}):
            with self.subTest(checks=checks):
                row["checks"] = checks
                self.save_report()
                with self.assertRaisesRegex(CompactInputError, "audit did not pass"):
                    load_compact("gov-uk")

    def test_missing_or_duplicate_document_results_are_rejected(self):
        original = copy.deepcopy(self.report["results"])
        for rows in ([], original * 2):
            with self.subTest(count=len(rows)):
                self.report["results"] = rows
                self.save_report()
                with self.assertRaisesRegex(CompactInputError, "document results"):
                    load_compact("gov-uk")

    def test_every_inventoried_document_is_required(self):
        self.report["inventory"].append({**self.report["inventory"][0], "id": "gov-uk--second", "document": "second"})
        self.save_report()
        with self.assertRaisesRegex(CompactInputError, "document results"):
            load_compact("gov-uk")

    def test_artifact_path_traversal_and_symlink_escape_are_rejected(self):
        metadata = self.report["results"][0]["artifacts"]["html"]
        for filename in ("../secret.html", str(self.source)):
            with self.subTest(path=filename):
                metadata["file"] = filename
                self.save_report()
                with self.assertRaisesRegex(CompactInputError, "Unsafe artifact path"):
                    load_compact("gov-uk")
        link = self.artifacts / "escaping-link.html"
        link.symlink_to(self.source)
        metadata["file"] = link.name
        self.save_report()
        with self.assertRaisesRegex(CompactInputError, "Unsafe artifact path"):
            load_compact("gov-uk")

    def test_invalid_dataset_profile_and_unknown_dataset_are_rejected(self):
        for dataset in ("../gov-uk", "gov-uk/../../secret", "", "missing"):
            with self.subTest(dataset=dataset), self.assertRaises(CompactInputError):
                load_compact(dataset)
        with self.assertRaises(CompactInputError):
            load_compact("gov-uk", "unknown")

    def test_request_cannot_smuggle_source_map_even_with_updated_hash(self):
        metadata = self.report["results"][0]["artifacts"]["request"]
        path = self.artifacts / metadata["file"]
        request = json.loads(path.read_text())
        user = json.loads(request["user"])
        user["sourceMap"] = [{"id": "SECRET_NOT_OBSERVED"}]
        request["user"] = json.dumps(user)
        path.write_text(json.dumps(request))
        self.rehash(metadata)
        with self.assertRaisesRegex(CompactInputError, "does not match compact HTML"):
            load_compact("gov-uk")

    def test_unknown_emitted_reference_cannot_pass_with_updated_artifact_hashes(self):
        row = self.report["results"][0]
        metadata = row["artifacts"]["html"]
        path = self.artifacts / metadata["file"]
        html = path.read_text().replace('data-r="3"', 'data-r="zzzz"', 1)
        path.write_text(html)
        self.rehash(metadata)
        request_metadata = row["artifacts"]["request"]
        request_path = self.artifacts / request_metadata["file"]
        request = json.loads(request_path.read_text())
        user = json.loads(request["user"])
        user["html"] = html
        request["user"] = json.dumps(user)
        request_path.write_text(json.dumps(request))
        self.rehash(request_metadata)
        row["htmlBytes"] = len(html.encode("utf-8"))
        row["requestInputBytes"] = sum(len(value.encode("utf-8")) for value in request.values())
        self.save_report()
        with self.assertRaisesRegex(CompactInputError, "Unknown emitted compact reference"):
            load_compact("gov-uk")


if __name__ == "__main__":
    unittest.main()
