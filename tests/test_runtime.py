"""Cache fairness, lab credential boundaries, and pre-network call budgets."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness.model import LabClient, ModelError, read_lab_token
from harness.projections import ProjectionFactory
from harness.lab_config import LabConfig

ACCOUNT = "test-user@example.com"
PROJECT = "semantic-test-project"
TEST_LAB = LabConfig(ACCOUNT, PROJECT, "semantic-test")




def snapshot(prefix="a", snapshot_id="first"):
    return {
        "snapshot_id": snapshot_id, "url": "http://site.local/admin/key/session-one/orders",
        "nodes": [
            dict(id=f"{prefix}-root", role="main", name="Orders", value="", children=[f"{prefix}-field"], bid=f"{prefix}-bid-root"),
            dict(id=f"{prefix}-field", role="textbox", name="Order identifier", value="", children=[], bid=f"{prefix}-bid-field"),
        ],
        "roots": [f"{prefix}-root"],
    }


class FakeClient:
    def __init__(self):
        self.calls = []

    def generate(self, model, system, prompt, *, purpose, max_tokens):
        self.calls.append(dict(model=model, system=system, prompt=json.loads(prompt), purpose=purpose))
        if purpose == "projection:descriptive":
            output = {"labels": {"orders": "Browse and edit orders", "field": "Enter an order identifier"}}
        else:
            output = {"groups": [
                dict(id="orders", label="Orders", parent=None, source_ids=["n0", "n1"]),
                dict(id="field", label="Entry", parent="orders", source_ids=["n1"]),
            ]}
        return output, {"call": len(self.calls)}


class ProjectionRuntimeTests(unittest.TestCase):
    def test_cache_reuses_content_across_snapshot_and_source_id_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            factory = ProjectionFactory(client, "fake-model", directory)
            first, first_meta = factory.make(snapshot(), "purpose")
            replacement = snapshot("b", "second")
            replacement["url"] = replacement["url"].replace("session-one", "session-two")
            second, second_meta = factory.make(replacement, "purpose")
            self.assertEqual(len(client.calls), 1)
            self.assertFalse(first_meta["cache_hit"])
            self.assertTrue(second_meta["cache_hit"])
            self.assertEqual(first_meta["cache_key"], second_meta["cache_key"])
            self.assertEqual(first["groups"][0]["source_ids"], ["a-root", "a-field"])
            self.assertEqual(second["groups"][0]["source_ids"], ["b-root", "b-field"])
            self.assertEqual(second["groups"][1]["source_ids"], ["b-field"])
            self.assertNotIn("snapshot_id", client.calls[0]["prompt"]["capture"])

    def test_descriptive_condition_changes_labels_only(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            factory = ProjectionFactory(client, "fake-model", directory)
            base, _ = factory.make(snapshot(), "purpose")
            descriptive, _ = factory.make(snapshot(), "descriptive")
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(client.calls[-1]["purpose"], "projection:descriptive")
            self.assertNotEqual([group["label"] for group in base["groups"]], [group["label"] for group in descriptive["groups"]])
            def without_labels(projection):
                return [{key: value for key, value in group.items() if key != "label"} for group in projection["groups"]]
            self.assertEqual(without_labels(base), without_labels(descriptive))
            self.assertEqual(client.calls[-1]["prompt"]["base_projection"]["groups"][0]["source_ids"], ["n0", "n1"])

    def test_changed_source_content_or_native_state_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            factory = ProjectionFactory(client, "fake-model", directory)
            _, original = factory.make(snapshot(), "purpose")
            changed_name = snapshot()
            changed_name["nodes"][1]["name"] = "Invoice identifier"
            _, name_meta = factory.make(changed_name, "purpose")
            changed_state = snapshot()
            changed_state["nodes"][1]["properties"] = [{"name": "invalid", "value": {"value": "true"}}]
            _, state_meta = factory.make(changed_state, "purpose")
            self.assertEqual(len(client.calls), 3)
            self.assertEqual(len({original["cache_key"], name_meta["cache_key"], state_meta["cache_key"]}), 3)
            self.assertFalse(name_meta["cache_hit"])
            self.assertFalse(state_meta["cache_hit"])


class ModelRuntimeTests(unittest.TestCase):
    def setUp(self):
        lab = mock.patch("harness.model._require_lab_config", return_value=TEST_LAB)
        lab.start()
        self.addCleanup(lab.stop)

    def write_token(self, directory, *, mode=0o600, **overrides):
        token = dict(account=ACCOUNT, project=PROJECT, issued_at=10_000, expires_at=13_600, access_token="test-only-token")
        token.update(overrides)
        path = Path(directory) / "lab-token.json"
        path.write_text(json.dumps(token))
        path.chmod(mode)
        return path

    def test_accepts_only_private_current_lab_envelope(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("harness.model.time.time", return_value=10_100):
            path = self.write_token(directory)
            self.assertEqual(read_lab_token(path), "test-only-token")

    def test_rejects_other_account_or_project(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("harness.model.time.time", return_value=10_100):
            for overrides in [dict(account="other@example.com"), dict(project="another-project")]:
                with self.subTest(overrides=overrides):
                    path = self.write_token(directory, **overrides)
                    with self.assertRaisesRegex(RuntimeError, "identity/project mismatch"):
                        read_lab_token(path)

    def test_rejects_expired_envelope_and_group_or_world_permissions(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("harness.model.time.time", return_value=14_000):
            with self.assertRaisesRegex(RuntimeError, "needs refresh"):
                read_lab_token(self.write_token(directory))
        with tempfile.TemporaryDirectory() as directory, mock.patch("harness.model.time.time", return_value=10_100):
            for mode in [0o640, 0o604, 0o644, 0o666]:
                with self.subTest(mode=oct(mode)), self.assertRaisesRegex(RuntimeError, "private regular file"):
                    read_lab_token(self.write_token(directory, mode=mode))

    def test_zero_model_call_budget_prevents_network_and_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            client = LabClient(directory, max_calls=0)
            with mock.patch.object(client, "_token") as token, mock.patch("harness.model.urllib.request.urlopen") as network:
                with self.assertRaisesRegex(ModelError, "budget exhausted"):
                    client.generate("fake-model", "system", "prompt", purpose="test")
                token.assert_not_called()
                network.assert_not_called()
            self.assertEqual(client.calls, 0)
            self.assertFalse((Path(directory) / "model_calls.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
