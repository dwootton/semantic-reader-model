"""Validate generation on the captured customer page; not a navigator trial."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.model import LabClient
from harness.projections import ProjectionFactory


def main():
    source = Path("runs/pilot-20260912-d/episodes/t157-coarse-gemini-3.1-pro-preview/captures/008-source.json")
    snapshot = json.loads(source.read_text())
    output = Path("runs/large-input-check")
    client = LabClient(output, max_calls=1)
    projection, metadata = ProjectionFactory(client, "gemini-3.8-flash", output / "cache").make(snapshot, "coarse")
    result = {"kind": "generation_capacity_check_not_agent_trial", "source_nodes": len(snapshot["nodes"]),
              "groups": len(projection["groups"]), "metadata": metadata, "calls": client.calls}
    (output / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
