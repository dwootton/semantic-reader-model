"""Vertex bootstrap using only the project's managed /gcs mount for artifacts.

The control-plane helper embeds this stdlib-only source in the CustomJob. All
training dependencies and commands run in a fresh local virtual environment.
No Google SDK, ADC, service-account key, or credential client is used here.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time


PROJECT = "eastwest72hack26bos-508"
PROJECT_NUMBER = "440367173014"
BUCKET = PROJECT + "-semantic-reader-staging"
PREFIX_ROOT = f"gs://{BUCKET}/training/qwen3-8b-20260913/"
MANAGED_IDENTITY = f"service-{PROJECT_NUMBER}@gcp-sa-aiplatform-cc.iam.gserviceaccount.com"
MODEL = "Qwen/Qwen3-8B"
FORBIDDEN_CREDENTIAL_ENV = (
    "GOOGLE_APPLICATION_CREDENTIALS", "CLOUDSDK_AUTH_ACCESS_TOKEN",
    "CLOUDSDK_AUTH_ACCESS_TOKEN_FILE", "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
    "CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT",
)


def mounted_prefix(uri):
    if not isinstance(uri, str) or not uri.startswith(PREFIX_ROOT):
        raise ValueError("Artifact prefix must be inside the approved training prefix")
    run_id = uri[len(PREFIX_ROOT):]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", run_id):
        raise ValueError("Artifact prefix must end with one safe run ID")
    return Path("/gcs") / uri[len("gs://"):]


def sha256(path):
    with Path(path).open("rb") as stream:
        result = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
        return result.hexdigest()


def extract_bundle(bundle, destination, expected_sha256):
    """Verify all archive members before writing, then extract regular files only."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or sha256(bundle) != expected_sha256:
        raise ValueError("Training bundle SHA256 mismatch")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("Bundle destination must be new")
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        seen, size = set(), 0
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                    or not path.parts or not (member.isdir() or member.isfile())
                    or path.as_posix() in seen):
                raise ValueError("Unsafe or duplicate training archive member")
            seen.add(path.as_posix())
            size += member.size
        if len(members) > 10000 or size > 2_000_000_000:
            raise ValueError("Training bundle exceeds bootstrap bounds")
        destination.mkdir(mode=0o700)
        for member in members:
            path = destination / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValueError("Archive regular file has no content stream")
                with extracted as source, path.open("xb") as target:
                    shutil.copyfileobj(source, target)
                path.chmod(0o600)


def copy_results(source, destination):
    """Copy closed local files; never rely on FUSE rename or copy credentials."""
    source, destination = Path(source), Path(destination)
    count = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Result artifacts must not be symlinks")
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            count += 1
    return count


def emit(event, **counters):
    print(json.dumps({"event": event, **counters}, sort_keys=True), flush=True)


def run_process(argv, *, cwd, logfile, seconds, environment):
    """Bound the whole subprocess group; child logs stay in the private results."""
    with Path(logfile).open("ab") as log:
        child = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        try:
            returncode = child.wait(timeout=seconds)
        except (subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit):
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, argv)


def stage_command(python, source, output, purpose, args):
    return [str(python), "-u", "-m", "training.train",
            "--train", str(source / "data" / f"{purpose}-train.jsonl"),
            "--dev", str(source / "data" / f"{purpose}-dev.jsonl"),
            "--output", str(output / purpose), "--purpose", purpose,
            "--model", MODEL, "--revision", args.revision,
            "--max-length", str(args.max_length), "--max-steps", str(args.steps),
            "--max-seconds", str(args.stage_seconds), "--gradient-accumulation", "4",
            "--eval-limit", "16", "--train-eval-limit", "8",
            "--generation-limit", "2", "--max-new-tokens", "8192",
            "--generation-seconds", "900", "--seed", "42"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-prefix", required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--steps", type=int, default=32)
    parser.add_argument("--stage-seconds", type=int, default=14400)
    parser.add_argument("--max-length", type=int, default=32768)
    args = parser.parse_args(argv)
    mounted_prefix(args.artifact_prefix)
    if not re.fullmatch(r"[a-f0-9]{64}", args.bundle_sha256):
        parser.error("bundle SHA256 must contain exactly 64 lowercase hexadecimal characters")
    if not re.fullmatch(r"[a-f0-9]{40}", args.revision):
        parser.error("model revision must be an immutable lowercase 40-character commit SHA")
    if not 1 <= args.steps <= 256 or not 60 <= args.stage_seconds <= 14400:
        parser.error("steps must be 1-256 and stage-seconds must be 60-14400")
    if not 1024 <= args.max_length <= 32768:
        parser.error("max-length must be 1024-32768")
    return args


