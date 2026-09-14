"""Offline tests; no cloud resources, dependency downloads, or GPU execution."""

import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from infra import vertex_training as infra
from training import vertex_entry as entry


PREFIX = entry.PREFIX_ROOT + "test-run"
IMAGE = "us-docker.pkg.dev/vertex-ai/training/pytorch-gpu.2-4.py310@sha256:" + "a" * 64
REVISION = "b" * 40


class VertexTrainingTests(unittest.TestCase):
    def config(self):
        return infra.create_config(image=IMAGE, artifact_prefix=PREFIX,
                                   bundle_sha256="c" * 64, revision=REVISION)

    def test_config_pins_machine_artifacts_code_and_bounds(self):
        config = self.config()
        pool = config["workerPoolSpecs"][0]
        self.assertEqual(pool["machineSpec"]["machineType"], "a2-highgpu-1g")
        self.assertEqual(pool["machineSpec"]["acceleratorCount"], 1)
        self.assertEqual(pool["replicaCount"], 1)
        self.assertEqual(pool["containerSpec"]["imageUri"], IMAGE)
        self.assertIn("def extract_bundle", pool["containerSpec"]["command"][3])
        self.assertNotIn("serviceAccount", config)
        self.assertEqual(config["scheduling"], {"strategy": "SPOT", "timeout": "43200s",
                                               "restartJobOnWorkerRestart": False, "disableRetries": True})
        self.assertNotIn("maxWaitDuration", config["scheduling"])
        self.assertEqual(infra.submit_command("config.json")[:4], infra.LAB.gcloud)
        dockerhub = infra.create_config(image=infra.DEFAULT_IMAGE, artifact_prefix=PREFIX,
                                        bundle_sha256="c" * 64, revision=REVISION)
        self.assertEqual(dockerhub["workerPoolSpecs"][0]["containerSpec"]["imageUri"], infra.DEFAULT_IMAGE)

    def test_prefix_and_image_fail_closed(self):
        for prefix in ("gs://another-bucket/training/run", entry.PREFIX_ROOT,
                       entry.PREFIX_ROOT + "../other", entry.PREFIX_ROOT + "run/nested"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                entry.mounted_prefix(prefix)
        with self.assertRaises(ValueError):
            infra.create_config(image=IMAGE.split("@")[0] + ":latest", artifact_prefix=PREFIX,
                                bundle_sha256="c" * 64, revision=REVISION)

    def test_verified_job_rejects_other_project_identity_machine_and_schedule(self):
        config = self.config()
        job = {"name": f"projects/{entry.PROJECT_NUMBER}/locations/us-central1/customJobs/123",
               "state": "JOB_STATE_QUEUED", "jobSpec": deepcopy(config)}
        job["jobSpec"]["workerPoolSpecs"][0]["replicaCount"] = "1"
        self.assertEqual(infra.verify_job(job, config)["managed_identity"], entry.MANAGED_IDENTITY)
        for mutation in ("project", "identity", "machine", "schedule"):
            changed = deepcopy(job)
            if mutation == "project":
                changed["name"] = "projects/other/locations/us-central1/customJobs/123"
            elif mutation == "identity":
                changed["jobSpec"]["serviceAccount"] = "other@example.com"
            elif mutation == "machine":
                changed["jobSpec"]["workerPoolSpecs"][0]["machineSpec"]["acceleratorCount"] = 8
            else:
                changed["jobSpec"]["scheduling"]["disableRetries"] = False
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                infra.verify_job(changed, config)

    def archive(self, root, name="training/train.py", kind=None):
        bundle = root / "bundle.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            member = tarfile.TarInfo(name)
            if kind:
                member.type, member.linkname = kind, "/etc/passwd"
                archive.addfile(member)
            else:
                value = b"print('test')\n"
                member.size = len(value)
                archive.addfile(member, io.BytesIO(value))
        return bundle

    def test_bundle_verification_and_safe_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.archive(root)
            entry.extract_bundle(bundle, root / "valid", entry.sha256(bundle))
            self.assertTrue((root / "valid/training/train.py").is_file())
            with self.assertRaises(ValueError):
                entry.extract_bundle(bundle, root / "mismatch", "0" * 64)
            for name, kind in (("../outside", None), ("/outside", None),
                               ("training/link", tarfile.SYMTYPE), ("training/link", tarfile.LNKTYPE)):
                bundle = self.archive(root, name, kind)
                with self.subTest(name=name, kind=kind), self.assertRaises(ValueError):
                    entry.extract_bundle(bundle, root / "unsafe", entry.sha256(bundle))
                self.assertFalse((root / "unsafe").exists())

    def test_copy_artifacts_preserves_nested_files_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "local/student/adapter").mkdir(parents=True)
            (root / "local/student/adapter/weights").write_bytes(b"weights")
            self.assertEqual(entry.copy_results(root / "local", root / "remote"), 1)
            self.assertEqual((root / "remote/student/adapter/weights").read_bytes(), b"weights")
            (root / "local/link").symlink_to(root / "local/student/adapter/weights")
            with self.assertRaises(ValueError):
                entry.copy_results(root / "local", root / "remote")

    def test_stage_commands_never_use_test_or_gcp_clients(self):
        args = entry.parse_args(["--artifact-prefix", PREFIX, "--bundle-sha256", "c" * 64,
                                 "--revision", REVISION])
        for purpose in ("student", "judge"):
            command = entry.stage_command(Path("venv/bin/python"), Path("source"), Path("out"), purpose, args)
            self.assertIn(f"source/data/{purpose}-train.jsonl", command)
            self.assertIn(f"source/data/{purpose}-dev.jsonl", command)
            self.assertNotIn("test", " ".join(command))
            self.assertIn("Qwen/Qwen3-8B", command)
            self.assertIn("32", command)

    def test_prepare_is_offline_and_does_not_overwrite_different_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "custom-job.json"
            args = ["--image", IMAGE, "--artifact-prefix", PREFIX, "--bundle-sha256", "c" * 64,
                    "--revision", REVISION, "--config", str(config)]
            with patch.object(infra, "verify_lab", side_effect=AssertionError("No cloud call")), \
                    patch.object(infra, "read_json", side_effect=AssertionError("No cloud call")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(infra.main(args), 0)
            self.assertEqual(json.loads(config.read_text()), self.config())
            config.write_text("{}")
            with self.assertRaises(FileExistsError):
                infra.main(args)

    def test_runtime_saves_stages_and_failure_artifacts_without_cloud_calls(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                mount = root / "mount"
                mount.mkdir()
                bundle = mount / "bundle.tar.gz"
                required = ["training/train.py", "training/requirements.txt", "training/quantize_runtime.sh",
                            *[f"data/{purpose}-{split}.jsonl" for purpose in ("student", "judge")
                              for split in ("train", "dev")]]
                with tarfile.open(bundle, "w:gz") as archive:
                    for name in required:
                        member = tarfile.TarInfo(name)
                        member.size = 1
                        archive.addfile(member, io.BytesIO(b"\n"))
                local = root / "local"
                local.mkdir()

                def process(argv, **options):
                    Path(options["logfile"]).write_text("private child output")
                    if "training.train" in argv:
                        output = Path(argv[argv.index("--output") + 1])
                        output.mkdir(parents=True)
                        (output / "adapter").mkdir()
                        (output / "adapter/weights").write_bytes(b"partial-or-complete-weights")
                        if fail:
                            raise subprocess.CalledProcessError(1, argv)
                        (output / "summary.json").write_text(json.dumps({"status": "complete",
                            "adapter_saved": True, "optimizer_steps": 32}))
                    elif argv[0] == "/bin/bash":
                        output = Path(argv[-1])
                        output.mkdir(parents=True)
                        (output / "summary.json").write_text(json.dumps({"status": "complete",
                            "quantized_artifact_verified": True, "quantized_bytes": 100,
                            "quantized_sha256": "a" * 64}))

                args = ["--artifact-prefix", PREFIX, "--bundle-sha256", entry.sha256(bundle),
                        "--revision", REVISION]
                log = io.StringIO()
                with patch.object(entry, "mounted_prefix", return_value=mount), \
                        patch.object(entry.tempfile, "mkdtemp", return_value=str(local)), \
                        patch.object(entry, "run_process", side_effect=process), \
                        patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(log):
                    self.assertEqual(entry.main(args), int(fail))
                summary = json.loads((mount / "results/vertex-summary.json").read_text())
                self.assertEqual(summary["status"], "failed" if fail else "complete")
                self.assertEqual(len(summary["stages"]), 0 if fail else 3)
                self.assertTrue((mount / "results/student/adapter/weights").exists())
                self.assertNotIn("private child output", log.getvalue())
                for line in log.getvalue().splitlines():
                    self.assertIn("event", json.loads(line))

    def test_submission_receipt_prevents_repeat_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "custom-job.json"
            args = ["--image", IMAGE, "--artifact-prefix", PREFIX, "--bundle-sha256", "c" * 64,
                    "--revision", REVISION, "--config", str(config), "--submit"]
            job = {"name": f"projects/{entry.PROJECT_NUMBER}/locations/us-central1/customJobs/123",
                   "jobSpec": self.config(), "state": "JOB_STATE_QUEUED"}
            with patch.object(infra, "verify_lab") as verify, \
                    patch.object(infra, "read_json", return_value=job) as read, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(infra.main(args), 0)
                verify.assert_called_once()
                read.assert_called_once()
                with self.assertRaises(FileExistsError):
                    infra.main(args)
            receipt = json.loads(config.with_suffix(".submission.json").read_text())
            self.assertEqual(receipt["mode"], "submitted")
            self.assertEqual(receipt["job_name"], job["name"])
            self.assertIn("queue_cancel_after", receipt)


if __name__ == "__main__":
    unittest.main()
