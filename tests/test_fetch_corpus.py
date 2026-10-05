"""Corpus unpacking uses a synthetic package; no network or hf CLI."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.fetch_corpus import pro_pages, unpack, verify

SITE, PAGE = "a" * 24, "b" * 24
FILES = {
    f"captures/{SITE}/{PAGE}/state-000/document.html": b"<html></html>",
    f"captures/{SITE}/{PAGE}/state-000/compression/document-00000.source-map.json": b"[]",
    f"captures/{SITE}/{PAGE}/state-000/ax.json": b"{}",
    f"labels/{PAGE}-pass1/result.json": b"{}",
    f"labels/inputs/{PAGE}-pass1.json": b"{}",
}


def package(directory, corrupt=None):
    artifacts, buffer = [], io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for i, (logical, data) in enumerate(FILES.items()):
            physical = f"checkpoints/x/{i}.bin"
            artifacts.append({"path": physical, "logical_path": logical, "shard": "artifacts-00001.tar.gz",
                              "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            payload = b"tampered!!!!!" if logical == corrupt else data
            info = tarfile.TarInfo(physical)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    shard = Path(directory) / "artifacts-00001.tar.gz"
    shard.write_bytes(buffer.getvalue())
    return {"artifacts": artifacts, "shards": [
        {"path": shard.name, "sha256": hashlib.sha256(shard.read_bytes()).hexdigest()}]}


class UnpackTest(unittest.TestCase):
    def test_writes_only_wanted_files_at_logical_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, out = package(tmp), Path(tmp) / "out"
            self.assertEqual(unpack(manifest, Path(tmp), out), 3)
            written = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
            self.assertEqual(written, sorted(k for k in FILES if "ax.json" not in k and "inputs" not in k))
            self.assertEqual((out / next(iter(FILES))).read_bytes(), b"<html></html>")
            (out / "export-manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(verify(out), 3)
            (out / next(iter(FILES))).write_bytes(b"edited")
            with self.assertRaisesRegex(ValueError, "checksum"):
                verify(out)

    def test_rejects_tampered_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = package(tmp, corrupt=next(iter(FILES)))
            with self.assertRaisesRegex(ValueError, "checksum"):
                unpack(manifest, Path(tmp), Path(tmp) / "out")

    def test_rejects_tampered_shard(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = package(tmp)
            manifest["shards"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "shard checksum"):
                unpack(manifest, Path(tmp), Path(tmp) / "out")

    def test_never_writes_outside_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = package(tmp)
            manifest["artifacts"][0]["logical_path"] = "captures/../../escape/document.html"
            unpack(manifest, Path(tmp), Path(tmp) / "out")
            self.assertFalse((Path(tmp) / "escape").exists())

    def test_pro_pages(self):
        files = [{"path": f".asta/x/retrieved/captures/{SITE}/{PAGE}/state-000/capture.json"},
                 {"path": ".asta/x/README.md"}]
        self.assertEqual(pro_pages({"files": files}), [f"{SITE}/{PAGE}"])


if __name__ == "__main__":
    unittest.main()
