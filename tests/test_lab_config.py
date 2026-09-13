"""Cloud configuration must be explicit while offline imports stay usable."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness.lab_config import load_lab_config
from harness.model import LabClient, local_lab_envelope, local_lab_token, read_lab_token


class LabConfigTests(unittest.TestCase):
    def test_explicit_identity_pins_every_cli_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({
                "account": "researcher@lab.test", "project": "research-project", "configuration": "research-lab",
            }))
            lab = load_lab_config(path)
            self.assertEqual(lab.gcloud, ["gcloud", "--configuration=research-lab",
                                        "--account=researcher@lab.test", "--project=research-project"])

    def test_missing_file_has_no_credential_discovery_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            self.assertIsNone(load_lab_config(path, required=False))
            with self.assertRaisesRegex(RuntimeError, "requires a local"):
                load_lab_config(path)

    def test_rejects_ambiguous_config_and_service_accounts(self):
        valid = {"account": "researcher@lab.test", "project": "research-project", "configuration": "research-lab"}
        variants = [None, {}, {**valid, "credential_file": "private.json"},
                    {**valid, "account": "robot@research-project.iam.gserviceaccount.com"},
                    {**valid, "account": ""}, {**valid, "project": "../project"},
                    {**valid, "configuration": "--account=other"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for data in variants:
                with self.subTest(data=data):
                    path.write_text(json.dumps(data))
                    with self.assertRaises(RuntimeError):
                        load_lab_config(path)

    def test_example_requires_operator_replacement(self):
        with self.assertRaises(RuntimeError):
            load_lab_config(Path(__file__).resolve().parents[1] / ".lab-config.example.json")

    def test_cloud_entrypoints_fail_before_credentials_or_network_without_config(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("harness.model._LAB_CONFIG", None),
            patch("harness.model.subprocess.check_output") as cli,
            patch("harness.model.urllib.request.urlopen") as network,
        ):
            client = LabClient(directory)
            operations = [local_lab_token, local_lab_envelope,
                          lambda: read_lab_token("unused.json"),
                          lambda: client.generate("model", "system", "prompt", purpose="test")]
            for operation in operations:
                with self.assertRaisesRegex(RuntimeError, "requires a local"):
                    operation()
            cli.assert_not_called()
            network.assert_not_called()

    def test_offline_import_without_local_config(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, SEMANTIC_LAB_CONFIG=str(Path(directory) / "missing.json"))
            result = subprocess.run(
                [sys.executable, "-c", "from harness.model import ACCOUNT; import harness.ollama_model; assert ACCOUNT == ''"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
