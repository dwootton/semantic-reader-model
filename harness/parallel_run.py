"""Bounded two-worker pilot followed by an evidence-gated four-worker test."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
import multiprocessing
import os
from pathlib import Path
import random
import shutil
import time
import traceback

from harness.benchmark import list_tasks
from harness.model import ACCOUNT, PROJECT, LabClient
from harness.projections import CONDITIONS, ProjectionFactory
from harness.run import complete_annotation, now, prepare_resume, run_episode, save
from harness.shared_budget import SharedBudget
from harness.site import SiteConfig


_WORKER = None


def claim_worker(ids):
    """Each spawned process keeps one origin for its entire lifetime."""
    worker_id = ids.get(timeout=10)
    if worker_id not in (1, 2, 3, 4):
        raise ValueError("Invalid worker ID")
    site = SiteConfig(f"webarena-verified-shopping_admin-worker-{worker_id}",
                      7780 + 2 * worker_id, 7781 + 2 * worker_id)
    os.environ["WA_SHOPPING_ADMIN"] = site.admin_url
    for name in ("SHOPPING", "REDDIT", "GITLAB", "WIKIPEDIA", "MAP", "HOMEPAGE"):
        os.environ[f"WA_{name}"] = "todo"
    return worker_id, site


def initialize_worker(ids, root, config, budget_path):
    global _WORKER
    worker_id, site = claim_worker(ids)
    root = Path(root)
    directory = root / "workers" / f"worker-{worker_id}"
    directory.mkdir(parents=True, exist_ok=True)
    args = argparse.Namespace(**config)
    args.site_config = site
    budget = SharedBudget(budget_path)
    client = LabClient(directory, max_calls=args.max_calls,
                       min_interval=args.request_interval, max_attempts=args.max_attempts,
                       shared_budget=budget)
    client.deadline = args.deadline
    cache = directory / "projection_cache"
    if (root / "projection_cache").exists():
        shutil.copytree(root / "projection_cache", cache, dirs_exist_ok=True)
    _WORKER = (worker_id, site, root, directory, args, budget, client,
               ProjectionFactory(client, args.generator, cache))
    save(directory / "status.json", {"worker": worker_id, "pid": os.getpid(),
                                      "origin": site.origin, "phase": "idle", "at": now()})


def execute_episode(spec):
    worker_id, site, root, directory, args, budget, client, factory = _WORKER
    episode_path = root / "episodes" / spec["episode_id"] / "episode.json"
    existing = json.loads(episode_path.read_text()) if episode_path.exists() else {}
    annotation_only = existing.get("annotation_pending") is True
    if annotation_only and any(existing.get(key) != value for key, value in spec.items()):
        raise ValueError("Annotation backlog episode specification mismatch")
    status = {"worker": worker_id, "pid": os.getpid(), "origin": site.origin,
              "episode": spec["episode_id"],
              "phase": "annotation" if annotation_only else "navigation", "at": now()}
    started = time.monotonic()
    save(directory / "status.json", status)
    annotation = {"status": "not_started", "reason": "no steps or insufficient remaining budget"}
    try:
        if annotation_only:
            episode = existing
        else:
            episode = run_episode(spec, root, client, factory, args)
            episode["execution"] = {"worker": worker_id, "pid": os.getpid(), "origin": site.origin}
        save(episode_path, episode)
        if (episode["steps"] and time.monotonic() < args.deadline
                and budget.usage()["reserved_calls"] < args.max_calls - 2):
            from harness.annotate import annotate_episode
            episode["annotation_worker"] = {"worker": worker_id, "pid": os.getpid(), "at": now()}
            status.update(phase="annotation", at=now())
            save(directory / "status.json", status)
            try:
                annotation = annotate_episode(episode, client, args.judge)
            except Exception as error:
                annotation = {"status": "error", "error": str(error)[:1000]}
        save(root / "episodes" / spec["episode_id"] / "annotation.json", annotation)
        infrastructure_error = episode["status"] in ("error", "evaluation_error")
        annotation_valid = complete_annotation(episode, annotation, args.judge)
        if annotation_valid:
            episode.pop("annotation_pending", None)
        save(episode_path, episode)
        result = {"episode_id": spec["episode_id"], "worker": worker_id,
                  "status": episode["status"], "infrastructure_error": infrastructure_error,
                  "annotation_valid": annotation_valid, "annotation_only": annotation_only,
                  "elapsed_seconds": time.monotonic() - started}
        status.update(phase="idle", result=result, at=now())
        return result
    finally:
        if status["phase"] != "idle":
            status.update(phase="error", at=now())
        save(directory / "status.json", status)


def aggregate_logs(root):
    """Snapshot completed log lines without reading any token files."""
    events = []
    for path in sorted((Path(root) / "workers").glob("*/model_calls.jsonl")):
        for line in path.read_bytes().split(b"\n")[:-1]:
            if not line:
                raise ValueError(f"Empty complete model log record: {path}")
            # Decode only newline-terminated records; the tail can split UTF-8.
            event = json.loads(line.decode("utf-8"))
            event["worker"] = path.parent.name
            events.append(event)
    events.sort(key=lambda event: event["call"])
    destination = Path(root) / "model_calls.jsonl"
    temporary = destination.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))
    temporary.replace(destination)
    usage = {}
    for event in events:
        for key, value in event.get("response", {}).get("usageMetadata", {}).items():
            if isinstance(value, (int, float)):
                usage[key] = usage.get(key, 0) + value
    return {"attempts": len(events),
            "http_429": sum(event.get("error", {}).get("status") == 429 for event in events),
            "usage": usage}


def stage_health(results, stats):
    """Conservative smoke gate, not a scientific quality judgment."""
    if sum(not item.get("annotation_only", False) for item in results) < 2:
        return False, "Fewer than two new navigation episodes finished"
    if any(item.get("infrastructure_error", True) for item in results):
        return False, "Infrastructure error in the measured stage"
    if any(not item.get("annotation_valid", False) for item in results):
        return False, "Missing or invalid annotations in the measured stage"
    if not stats["attempts"]:
        return False, "No model requests recorded in the measured stage"
    if stats["http_429"] / stats["attempts"] > 0.25:
        return False, "HTTP 429 fraction exceeds 25 percent"
    return True, "No infrastructure errors; complete annotations; HTTP 429 fraction at most 25 percent"


def pending_specs(specs, preserved, annotation_backlog=()):
    ids = [spec["episode_id"] for spec in specs]
    if (len(set(ids)) != len(ids) or not set(preserved).issubset(ids)
            or not set(annotation_backlog).issubset(ids) or set(annotation_backlog) & set(preserved)):
        raise ValueError("Duplicate episode IDs or unknown preserved episode")
    pending = [spec for spec in specs if spec["episode_id"] not in preserved]
    return sorted(pending, key=lambda spec: spec["episode_id"] in annotation_backlog)


def coordinate(pool, root, args, run, budget, *, job=execute_episode):
    """Submit a first batch of two, gate four, and never duplicate a spec."""
    pending = iter(pending_specs(run["episodes"], run["preserved_episodes"], run.get("annotation_backlog", [])))
    futures, completed, stage_results = {}, [], []
    stage = {"workers": 2, "started_at": now(), "started_monotonic": time.monotonic(),
             "start_attempts": 0, "start_http_429": 0, "episodes": []}
    run["concurrency_stages"] = [stage]
    run["four_worker_test"] = {"status": "pending"}
    target, first_batch, exhausted, stop_submissions = 2, True, False, False
    run["status"] = "running"

    def finish_stage(stats, reason):
        stage.update(finished_at=now(), elapsed_seconds=time.monotonic() - stage["started_monotonic"],
                     attempts=stats["attempts"] - stage["start_attempts"],
                     http_429=stats["http_429"] - stage["start_http_429"], reason=reason)
        stage["episodes_per_minute"] = len(stage["episodes"]) * 60 / max(stage["elapsed_seconds"], 0.001)

    while True:
        used = budget.usage()
        if time.monotonic() >= args.deadline or used["reserved_calls"] >= args.max_calls - 4:
            stop_submissions = True
            run["status"] = "budget_exhausted"
        # During the initial gate, await both jobs before admitting a third.
        while not exhausted and not stop_submissions and len(futures) < target:
            if first_batch and len(futures) + len(stage_results) >= 2:
                break
            spec = next(pending, None)
            if spec is None:
                exhausted = True
                break
            futures[pool.submit(job, spec)] = spec
        run.update(active_episodes=[spec["episode_id"] for spec in futures.values()],
                   phase="parallel_navigation_and_annotation", model_calls=used["reserved_calls"],
                   shared_budget=used, updated_at=now())
        stats = aggregate_logs(root)
        run.update(usage=stats["usage"], request_stats={k: stats[k] for k in ("attempts", "http_429")})
        save(root / "run.json", run)
        if not futures:
            if first_batch:
                run["four_worker_test"] = {"status": "not_attempted", "reason": "Fewer than two new episodes or remaining budget insufficient"}
            finish_stage(stats, run["status"] if stop_submissions else "All scheduled work finished")
            if run["status"] == "running":
                run["status"] = "completed"
            break
        done, _ = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
        for future in done:
            spec = futures.pop(future)
            try:
                result = future.result()
            except Exception as error:
                result = {"episode_id": spec["episode_id"], "status": "worker_error",
                          "infrastructure_error": True, "annotation_valid": False,
                          "error": f"{type(error).__name__}: {str(error)[:1000]}"}
                path = root / "episodes" / spec["episode_id"] / "worker-error.json"
                save(path, result)
            completed.append(result)
            stage_results.append(result)
            stage["episodes"].append(result)
            run["completed_episodes"] = len(run["preserved_episodes"]) + len(completed)
            if sum(item["infrastructure_error"] for item in completed) >= 3:
                stop_submissions = True
                run["status"] = "stopped_after_repeated_errors"
        stats = aggregate_logs(root)
        stage_stats = {key: stats[key] - stage[f"start_{key}"] for key in ("attempts", "http_429")}
        if first_batch and len(stage_results) == 2 and not futures:
            healthy, reason = stage_health(stage_results, stage_stats)
            first_batch = False
            if healthy and not stop_submissions:
                finish_stage(stats, reason)
                target = args.test_workers
                stage_results = []
                stage = {"workers": target, "started_at": now(), "started_monotonic": time.monotonic(),
                         "start_attempts": stats["attempts"], "start_http_429": stats["http_429"], "episodes": []}
                run["concurrency_stages"].append(stage)
                run["four_worker_test"] = {"status": "running", "gate_reason": reason}
            else:
                run["four_worker_test"] = {"status": "not_attempted",
                                           "reason": run["status"] if stop_submissions else reason}
        elif target == 4 and sum(not item.get("annotation_only", False) for item in stage_results) >= 4:
            healthy, reason = stage_health(stage_results, stage_stats)
            run["four_worker_test"] = {"status": "passed" if healthy else "reduced_to_two", "reason": reason,
                                       "measured_episodes": len(stage_results), **stage_stats}
            if not healthy:
                finish_stage(stats, reason)
                target = 2  # Already running jobs finish; subsequent admissions respect two.
                stage_results = []
                stage = {"workers": 2, "started_at": now(), "started_monotonic": time.monotonic(),
                         "start_attempts": stats["attempts"], "start_http_429": stats["http_429"], "episodes": [],
                         "draining_existing_jobs": len(futures)}
                run["concurrency_stages"].append(stage)
    if run["four_worker_test"]["status"] == "running":
        run["four_worker_test"].update(status="incomplete", reason="Fewer than four new episodes completed in four-worker stage")
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume-from")
    parser.add_argument("--workers", type=int, choices=[2], default=2)
    parser.add_argument("--test-workers", type=int, choices=[4], default=4)
    parser.add_argument("--tasks", default="157,94")
    parser.add_argument("--conditions", default=",".join(CONDITIONS))
    parser.add_argument("--models", default="gemini-3.8-flash,gemini-3.1-pro-preview")
    parser.add_argument("--generator", default="gemini-3.8-flash")
    parser.add_argument("--judge", default="gemini-3.1-pro-preview")
    for name, default in (("max-steps", 28), ("max-browser-actions", 8), ("max-calls", 650),
                          ("max-minutes", 150), ("page-size", 12), ("max-attempts", 6), ("seed", 42)):
        parser.add_argument("--" + name, type=int, default=default)
    parser.add_argument("--request-interval", type=float, default=10.0)
    args = parser.parse_args()
    if not 1 <= args.max_steps <= 28 or args.max_calls < 1 or args.max_minutes < 1:
        parser.error("Invalid bounded smoke budget")
    root = Path(args.output).resolve()
    if (root / "run.json").exists() or (root / "shared-budget.sqlite").exists():
        parser.error("Use a fresh output directory")
    root.mkdir(parents=True, exist_ok=True)
    tasks = list_tasks([int(value) for value in args.tasks.split(",")])
    specs = []
    for task in tasks:
        for condition in args.conditions.split(","):
            if condition not in CONDITIONS:
                parser.error("Unknown condition")
            for model in args.models.split(","):
                specs.append({"episode_id": f"t{task['task_id']}-{condition}-{model}",
                              "task": task, "condition": condition, "model": model})
    random.Random(args.seed).shuffle(specs)
    pending_specs(specs, [])
    recovery = prepare_resume(args.resume_from, root, args, specs,
                              include_annotation_backlog=True) if args.resume_from else None
    run = {"run_id": root.name, "status": "running", "started_at": now(), "account": ACCOUNT,
           "project": PROJECT, "config": vars(args).copy(), "episodes": specs,
           "preserved_episodes": recovery["preserved_episodes"] if recovery else [],
           "annotation_backlog": recovery.get("annotation_backlog", []) if recovery else [],
           "execution_protocol": "Spawned isolated processes, two then gated four; shared request pacing and budget",
           "limitations": ["Same smoke matrix; one repetition; no causal or human accessibility claims.",
                           "Each worker uses a distinct origin; this is a recorded transport change.",
                           "Origin-dependent capture keys can prevent projection cache sharing.",
                           "Prior completed annotations are preserved; navigation summaries and scientific settings unchanged."]}
    run["completed_episodes"] = len(run["preserved_episodes"])
    budget_path = root / "shared-budget.sqlite"
    budget = SharedBudget(budget_path, max_calls=args.max_calls, min_interval=args.request_interval)
    args.deadline = time.monotonic() + 60 * args.max_minutes
    context = multiprocessing.get_context("spawn")
    ids = context.Queue()
    for worker_id in range(1, 5):
        ids.put(worker_id)
    try:
        with ProcessPoolExecutor(max_workers=4, mp_context=context, initializer=initialize_worker,
                                 initargs=(ids, str(root), vars(args).copy(), str(budget_path))) as pool:
            coordinate(pool, root, args, run, budget)
    except Exception as error:
        run.update(status="failed", error=f"{type(error).__name__}: {str(error)[:1500]}")
        (root / "error.txt").write_text(traceback.format_exc())
    finally:
        for spec in specs:
            path = root / "episodes" / spec["episode_id"] / "episode.json"
            worker_error = path.with_name("worker-error.json")
            if worker_error.exists() and path.exists():
                episode = json.loads(path.read_text())
                episode.update(status="worker_error", worker_error=json.loads(worker_error.read_text()))
                save(path, episode)
            if not path.exists():
                save(path, {**spec, "status": "worker_error" if worker_error.exists() else "not_started",
                            "reason": run["status"], "steps": [], "evaluation": None, "totals": {}})
        stats = aggregate_logs(root)
        run.update(finished_at=now(), phase="finished", active_episodes=[],
                   model_calls=budget.usage()["reserved_calls"], usage=stats["usage"],
                   shared_budget=budget.usage(), request_stats={k: stats[k] for k in ("attempts", "http_429")})
        save(root / "run.json", run)
        from harness.annotate import create_report
        create_report(root)
        ids.close()
        print(json.dumps({"event": "run_finished", "status": run["status"], "at": now()}), flush=True)


if __name__ == "__main__":
    main()
