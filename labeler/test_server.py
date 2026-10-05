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
        self.assertEqual(json.loads(self.request("GET", "/api/labels")[2]), {f"{SITE}/{PAGE}": "submitted"})

    def test_corpus_check_report(self):
        report = json.dumps({"checked": 2, "pages": [{"page": f"{SITE}/{PAGE}", "error": "count"}]})
        status, _, _ = self.request("POST", "/api/corpus-check", report, {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads((Path(self.tmp.name) / "corpus/excluded.json").read_text())["checked"], 2)
        bad = json.dumps({"pages": [{"page": "../x"}]})
        self.assertEqual(self.request("POST", "/api/corpus-check", bad, {"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/api/corpus-check", report,
                                      {"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"})[0], 403)


if __name__ == "__main__":
    unittest.main()