def main(argv=None):
    args = parse_args(argv)
    if any(os.environ.get(key) for key in FORBIDDEN_CREDENTIAL_ENV):
        raise RuntimeError("Explicit Google credential overrides are forbidden in training")
    observed_project = os.environ.get("CLOUD_ML_PROJECT_ID")
    if observed_project and observed_project not in {PROJECT, PROJECT_NUMBER}:
        raise RuntimeError("Vertex runtime project mismatch")
    mount = mounted_prefix(args.artifact_prefix)
    remote = mount / "results"
    if remote.exists() and any(remote.iterdir()):
        raise FileExistsError("Results already exist; use a fresh run prefix")
    local = Path(tempfile.mkdtemp(prefix="semantic-training-"))
    output = local / "results"
    output.mkdir(mode=0o700)
    manifest = {"status": "running", "project": PROJECT,
                "vertex_project_environment": observed_project,
                "managed_identity": MANAGED_IDENTITY,
                "identity_basis": "Verified parent CustomJob project; default managed identity; no custom service account",
                "artifact_prefix": args.artifact_prefix, "bundle_sha256": args.bundle_sha256,
                "base_model": MODEL, "model_revision": args.revision, "stages": []}
    started = time.monotonic()
    environment = dict(os.environ, HF_HOME=str(local / "hf-cache"),
                       PIP_DISABLE_PIP_VERSION_CHECK="1", TOKENIZERS_PARALLELISM="false")

    def terminated(signum, frame):
        raise SystemExit("Vertex termination signal")

    previous_term = signal.signal(signal.SIGTERM, terminated)

    def publish():
        manifest["elapsed_seconds"] = round(time.monotonic() - started, 2)
        (output / "vertex-summary.json").write_text(json.dumps(manifest, indent=2) + "\n")
        count = copy_results(output, remote)
        emit("artifacts_copied", files=count, stages=len(manifest["stages"]))

    try:
        emit("bootstrap_started", stages=3)
        bundle = local / "bundle.tar.gz"
        shutil.copyfile(mount / "bundle.tar.gz", bundle)
        source = local / "source"
        extract_bundle(bundle, source, args.bundle_sha256)
        for required in [source / "training" / "train.py", source / "training" / "requirements.txt",
                         source / "training" / "quantize_runtime.sh",
                         *[source / "data" / f"{purpose}-{split}.jsonl"
                           for purpose in ("student", "judge") for split in ("train", "dev")]]:
            if not required.is_file():
                raise ValueError("Training bundle is missing a required source or data file")
        setup_log = output / "setup.log"
        run_process([sys.executable, "-m", "venv", "--system-site-packages", str(local / "venv")], cwd=source,
                    logfile=setup_log, seconds=300, environment=environment)
        python = local / "venv" / "bin" / "python"
        try:
            run_process([str(python), "-c", "import torch; assert torch.__version__.split('+')[0] == '2.9.1'; "
                         "assert torch.version.cuda == '12.8'"], cwd=source,
                        logfile=setup_log, seconds=120, environment=environment)
        except subprocess.CalledProcessError:
            run_process([str(python), "-m", "pip", "install", "--force-reinstall", "torch==2.9.1",
                         "--index-url", "https://download.pytorch.org/whl/cu128"], cwd=source,
                        logfile=setup_log, seconds=2400, environment=environment)
        run_process([str(python), "-m", "pip", "install", "-r", "training/requirements.txt"],
                    cwd=source, logfile=setup_log, seconds=1200, environment=environment)
        publish()
        for purpose in ("student", "judge"):
            emit("stage_started", stage=purpose, steps=args.steps)
            run_process(stage_command(python, source, output, purpose, args), cwd=source,
                        logfile=output / f"{purpose}.log", seconds=args.stage_seconds + 120,
                        environment=environment)
            stage_summary = json.loads((output / purpose / "summary.json").read_text())
            if stage_summary.get("status") != "complete" or not stage_summary.get("adapter_saved"):
                raise RuntimeError("Training stage did not produce a complete trained adapter")
            manifest["stages"].append({"purpose": purpose, "status": "complete",
                                       "optimizer_steps": stage_summary["optimizer_steps"]})
            publish()
            emit("stage_complete", stage=purpose, steps=stage_summary["optimizer_steps"])
        emit("stage_started", stage="q4_k_m")
        run_process(["/bin/bash", "training/quantize_runtime.sh", str(python),
                     str(output / "student"), str(output / "q4_k_m")], cwd=source,
                    logfile=output / "q4_k_m.log", seconds=3600, environment=environment)
        exported = json.loads((output / "q4_k_m" / "summary.json").read_text())
        if exported.get("status") != "complete" or exported.get("quantized_artifact_verified") is not True:
            raise RuntimeError("Export did not verify a complete Q4_K_M artifact")
        manifest["stages"].append({"purpose": "q4_k_m", "status": "complete",
                                   "quantized_bytes": exported["quantized_bytes"],
                                   "quantized_sha256": exported["quantized_sha256"]})
        emit("stage_complete", stage="q4_k_m", quantized_bytes=exported["quantized_bytes"])
        manifest["status"] = "complete"
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        manifest.update(status="failed", error_type=type(error).__name__)
        emit("run_failed", completed_stages=len(manifest["stages"]), error_type=type(error).__name__)
    finally:
        try:
            publish()
        finally:
            signal.signal(signal.SIGTERM, previous_term)
    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
