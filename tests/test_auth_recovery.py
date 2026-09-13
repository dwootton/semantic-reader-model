import io
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

from harness.model import CLOUD_SCOPE, LabClient, ModelError, local_lab_envelope, local_lab_token, read_lab_token
from harness.lab_config import LabConfig

ACCOUNT = "test-user@example.com"
PROJECT = "semantic-test-project"
TEST_LAB = LabConfig(ACCOUNT, PROJECT, "semantic-test")




class AuthRecoveryTests(unittest.TestCase):
    def setUp(self):
        lab = patch("harness.model._require_lab_config", return_value=TEST_LAB)
        lab.start()
        self.addCleanup(lab.stop)

    def test_envelope_uses_verified_server_lifetime_and_identity(self):
        response = io.BytesIO(json.dumps({
            "email": ACCOUNT, "verified_email": True, "scope": CLOUD_SCOPE,
            "expires_in": 3578,
        }).encode())
        with (
            patch("harness.model.local_lab_token", return_value="test-token"),
            patch("harness.model.time.time", return_value=10_000),
            patch("harness.model.urllib.request.urlopen", return_value=response),
        ):
            envelope = local_lab_envelope()
        self.assertEqual(envelope["expires_at"], 13_578)
        self.assertEqual(envelope["account"], ACCOUNT)

    def test_tokeninfo_error_does_not_expose_credential_url(self):
        error = urllib.error.HTTPError(
            "https://www.googleapis.com/oauth2/v2/tokeninfo?access_token=private-test-value",
            400, "bad token", {}, io.BytesIO(b""),
        )
        with (
            patch("harness.model.local_lab_token", return_value="private-test-value"),
            patch("harness.model.urllib.request.urlopen", side_effect=error),
        ):
            with self.assertRaises(RuntimeError) as raised:
                local_lab_envelope()
        self.assertNotIn("private-test-value", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)

    def test_tokeninfo_rejects_a_different_user(self):
        response = io.BytesIO(json.dumps({
            "email": "another@example.com", "verified_email": True,
            "scope": CLOUD_SCOPE, "expires_in": 3600,
        }).encode())
        with (
            patch("harness.model.local_lab_token", return_value="test-token"),
            patch("harness.model.urllib.request.urlopen", return_value=response),
        ):
            with self.assertRaisesRegex(RuntimeError, "approved lab user"):
                local_lab_envelope()

    def test_cli_token_request_forces_refresh_with_explicit_scope(self):
        config = {"properties": {"core": {"account": ACCOUNT, "project": PROJECT}}}
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("harness.model.subprocess.check_output", side_effect=[json.dumps(config), "fresh-test-token\n"]) as cli,
        ):
            self.assertEqual(local_lab_token(), "fresh-test-token")
        self.assertIn("--scopes=https://www.googleapis.com/auth/cloud-platform", cli.call_args.args[0])

    def test_recent_envelope_does_not_hide_actual_token_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.json"
            path.write_text(json.dumps({
                "account": ACCOUNT, "project": PROJECT, "issued_at": time.time(),
                "expires_at": time.time() - 1, "access_token": "expired-test-token",
            }))
            path.chmod(0o600)
            with self.assertRaisesRegex(RuntimeError, "refresh"):
                read_lab_token(path)

    def test_401_retries_same_request_after_private_token_rotation(self):
        expired = urllib.error.HTTPError(
            "https://aiplatform.googleapis.com", 401, "expired", {},
            io.BytesIO(b'{"error":{"message":"Invalid authentication"}}'),
        )
        response = io.BytesIO(json.dumps({
            "candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}],
        }).encode())
        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, token_file="/unused-test-path", max_calls=3, min_interval=0)
            with (
                patch.object(client, "_token", side_effect=["old-test-token", "new-test-token", "new-test-token"]),
                patch("harness.model.time.sleep"),
                patch("harness.model.urllib.request.urlopen", side_effect=[expired, response]) as request,
            ):
                result, _ = client.generate("gemini-3.8-flash", "system", "input", purpose="test")
            self.assertTrue(result["ok"])
            self.assertEqual(request.call_count, 2)
            first, second = [call.args[0] for call in request.call_args_list]
            self.assertEqual(first.data, second.data)
            self.assertNotEqual(first.headers["Authorization"], second.headers["Authorization"])

    def test_unchanged_rejected_token_waits_without_sending_more_requests(self):
        clock = SimpleNamespace(value=0)
        expired = urllib.error.HTTPError(
            "https://aiplatform.googleapis.com", 401, "expired", {},
            io.BytesIO(b'{"error":{"message":"Invalid authentication"}}'),
        )

        def sleep(seconds):
            clock.value += seconds

        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, token_file="/unused-test-path", max_calls=3, min_interval=0)
            client.auth_wait_seconds = 10
            with (
                patch.object(client, "_token", return_value="unchanged-test-token"),
                patch("harness.model.time.monotonic", side_effect=lambda: clock.value),
                patch("harness.model.time.sleep", side_effect=sleep),
                patch("harness.model.urllib.request.urlopen", side_effect=expired) as request,
            ):
                with self.assertRaisesRegex(ModelError, "waiting budget"):
                    client.generate("gemini-3.8-flash", "system", "input", purpose="test")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(clock.value, 10)


if __name__ == "__main__":
    unittest.main()
