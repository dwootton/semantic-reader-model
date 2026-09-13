"""Guard artifact provenance and source-reference joins used by the comparison UI."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from inspector.build_compression_data import validate_mapping, verified_artifact


class CompressionDataTests(unittest.TestCase):
    def setUp(self):
        self.source = {"nodes": [
            {"id": "0", "tag": "html"}, {"id": "1", "tag": "head"},
            {"id": "2", "tag": "body"}, {"id": "3", "tag": "div"}]}
        self.mapping = [{**n, "disposition": "retained" if n["id"] != "3" else "collapsed"}
                        for n in self.source["nodes"]]
        self.tree = {"nodes": [{"id": "c0", "tag": "html", "sourceId": None},
                               {"id": "c1", "tag": "head", "sourceId": None},
                               {"id": "c2", "tag": "body", "sourceId": "2"}]}
        self.report = {"sourceElements": 4, "outputElements": 3}

    def test_native_roots_receive_exact_references(self):
        validate_mapping(self.source, self.tree, self.mapping, self.report)
        self.assertEqual([n["sourceId"] for n in self.tree["nodes"]], ["0", "1", "2"])

    def test_reordered_source_inventory_fails(self):
        self.mapping[2], self.mapping[3] = self.mapping[3], self.mapping[2]
        with self.assertRaisesRegex(ValueError, "preorder"):
            validate_mapping(self.source, self.tree, self.mapping, self.report)

    def test_duplicate_reference_fails(self):
        self.tree["nodes"][2] = {"id": "c2", "tag": "html", "sourceId": "0"}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_mapping(self.source, self.tree, self.mapping, self.report)

    def test_retained_inventory_mismatch_fails(self):
        self.mapping[3]["disposition"] = "retained"
        with self.assertRaisesRegex(ValueError, "retained"):
            validate_mapping(self.source, self.tree, self.mapping, self.report)

    def test_template_logical_parent_does_not_break_identity(self):
        mapping = copy.deepcopy(self.mapping)
        for n in mapping:
            n["parent"] = None
        validate_mapping(self.source, self.tree, mapping, self.report)

    def test_artifact_tampering_and_traversal_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "snapshot").write_bytes(b"source")
            entry = {"file": "snapshot", "bytes": 6,
                     "sha256": hashlib.sha256(b"source").hexdigest()}
            self.assertEqual(verified_artifact(directory, entry), b"source")
            (directory / "snapshot").write_bytes(b"change")
            with self.assertRaisesRegex(ValueError, "hash/length"):
                verified_artifact(directory, entry)
            with self.assertRaisesRegex(ValueError, "escapes"):
                verified_artifact(directory, {**entry, "file": "../snapshot"})


if __name__ == "__main__":
    unittest.main()
