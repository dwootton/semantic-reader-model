"""Print compact pilot status without credentials or full browser captures."""

import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/pilot-20260912-f")
    args = parser.parse_args()
    root = Path(args.run)
    service = subprocess.run(
        ["systemctl", "show", "semantic-reader-pilot", "--property=ActiveState,SubState,MainPID"],
        text=True, capture_output=True, check=False,
    ).stdout.strip().splitlines()
    result = {"service": service, "run_path": str(root.resolve())}
    credentials_log = root / "credential_events.jsonl"
    if credentials_log.exists():
        lines = credentials_log.read_text().splitlines()
        if lines:
            try:
                result["last_credential_event"] = json.loads(lines[-1])
            except json.JSONDecodeError:
                result["last_credential_event"] = {"phase": "log_append_in_progress"}
    call_log = root / "model_calls.jsonl"
    if call_log.exists():
        last_line = ""
        with call_log.open() as stream:
            for line in stream:
                last_line = line
        try:
            call = json.loads(last_line)
            result["last_model_call"] = {key: call.get(key) for key in (
                "call", "model", "purpose", "started_at", "elapsed_seconds",
                "error", "pacing_seconds", "retry_delay_seconds",
            )}
        except json.JSONDecodeError:
            result["last_model_call"] = {"status": "log_append_in_progress"}
    if (root / "run.json").exists():
        run = json.loads((root / "run.json").read_text())
        result["run"] = {key: run.get(key) for key in (
            "status", "phase", "started_at", "updated_at", "finished_at",
            "current_episode", "completed_episodes", "model_calls", "error",
        )}
        result["planned_episodes"] = len(run.get("episodes", []))
        if "concurrency_stages" in run:
            result["parallel"] = {key: run.get(key) for key in (
                "active_episodes", "request_stats", "shared_budget", "four_worker_test",
                "concurrency_stages",
            )}
            result["workers"] = []
            for path in sorted((root / "workers").glob("*/status.json")):
                worker = json.loads(path.read_text())
                episode_path = root / "episodes" / str(worker.get("episode", "")) / "episode.json"
                if episode_path.exists():
                    ep = json.loads(episode_path.read_text())
                    worker["recorded_steps"] = len(ep.get("steps", []))
                    worker["episode_status"] = ep.get("status")
                    worker["episode_updated_at"] = ep.get("updated_at")
                result["workers"].append(worker)
        current = root / "episodes" / str(run.get("current_episode", "")) / "episode.json"
        if current.exists():
            episode = json.loads(current.read_text())
            result["episode"] = {key: episode.get(key) for key in (
                "episode_id", "status", "started_at", "updated_at", "finished_at", "totals", "error",
            )}
            steps = episode.get("steps", [])
            result["episode"]["recorded_steps"] = len(steps)
            if steps:
                last = steps[-1]
                result["episode"]["last_step"] = {
                    "step": last["step"], "started_at": last.get("started_at"),
                    "decision_recorded_at": last.get("decision_recorded_at"),
                    "action": last.get("decision", {}).get("action"),
                    "result_recorded": "result" in last,
                }
        result["terminal_episodes"] = []
        for path in sorted((root / "episodes").glob("*/episode.json")):
            episode = json.loads(path.read_text())
            if episode.get("status") != "running":
                result["terminal_episodes"].append({
                    "episode_id": episode["episode_id"], "status": episode["status"],
                    "steps": len(episode.get("steps", [])),
                    "strict_success": (episode.get("evaluation") or {}).get("strict_success"),
                    "annotation_exists": path.with_name("annotation.json").exists(),
                })
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
