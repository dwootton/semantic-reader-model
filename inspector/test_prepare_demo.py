"""The public demo is synthetic and must never replace a local corpus."""

import json
from pathlib import Path
import tempfile
import unittest

from inspector.build_data import validate
from scripts.prepare_demo import prepare


class DemoTests(unittest.TestCase):
    def test_installs_valid_synthetic_dataset_and_preserves_catalog_on_repeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "data"
            self.assertTrue(prepare(destination))
            catalog = json.loads((destination / "catalog.json").read_text())
            self.assertTrue(catalog["synthetic"])
            self.assertEqual(len(catalog["datasets"]), 1)
            entry = catalog["datasets"][0]
            dataset = json.loads((destination / f"{entry['id']}.json").read_text())
            self.assertTrue(dataset["synthetic"])
            self.assertGreater(validate(dataset), 0)
            self.assertEqual(entry["domCount"], len(dataset["dom"]["nodes"]))
            before = {path.name: path.read_bytes() for path in destination.iterdir()}
            self.assertFalse(prepare(destination))
            self.assertEqual(before, {path.name: path.read_bytes() for path in destination.iterdir()})

    def test_existing_local_catalog_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            catalog = destination / "catalog.json"
            catalog.write_text("local catalog")
            self.assertFalse(prepare(destination))
            self.assertEqual(catalog.read_text(), "local catalog")
            self.assertEqual(list(destination.iterdir()), [catalog])

    def test_partial_local_data_without_catalog_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            capture = destination / "synthetic-library.json"
            capture.write_text("local content")
            with self.assertRaises(FileExistsError):
                prepare(destination)
            self.assertEqual(capture.read_text(), "local content")
            self.assertEqual(list(destination.iterdir()), [capture])


if __name__ == "__main__":
    unittest.main()
