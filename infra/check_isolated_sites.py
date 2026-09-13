"""Verify two separate live site/browser namespaces; no model calls."""

from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.site import SiteConfig


def check(worker):
    port = 7780 + 2 * worker
    site = SiteConfig(f"webarena-verified-shopping_admin-worker-{worker}", port, port + 1)
    os.environ["WA_SHOPPING_ADMIN"] = site.admin_url
    output = Path("runs/site-isolation-check")
    output.mkdir(parents=True, exist_ok=True)
    reset = site.reset(output / f"worker-{worker}.log")
    from harness.benchmark import Benchmark
    benchmark = Benchmark(157)
    try:
        snapshot = benchmark.reset()
        if not snapshot["url"].startswith(site.origin + "/"):
            raise RuntimeError("Browser reached another worker's origin")
        result = {"worker": worker, "reset": reset, "url": snapshot["url"],
                  "source_nodes": len(snapshot["nodes"]), "snapshot_id": snapshot["snapshot_id"]}
        (output / f"worker-{worker}.json").write_text(json.dumps(result, indent=2))
        return result
    finally:
        benchmark.close()


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(check, (1, 2)))
    print(json.dumps(results, indent=2))
