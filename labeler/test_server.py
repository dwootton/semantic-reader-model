"""Labeler server routes against a temporary corpus; loopback only, no captured data."""

import json
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from server import Handler

SITE, PAGE = "a" * 24, "b" * 24


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        state = root / "corpus/public-research-v1/captures" / SITE / PAGE / "state-000"
        (state / "compression").mkdir(parents=True)
        (state / "document.html").write_text("<script>alert(1)</script>")
        (state / "ax.json").write_text("{}")
        (state / "compression/document-00000.source-map.json").write_text(json.dumps([
            {"id": "0", "tag": "html", "parent": None}, {"id": "1", "tag": "body", "parent": "0"},
            {"id": "2", "tag": "p", "parent": "1"}]))
        (root / "corpus/queue.json").write_text('{"groups": {}}')
        (root / "labels").mkdir()
        (root / "labels/x.json").write_text(json.dumps({"page": f"{SITE}/{PAGE}", "provenance": {"status": "submitted"}}))
        handler = type("TestHandler", (Handler,), {"corpus": root / "corpus", "labels": root / "labels"})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port)
        connection.request(method, path, body, {"Host": f"127.0.0.1:{self.port}", **(headers or {})})
        response = connection.getresponse()
        return response.status, response.getheader("Content-Type"), response.read()

    def test_serves_app_queue_and_capture_files(self):
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/inspector/model.mjs")[0], 200)
        self.assertEqual(self.request("GET", "/corpus/queue.json")[2], b'{"groups": {}}')
        status, kind, body = self.request("GET", f"/corpus/pages/{SITE}/{PAGE}/document.html")
        self.assertEqual((status, body), (200, b"<script>alert(1)</script>"))
        self.assertTrue(kind.startswith("text/plain"))

    def test_refuses_everything_else(self):
        for path in [f"/corpus/pages/{SITE}/{PAGE}/ax.json", f"/corpus/pages/{SITE}/{PAGE}/../../x",
                     "/corpus/pages/zz/yy/document.html", "/server.py", "/inspector/app.mjs",
                     "/corpus/pro-pages.json", "/../.corpus.json", "/%2e%2e/.corpus.json"]:
            self.assertEqual(self.request("GET", path)[0], 404, path)

    def test_rejects_foreign_host_and_origin(self):
        connection = HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", "/", headers={"Host": "evil.example"})
        self.assertEqual(connection.getresponse().status, 403)
        self.assertEqual(self.request("GET", "/", headers={"Origin": "http://evil.example"})[0], 403)

    def test_label_status(self):
        # An old "submitted" label reads as complete.
        self.assertEqual(json.loads(self.request("GET", "/api/labels")[2]), {f"{SITE}/{PAGE}": "complete"})

    def test_corpus_check_report(self):
        report = json.dumps({"checked": 2, "pages": [{"page": f"{SITE}/{PAGE}", "error": "count"}]})
        status, _, _ = self.request("POST", "/api/corpus-check", report, {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads((Path(self.tmp.name) / "corpus/excluded.json").read_text())["checked"], 2)
        bad = json.dumps({"pages": [{"page": "../x"}]})
        self.assertEqual(self.request("POST", "/api/corpus-check", bad, {"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/api/corpus-check", report,
                                      {"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"})[0], 403)

    def post(self, path, payload, headers=None):
        return self.request("POST", path, json.dumps(payload), {"Content-Type": "application/json", **(headers or {})})

    def label(self, status, refs=("src-2",)):
        return {"page": f"{SITE}/{PAGE}", "rootId": "page", "provenance": {"status": status}, "nodes": [
            {"id": "page", "kind": "group", "label": "Page", "children": ["u"], "sourceRefs": []},
            {"id": "u", "kind": "dom", "label": "Para", "children": [], "sourceRefs": list(refs)}]}

    def test_in_progress_save_and_load(self):
        status, _, _ = self.post("/api/labels", self.label("in_progress", refs=("src-missing",)))
        self.assertEqual(status, 200, "in-progress labels are saved even when invalid")
        status, _, body = self.request("GET", f"/api/labels/{SITE}/{PAGE}")
        saved = json.loads(body)
        self.assertEqual((status, saved["provenance"]["status"]), (200, "in_progress"))
        self.assertIn("labeler", saved["provenance"])
        self.assertEqual(self.request("GET", "/api/labels/../x")[0], 400)

    def test_complete_is_validated_against_the_source_map(self):
        status, _, body = self.post("/api/labels", self.label("complete", refs=("src-missing",)))
        result = json.loads(body)
        self.assertEqual((status, result["status"]), (200, "in_progress"), "an invalid complete label is kept, as in progress")
        self.assertIn("dangling", result["note"])
        status, _, body = self.post("/api/labels", self.label("complete"))
        self.assertEqual((status, json.loads(body)["status"]), (200, "complete"))
        saved = json.loads((Path(self.tmp.name) / f"labels/{SITE}__{PAGE}.json").read_text())
        self.assertIn("completed_at", saved["provenance"])
        self.assertEqual(self.post("/api/labels", {**self.label("in_progress"), "page": "../../x"})[0], 400)
        self.assertEqual(self.post("/api/labels", self.label("submitted"))[0], 400)

    def test_export_writes_a_valid_dataset(self):
        dom = {"roots": ["src-0"], "nodes": [{"id": "src-0", "parent": None, "children": ["src-2"]},
                                              {"id": "src-2", "parent": "src-0", "children": []}]}
        dataset = {"id": f"label-{PAGE}", "dom": dom, "variants": {"gold": self.label("complete")}}
        self.assertEqual(self.post("/api/export", dataset)[0], 200)
        self.assertTrue((Path(self.tmp.name) / f"labels/datasets/label-{PAGE}.json").exists())
        self.assertEqual(self.post("/api/export", {**dataset, "id": "../x"})[0], 400)


if __name__ == "__main__":
    unittest.main()
