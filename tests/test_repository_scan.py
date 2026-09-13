import unittest

from scripts.check_staged_files import scan_blob


class RepositoryScanTests(unittest.TestCase):
    def test_reports_secret_location_without_returning_its_value(self):
        secret = b"ghp_" + b"a" * 36
        issues = scan_blob("source.py", b"first line\n" + secret)
        self.assertEqual(issues, [("source.py", 2, "GitHub token")])
        self.assertNotIn(secret.decode(), repr(issues))

    def test_excluded_artifact_stays_blocked_even_without_token_pattern(self):
        for path in ("runs/a/result.json", "inspector/data/page.json", ".lab-config.json"):
            self.assertIn((path, 0, "local-only file"), scan_blob(path, b"{}"))

    def test_synthetic_demo_and_placeholder_config_are_allowed(self):
        for path in ("examples/demo/catalog.json", ".lab-config.example.json"):
            self.assertEqual(scan_blob(path, b'{"account": "researcher@example.com"}'), [])

    def test_private_key_marker_and_large_file_are_blocked(self):
        marker = b"-----BEGIN " + b"PRIVATE KEY-----"
        self.assertEqual(scan_blob("sample.txt", marker)[0][2], "private key")
        self.assertTrue(scan_blob("large.json", b" " * (5 * 1024 * 1024 + 1)))


if __name__ == "__main__":
    unittest.main()
