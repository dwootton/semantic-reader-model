"""Loopback-only interactive comparison with local Ollama or the verified lab client."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.model import LabClient, ModelError  # noqa: E402
from inspector.serve import Handler as StaticHandler  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

DATA = ROOT / "inspector" / "data"
JOB_ID = re.compile(r"^[a-f0-9]{32}$")
INPUT_MODES = [
    {"id": "compact-selection", "label": "Compact · select proposed groups"},
    {"id": "compact-budget", "label": "Compact HTML · budget"},
    {"id": "legacy", "label": "Original normalized DOM"},
]


class ComparisonJobs:
    """Run one bounded comparison at a time; retain results across page reloads."""

    def __init__(self, output, model="gemini-3.8-flash", client_factory=None, runner=None,
                 *, backend="lab", num_ctx=131072, local_models=(), input_mode="legacy"):
        if backend not in {"lab", "ollama"}:
            raise ValueError("Backend must be lab or ollama.")
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.backend = backend
        self.num_ctx = num_ctx
        if input_mode not in {option["id"] for option in INPUT_MODES}:
            raise ValueError("Unknown comparison input mode.")
        self.input_mode = input_mode
        self.client_factory = client_factory
        self.models = [{"backend": backend, "model": model,
                        "label": ("Local · " if backend == "ollama" else "Cloud · ") + model}]
        for local_model in local_models:
            if not any(option["backend"] == "ollama" and option["model"] == local_model for option in self.models):
                self.models.append({"backend": "ollama", "model": local_model, "label": "Local · " + local_model})
        if backend == "ollama":
            self.models.append({"backend": "lab", "model": "gemini-3.8-flash", "label": "Cloud · Gemini Flash"})
        self.runner = runner
        self.lock = threading.RLock()
        self.jobs = {}
        self.active_job = None
        self.catalog = {item["id"]: item for item in json.loads((DATA / "catalog.json").read_text())["datasets"]}
        for path in sorted(self.output.glob("*/job.json"))[-50:]:
            try:
                job = json.loads(path.read_text())
                if not JOB_ID.fullmatch(job.get("id", "")):
                    continue
                if job.get("status") == "running":
                    job.update(status="failed", error="The server stopped before this run finished.",
                               progress="Interrupted. Start a new run to try again.")
                    self._persist(job)
                if job.get("status") == "failed" and job.get("errors") and not job.get("failed_calls"):
                    records = self._failed_calls(path.parent / "model_calls.jsonl", 0)
                    job["failed_calls"] = {
                        strategy: [event for event in records if (
                            event.get("purpose", "").endswith(":whole") if strategy == "whole"
                            else ":region " in event.get("purpose", "") or event.get("purpose", "").endswith(":compose")
                        )] for strategy in job["errors"]
                    }
                    self._persist(job)
                self.jobs[job["id"]] = job
            except (OSError, ValueError, TypeError):
                continue

    def _persist(self, job):
        directory = self.output / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "job.json.tmp"
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2))
        temporary.replace(directory / "job.json")

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError(job_id)
            return copy.deepcopy(self.jobs[job_id])

    def source(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError(job_id)
            path = self.output / job_id / "source.json"
            if not path.exists():
                raise KeyError(job_id)
            return path.read_bytes()

    def config(self):
        with self.lock:
            recent = sorted(self.jobs.values(), key=lambda job: job.get("created_at", 0), reverse=True)[:12]
            return {"backend": self.backend, "model": self.model, "models": copy.deepcopy(self.models),
                    "num_ctx": self.num_ctx if self.backend == "ollama" else None,
                    "input_mode": self.input_mode, "input_modes": copy.deepcopy(INPUT_MODES),
                    "region_sizes": [80, 160, 320],
                    "active_job": self.active_job,
                    "recent_jobs": [{key: job.get(key) for key in ("id", "capture_id", "status", "created_at", "backend", "model", "input_mode")}
                                    for job in recent]}

    def create(self, request):
        if not isinstance(request, dict):
            raise ValueError("A JSON object is required.")
        capture_id = request.get("capture_id")
        strategy = request.get("strategy")
        region_size = request.get("region_size", 160)
        backend = request.get("backend", self.backend)
        model = request.get("model", self.model)
        input_mode = request.get("input_mode", self.input_mode)
        if not isinstance(capture_id, str) or capture_id not in self.catalog:
            raise ValueError("Choose an available saved capture.")
        if strategy not in ("whole", "regions", "both"):
            raise ValueError("Choose whole, regions, or both.")
        if type(region_size) is not int or region_size not in (80, 160, 320):
            raise ValueError("Region size must be 80, 160, or 320.")
        if not isinstance(input_mode, str) or input_mode not in {option["id"] for option in INPUT_MODES}:
            raise ValueError("Choose a configured input mode.")
        if not isinstance(backend, str) or not isinstance(model, str) or not any(
            option["backend"] == backend and option["model"] == model for option in self.models
        ):
            raise ValueError("Choose one of the configured models. No automatic model download or backend fallback is allowed.")
        with self.lock:
            if self.active_job:
                raise RuntimeError(self.active_job)
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "status": "running", "capture_id": capture_id,
                   "strategy": strategy, "backend": backend, "model": model,
                   "num_ctx": self.num_ctx if backend == "ollama" else None,
                   "input_mode": input_mode,
                   "region_size": region_size, "created_at": time.time(), "progress": "Preparing saved capture…",
                   "error": None, "errors": {}, "results": {}, "failed_calls": {}}
            self.jobs[job_id] = job
            self.active_job = job_id
            self._persist(job)
            thread = threading.Thread(target=self._run, args=(job_id,), daemon=True)
            thread.start()
            return copy.deepcopy(job)

    def _run(self, job_id):
        job = self.jobs[job_id]

        def progress(message):
            with self.lock:
                job["progress"] = str(message)
                self._persist(job)

        try:
            from inspector.comparison import run_comparison

            preparation_started = time.monotonic()
            raw_capture = (DATA / f"{job['capture_id']}.json").read_bytes()
            dataset = json.loads(raw_capture)
            directory = self.output / job_id
            if job.get("input_mode", "legacy") in {"compact-budget", "compact-selection"}:
                from inspector.compact_input import load_compact
                from inspector.compact_comparison import run_compact_comparison

                prepared = load_compact(job["capture_id"], profile="budget")
                source_bytes = json.dumps(prepared["dataset"], ensure_ascii=False).encode("utf-8")
                if job["input_mode"] == "compact-selection":
                    from inspector.selection_comparison import run_selection_comparison
                    runner = self.runner or run_selection_comparison
                else:
                    runner = self.runner or run_compact_comparison
                runner_input = prepared
                provenance = prepared.get("provenance", {})
            else:
                source_bytes = raw_capture
                runner = self.runner or run_comparison
                runner_input = dataset
                provenance = {}
            (directory / "source.json").write_bytes(source_bytes)
            with self.lock:
                job["capture_hash"] = hashlib.sha256(source_bytes).hexdigest()
                job["catalog_capture_hash"] = hashlib.sha256(raw_capture).hexdigest()
                job["source_url"] = f"/api/comparison/jobs/{job_id}/source"
                job["input_provenance"] = provenance
                job["preparation_seconds"] = time.monotonic() - preparation_started
                self._persist(job)
            if self.client_factory is not None:
                client = self.client_factory(directory)
            elif job["backend"] == "ollama":
                from harness.ollama_model import OllamaClient
                client = OllamaClient(directory, num_ctx=self.num_ctx, max_calls=40)
            else:
                client = LabClient(directory, max_calls=40, min_interval=10, max_attempts=2)
            client.deadline = time.monotonic() + (1800 if job["backend"] == "ollama" else 600)
            strategies = ("whole", "regions") if job["strategy"] == "both" else (job["strategy"],)
            ledger = directory / "model_calls.jsonl"
            for strategy in strategies:
                offset = ledger.stat().st_size if ledger.exists() else 0
                try:
                    result = runner(runner_input, strategy, client, job["model"],
                                    region_size=job["region_size"], progress=progress)
                    with self.lock:
                        job["results"][strategy] = result
                        self._persist(job)
                except (ValueError, RuntimeError, OSError) as error:
                    with self.lock:
                        job["errors"][strategy] = self._safe_error(error)
                        job["failed_calls"][strategy] = self._failed_calls(ledger, offset)
                        self._persist(job)
            with self.lock:
                job["status"] = "failed" if job["errors"] else "complete"
                job["error"] = " · ".join(f"{key}: {value}" for key, value in job["errors"].items()) or None
                job["progress"] = "Run finished with errors; any completed results are preserved." if job["errors"] else "Comparison ready."
        except Exception as error:
            with self.lock:
                job.update(status="failed", error=self._safe_error(error), progress="Run stopped.")
        finally:
            with self.lock:
                job["completed_at"] = time.time()
                job["elapsed_seconds"] = job["completed_at"] - job["created_at"]
                self.active_job = None
                self._persist(job)

    @staticmethod
    def _failed_calls(ledger, offset):
        if not ledger.exists():
            return []
        with ledger.open("rb") as stream:
            stream.seek(offset)
            lines = stream.read().decode("utf-8").splitlines()
        records = []
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            records.append({key: event[key] for key in ("backend", "model", "purpose", "request", "response",
                                                       "metadata", "error", "elapsed_seconds") if key in event})
        return records

    @staticmethod
    def _safe_error(error):
        # Never serialize subprocess output, request URLs, or credential envelopes.
        if isinstance(error, (ValueError, ModelError)):
            return str(error)[:600]
        if type(error) is RuntimeError:
            return str(error)[:600]
        return f"{type(error).__name__}: check the local comparison server."


class ComparisonHandler(StaticHandler):
    def _allowed(self, mutation=False):
        expected_port = self.server.server_address[1]
        try:
            authority = urlsplit("http://" + self.headers.get("Host", ""))
            if authority.hostname not in {"localhost", "127.0.0.1"} or authority.port != expected_port:
                return False
            origin = self.headers.get("Origin")
            if origin:
                supplied = urlsplit(origin)
                if supplied.scheme != "http" or supplied.netloc != authority.netloc:
                    return False
            if mutation and self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
                return False
            return True
        except ValueError:
            return False

    def _json(self, status, body):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self._json_bytes(status, payload)

    def _json_bytes(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self._allowed():
            self._json(403, {"error": "Same-origin loopback access is required."})
            return
        path = urlsplit(self.path).path
        if path == "/api/comparison/config":
            self._json(200, self.server.jobs.config())
        elif path.startswith("/api/comparison/jobs/"):
            job_id = path.removeprefix("/api/comparison/jobs/")
            try:
                if job_id.endswith("/source"):
                    self._json_bytes(200, self.server.jobs.source(job_id.removesuffix("/source")))
                else:
                    self._json(200, self.server.jobs.get(job_id))
            except KeyError:
                self._json(404, {"error": "Run not found."})
        elif path.startswith("/api/"):
            self._json(404, {"error": "Unknown endpoint."})
        else:
            if path == "/":
                self.path = "/compare.html"
            super().do_GET()

    def do_POST(self):
        if not self._allowed(mutation=True):
            self._json(403, {"error": "Same-origin loopback access is required."})
            return
        if urlsplit(self.path).path != "/api/comparison/jobs":
            self._json(404, {"error": "Unknown endpoint."})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            self._json(415, {"error": "Use application/json."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Request body must contain at most 4096 bytes.")
            request = json.loads(self.rfile.read(length))
            job = self.server.jobs.create(request)
            self._json(202, job)
        except (ValueError, UnicodeDecodeError) as error:
            self._json(400, {"error": str(error)[:300]})
        except RuntimeError as error:
            self._json(409, {"error": "Another comparison is running.", "active_job": str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--backend", choices=("lab", "ollama"), default="lab")
    parser.add_argument("--model", default=None)
    parser.add_argument("--num-ctx", type=int, default=131072)
    parser.add_argument("--local-model", action="append", default=[], help="Additional installed local model to offer")
    parser.add_argument("--input-mode", choices=[option["id"] for option in INPUT_MODES], default="compact-budget")
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / "comparison")
    args = parser.parse_args()
    model = args.model or ("qwen3.5:0.8b" if args.backend == "ollama" else "gemini-3.8-flash")
    pattern = r"[A-Za-z0-9._:/-]+" if args.backend == "ollama" else r"[A-Za-z0-9._-]+"
    if not re.fullmatch(pattern, model):
        parser.error("Invalid model ID.")
    if not 4096 <= args.num_ctx <= 262144:
        parser.error("Context must be between 4096 and 262144 tokens.")
    jobs = ComparisonJobs(args.output, model, backend=args.backend, num_ctx=args.num_ctx,
                          local_models=args.local_model, input_mode=args.input_mode)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ComparisonHandler)
    server.jobs = jobs
    print(f"Hierarchy comparison: http://127.0.0.1:{args.port}/compare.html", flush=True)
    print(f"Default model: {args.backend}/{model}. Runs start on request.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
