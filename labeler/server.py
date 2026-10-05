"""Serve the labeling tool on loopback. Read-only access to the local corpus; no cloud calls.

Routes:
  GET  /                                   the labeler page; other labeler/*.html|*.mjs|*.css by name
  GET  /inspector/model.mjs                shared tree helpers reused from the inspector
  GET  /corpus/queue.json                  page order (labeler/queue_order.py)
  GET  /corpus/pages/<site>/<page>/<file>  one of the six desktop capture files
  GET  /api/labels                         {page: status} for label files in runs/labels/
  GET  /api/labels/<site>/<page>           one saved label
  POST /api/labels                         save a draft, or submit (validated against the page's source map)
  POST /api/export                         write an inspector dataset to runs/labels/datasets/
  POST /api/corpus-check                   writes runs/corpus/excluded.json from the in-browser check
"""
import argparse
from datetime import datetime, timezone
import getpass
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
sys.path.insert(0, str(ROOT))
from inspector.build_data import validate  # noqa: E402

INSPECTOR_MODULES = {"model.mjs"}
TYPES = {".html": "text/html; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}
PAGE_FILE = re.compile(r"/corpus/pages/([0-9a-f]{24})/([0-9a-f]{24})/(.+)")
PAGE_ID = re.compile(r"[0-9a-f]{24}/[0-9a-f]{24}")
MAX_POST = 32 << 20  # an exported dataset carries the page's whole raw DOM


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
        if path.startswith("/api/labels/"):
            try:
                label = self.label_path(path.removeprefix("/api/labels/"))
                return self._file(label) if label.exists() else self._json(200, None)  # no label yet
            except ValueError as error:
                return self._json(400, {"error": str(error)})
        target = self.resolve(path)
        if target is None:
            return self._json(404, {"error": "Not found."})
        # Capture HTML is page data, never a document to render here.
        self._file(target, "text/plain; charset=utf-8" if target.is_relative_to(self.corpus) and target.suffix == ".html" else None)

    def do_POST(self):
        if not self._allowed(mutation=True):
            return self._json(403, {"error": "Same-origin loopback access is required."})
        routes = {"/api/corpus-check": self.save_check, "/api/labels": self.save_label, "/api/export": self.save_export}
        handler = routes.get(urlsplit(self.path).path)
        if handler is None:
            return self._json(404, {"error": "Unknown endpoint."})
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            return self._json(415, {"error": "Use application/json."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_POST:
                raise ValueError("Body too large.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object.")
            status, payload = handler(body)
        except (ValueError, KeyError, TypeError, AssertionError) as error:
            return self._json(400, {"error": str(error)[:500]})
        self._json(status, payload)

    def save_check(self, report):
        pages = report["pages"]
        if not isinstance(pages, list) or not all(isinstance(p, dict) and PAGE_ID.fullmatch(str(p.get("page"))) for p in pages):
            raise ValueError("pages must be a list of {page, error}.")
        (self.corpus / "excluded.json").write_text(json.dumps(report, indent=1))
        return 200, {"excluded": len(pages)}

    def label_path(self, page):
        if not PAGE_ID.fullmatch(str(page)):
            raise ValueError("Unknown page id.")
        return self.labels / (page.replace("/", "__") + ".json")

    def page_dom(self, page):
        """A minimal raw DOM rebuilt from the page's source map, enough for validate() to check references."""
        site, page_id = page.split("/")
        source_map = json.loads((self.corpus / "public-research-v1/captures" / site / page_id / STATE /
                                 "compression/document-00000.source-map.json").read_text())
        nodes = {e["id"]: {"id": f"src-{e['id']}", "parent": None if e["parent"] is None else f"src-{e['parent']}",
                           "children": []} for e in source_map}
        for e in source_map:
            if e["parent"] is not None:
                nodes[e["parent"]]["children"].append(f"src-{e['id']}")
        listed = list(nodes.values())
        return {"roots": [n["id"] for n in listed if n["parent"] is None], "nodes": listed}

    def save_label(self, label):
        path = self.label_path(label["page"])
        provenance = label.setdefault("provenance", {})
        if provenance.get("status") not in {"draft", "submitted"}:
            raise ValueError("status must be draft or submitted.")
        if not isinstance(label.get("nodes"), list) or not isinstance(label.get("rootId"), str):
            raise ValueError("A label needs rootId and nodes.")
        if provenance["status"] == "submitted":
            validate({"dom": self.page_dom(label["page"]), "variants": {"label": label}})
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        previous = json.loads(path.read_text()).get("provenance", {}) if path.exists() else {}
        provenance.update(labeler=getpass.getuser(), started_at=previous.get("started_at", now), saved_at=now)
        if provenance["status"] == "submitted":
            provenance["submitted_at"] = now
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(label, ensure_ascii=False, indent=1))
        temporary.replace(path)
        return 200, {"status": provenance["status"], "saved_at": now}

    def save_export(self, dataset):
        if not re.fullmatch(r"label-[0-9a-f]{24}", str(dataset.get("id"))):
            raise ValueError("Unexpected dataset id.")
        validate(dataset)
        path = self.labels / "datasets" / f"{dataset['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")))
        return 200, {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)}

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
    parser.add_argument("--labels", type=Path, default=Handler.labels, help="where labels are read and written (tests use a scratch folder)")
    args = parser.parse_args()
    Handler.labels = args.labels.resolve()
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
