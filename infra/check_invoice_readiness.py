"""Privileged adapter diagnostic; never counted as a navigator trial."""

from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.benchmark import Benchmark


def main():
    output = Path("runs/readiness-check")
    output.mkdir(parents=True, exist_ok=True)
    benchmark = Benchmark(94)
    summary = {"kind": "adapter_diagnostic_not_agent_trial", "actions": []}
    try:
        snapshot = benchmark.reset()
        for label in ("\ue60b SALES", "Invoices"):
            targets = [node for node in snapshot["nodes"]
                       if node["role"].lower() == "link" and node["name"].casefold() == label.casefold()]
            if len(targets) != 1:
                raise RuntimeError(f"Expected one live source link labeled {label}, found {len(targets)}")
            snapshot = benchmark.act({"kind": "click", "bid": targets[0]["bid"],
                                      "snapshot_id": snapshot["snapshot_id"]})
            summary["actions"].append({"label": label, "url": snapshot["url"],
                                       "capture": snapshot.get("capture_metadata"),
                                       "action_error": benchmark.last_action_error})
        summary["roles"] = dict(Counter(node["role"] for node in snapshot["nodes"]))
        summary["rows"] = [node["name"] for node in snapshot["nodes"] if node["role"] == "row"][:3]
        (output / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2), flush=True)
    except Exception as error:
        summary["error"] = {"type": type(error).__name__, "message": str(error)}
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        (output / "raw-error.json").write_text(json.dumps(benchmark.raw_capture(), indent=2))
        print(json.dumps(summary, indent=2), flush=True)
        raise
    finally:
        benchmark.close()


if __name__ == "__main__":
    main()
