"""Serve the labeling tool on loopback. Read-only access to the local corpus; no cloud calls.

Routes:
  GET  /                                   the labeler page; other labeler/*.html|*.mjs|*.css by name
  GET  /inspector/model.mjs                shared tree helpers reused from the inspector
  GET  /corpus/queue.json                  page order (labeler/queue_order.py)
  GET  /corpus/pages/<site>/<page>/<file>  one of the six desktop capture files
  GET  /api/labels                         {page: status} for label files in runs/labels/
  POST /api/corpus-check                   writes runs/corpus/excluded.json from the in-browser check
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(APP))
from queue_order import CAPTURE_FILES, STATE  # noqa: E402

INSPECTOR_MODULES = {"model.mjs"}
TYPES = {".html": "text/html; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}
PAGE_FILE = re.compile(r"/corpus/pages/([0-9a-f]{24})/([0-9a-f]{24})/(.+)")
MAX_POST = 4 << 20


class Server(ThreadingHTTPServer):
    request_queue_size = 64  # the page view fetches six files at once; the default backlog of 5 drops some


class Handler(BaseHTTPRequestHandler):
    corpus = ROOT / "runs/corpus"
    labels = ROOT / "runs/labels"

    def log_message(self, *args):
        pass

    def _allowed(self, mutation=False):
        try:
            authority = urlsplit("http://" + self.headers.get("Host", ""))
            if authority.hostname not in {"localhost", "127.0.0.1"} or authority.port != self.server.server_address[1]:
                return False
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != authority.netloc:
                return False
            return not (mutation and self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"})
        except ValueError:
            return False

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' "
                         "'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                         "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload).encode())

    def _file(self, path, content_type=None):
        if not path.is_file():
            return self._json(404, {"error": "Not found."})
        self._send(200, path.read_bytes(), content_type or TYPES.get(path.suffix, "application/octet-stream"))

    def resolve(self, path):
        """Map an allowed URL path to a file on disk, or None."""
        if path == "/":
            return APP / "index.html"
        if re.fullmatch(r"/[\w-]+\.(html|mjs|css)", path):
            return APP / path[1:]
        if path.startswith("/inspector/") and path.removeprefix("/inspector/") in INSPECTOR_MODULES:
            return ROOT / "inspector" / path.removeprefix("/inspector/")
        if path == "/corpus/queue.json":
            return self.corpus / "queue.json"
        match = PAGE_FILE.fullmatch(path)
        if match and match[3] in CAPTURE_FILES:
            return self.corpus / "public-research-v1/captures" / match[1] / match[2] / STATE / match[3]
        return None

    def do_GET(self):
        if not self._allowed():
            return self._json(403, {"error": "Same-origin loopback access is required."})
        path = urlsplit(self.path).path
        if path == "/api/labels":
            return self._json(200, self.label_status())
        target = self.resolve(path)
        if target is None:
            return self._json(404, {"error": "Not found."})
        # Capture HTML is page data, never a document to render here.
        self._file(target, "text/plain; charset=utf-8" if target.is_relative_to(self.corpus) and target.suffix == ".html" else None)

    def do_POST(self):
        if not self._allowed(mutation=True):
            return self._json(403, {"error": "Same-origin loopback access is required."})
        if urlsplit(self.path).path != "/api/corpus-check":
            return self._json(404, {"error": "Unknown endpoint."})
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            return self._json(415, {"error": "Use application/json."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_POST:
                raise ValueError("Body too large.")
            report = json.loads(self.rfile.read(length))
            pages = report["pages"]
            if not isinstance(pages, list) or not all(
                    isinstance(p, dict) and re.fullmatch(r"[0-9a-f]{24}/[0-9a-f]{24}", str(p.get("page"))) for p in pages):
                raise ValueError("pages must be a list of {page, error}.")
        except (ValueError, KeyError, TypeError) as error:
            return self._json(400, {"error": str(error)[:300]})
        (self.corpus / "excluded.json").write_text(json.dumps(report, indent=1))
        self._json(200, {"excluded": len(pages)})

    def label_status(self):
        status = {}
        for path in sorted(self.labels.glob("*.json")) if self.labels.is_dir() else []:
            try:
                label = json.loads(path.read_text())
                status[label["page"]] = label.get("provenance", {}).get("status", "draft")
            except (ValueError, KeyError, TypeError):
                continue
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    server = Server(("127.0.0.1", args.port), Handler)
    print(f"Labeler: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
