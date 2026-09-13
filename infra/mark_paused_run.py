"""Finalize metadata after an intentional SIGINT, without changing finished trials."""

import argparse
import json
from pathlib import Path
import subprocess


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--reason", default="input_capacity_fix",
                        choices=["input_capacity_fix", "parallel_execution"])
    args = parser.parse_args()
    pid = subprocess.check_output(
        ["systemctl", "show", "semantic-reader-pilot", "--property=MainPID", "--value"], text=True,
    ).strip()
    if pid != "0":
        raise RuntimeError("The run is still active; refusing to change its metadata")
    root = Path(args.run)
    run = json.loads((root / "run.json").read_text())
    if run.get("phase") != "finished" or not run.get("finished_at"):
        raise RuntimeError("Run finalization has not completed")
    run["status"] = f"paused_for_{args.reason}"
    run["pause_note"] = ("Paused between episodes for " + args.reason.replace("_", " ")
                         + "; finished trials are unchanged.")
    for path in (root / "episodes").glob("*/episode.json"):
        episode = json.loads(path.read_text())
        if episode.get("status") == "running":
            episode["status"] = "error"
            episode["error"] = {"type": "OperatorPause", "message": run["pause_note"]}
            write(path, episode)
        elif episode.get("status") == "not_started":
            episode["reason"] = run["status"]
            write(path, episode)
    write(root / "run.json", run)
    print(json.dumps({"status": run["status"], "calls": run["model_calls"],
                      "remaining_calls": run["config"]["max_calls"] - run["model_calls"]}))


if __name__ == "__main__":
    main()
