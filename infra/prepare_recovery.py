"""Print the bounded resume command; the runner validates and copies artifacts.

From the project root, run with the same Python used for the harness:
    python infra/prepare_recovery.py --source runs/pilot-20260912-c \
        --output runs/pilot-20260912-d --max-calls 551

Execute the printed command inside the existing pilot systemd environment after
refreshing its private lab token. This helper makes no cloud calls and writes no
run artifacts. --resume-from in harness.run owns all validation and provenance;
never invoke the runner against an existing run.json or delete the source run.
"""

import argparse
import json
from pathlib import Path
import shlex
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="runs/pilot-20260912-c")
    parser.add_argument("--output", default="runs/pilot-20260912-d")
    parser.add_argument("--max-calls", type=int, default=551)
    args = parser.parse_args()
    if (Path(args.output) / "run.json").exists():
        parser.error("Output run already exists; refusing to replace it")
    run = json.loads((Path(args.source) / "run.json").read_text())
    config = run["config"]
    remaining = config["max_calls"] - run["model_calls"]
    if not 0 < args.max_calls <= remaining:
        parser.error(f"Source budget permits at most {remaining} new model calls")
    command = [sys.executable, "-m", "harness.run", "--output", args.output,
               "--resume-from", args.source, "--max-calls", str(args.max_calls)]
    for key in ("tasks", "conditions", "models", "generator", "judge", "max_steps",
                "max_browser_actions", "max_minutes", "page_size", "request_interval",
                "max_attempts", "seed"):
        command.extend(["--" + key.replace("_", "-"), str(config[key])])
    print(shlex.join(command))


if __name__ == "__main__":
    main()
