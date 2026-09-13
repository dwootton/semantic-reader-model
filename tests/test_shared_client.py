import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from harness.model import LabClient, ModelError
from harness.shared_budget import SharedBudget
from harness.lab_config import LabConfig

ACCOUNT = "test-user@example.com"
PROJECT = "semantic-test-project"
TEST_LAB = LabConfig(ACCOUNT, PROJECT, "semantic-test")




def response():
    return io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"{\\"ok\\":true}"}]}}]}')


class SharedClientTests(unittest.TestCase):
    def setUp(self):
        lab = patch("harness.model._require_lab_config", return_value=TEST_LAB)
        lab.start()
        self.addCleanup(lab.stop)

    def test_clients_share_global_ids_and_cap_without_local_pacing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = SharedBudget(root / "budget.sqlite", max_calls=2, min_interval=0)
            clients = [LabClient(root / str(i), shared_budget=SharedBudget(budget.path)) for i in range(2)]
            ids = []
            with patch("harness.model.urllib.request.urlopen", side_effect=lambda *a, **k: response()) as network:
                for client in clients:
                    with patch.object(client, "_token", return_value="test-token"), patch.object(client, "_pace") as pace:
                        _, meta = client.generate("model", "system", "prompt", purpose="test")
                        ids.append(meta["call"])
                        pace.assert_not_called()
                with patch.object(clients[0], "_token", return_value="test-token"):
                    with self.assertRaisesRegex(ModelError, "budget"):
                        clients[0].generate("model", "system", "prompt", purpose="test")
            self.assertEqual(ids, [1, 2])
            self.assertEqual(network.call_count, 2)
            self.assertEqual(budget.usage()["reserved_calls"], 2)
            logs = [json.loads((c.output_dir / "model_calls.jsonl").read_text())["call"] for c in clients]
            self.assertEqual(logs, ids)


if __name__ == "__main__":
    unittest.main()
