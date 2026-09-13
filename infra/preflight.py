"""Capture and generate one live state without running a navigator episode."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.benchmark import Benchmark, list_tasks
from harness.model import LabClient
from harness.projections import ProjectionFactory
from harness.reader import Reader


def main():
    output = Path("runs/preflight")
    output.mkdir(parents=True, exist_ok=True)
    benchmark = Benchmark(157)
    try:
        snapshot = benchmark.reset()
        (output / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
        (output / "raw-capture.json").write_text(json.dumps(benchmark.raw_capture(), indent=2))
        client = LabClient(output, max_calls=3)
        factory = ProjectionFactory(client, "gemini-3.8-flash", output / "cache")
        projection, metadata = factory.make(snapshot, "purpose")
        (output / "projection.json").write_text(json.dumps({"projection": projection, "metadata": metadata}, indent=2))
        view = Reader(snapshot, projection).view()
        (output / "view.json").write_text(json.dumps(view, indent=2))
        summary = {
            "tasks": list_tasks([157, 94]), "url": snapshot["url"],
            "source_nodes": len(snapshot["nodes"]),
            "actionable_bids": sum(node["bid"] is not None for node in snapshot["nodes"]),
            "groups": len(projection["groups"]), "root_labels": [item["label"] for item in view["items"]],
            "generation": metadata,
        }
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2), flush=True)
    except Exception:
        try:
            (output / "raw-capture-error.json").write_text(json.dumps(benchmark.raw_capture(), indent=2))
        except RuntimeError:
            pass
        raise
    finally:
        benchmark.close()


if __name__ == "__main__":
    main()
