"""Container ownership and origin configuration for concurrent benchmark sites."""

import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.request

from harness.site import SiteConfig, _OwnOriginRedirect


IMAGE = "am1n3e/webarena-verified-shopping_admin@sha256:" + "a" * 64


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.site = SiteConfig("webarena-verified-shopping_admin-worker-1", 7782, 7783)

    def reset(self, *, exists=True, failure=None, shown=None):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            self.assertNotIn("shell", kwargs)
            if failure and failure in command:
                raise subprocess.CalledProcessError(1, command)
            output = ""
            if "ps" in command:
                output = self.site.name + "\n" if exists else ""
            if "config:show" in command:
                output = shown if shown is not None else self.site.origin + "/\n"
            return subprocess.CompletedProcess(command, 0, stdout=output)

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("harness.site.IMAGE_DIGEST") as digest, \
                mock.patch("harness.site.subprocess.run", side_effect=run), \
                mock.patch.object(SiteConfig, "_wait_control") as control, \
                mock.patch.object(SiteConfig, "_wait_admin") as admin:
            digest.read_text.return_value = IMAGE
            result = self.site.reset(Path(directory) / "reset.log")
            control.assert_called_once()
            admin.assert_called_once()
        return result, commands

    def test_recreates_only_own_container_and_configures_both_urls(self):
        result, commands = self.reset()
        self.assertTrue(result["base_url_verified"])
        self.assertEqual(result["container"], self.site.name)
        for command in commands:
            self.assertEqual(command[:3], ["sudo", "-n", "docker"])
            if command[3] in ("rm", "exec"):
                self.assertIn(self.site.name, command)
        launch = next(command for command in commands if command[3] == "run")
        self.assertIn("127.0.0.1:7782:80", launch)
        self.assertIn("127.0.0.1:7783:8877", launch)
        self.assertIn("WA_ENV_CTRL_EXTERNAL_SITE_URL=http://localhost:7782/", launch)
        self.assertEqual(launch[-1], IMAGE)
        configs = [command[-2:] for command in commands if "config:set" in command]
        self.assertEqual(configs, [["web/unsecure/base_url", "http://localhost:7782/"],
                                   ["web/secure/base_url", "http://localhost:7782/"]])
        self.assertEqual(sum("config:show" in command for command in commands), 2)

    def test_first_launch_does_not_remove_missing_container(self):
        _, commands = self.reset(exists=False)
        self.assertFalse(any(command[3] == "rm" for command in commands))

    def test_lifecycle_and_configuration_failures_propagate(self):
        for stage in ("ps", "rm", "run", "config:set", "cache:flush", "config:show"):
            with self.subTest(stage=stage), self.assertRaises(subprocess.CalledProcessError):
                self.reset(failure=stage)

    def test_wrong_base_url_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "configuration mismatch"):
            self.reset(shown="http://localhost:7780/\n")

    def test_reserved_names_and_ports_prevent_cross_worker_reset(self):
        for number, port in enumerate((7782, 7784, 7786, 7788), 1):
            site = SiteConfig(f"webarena-verified-shopping_admin-worker-{number}", port, port + 1)
            self.assertEqual(site.admin_url, f"http://localhost:{port}/admin")
        for name, port, control in ((self.site.name, 7784, 7785),
                                    (self.site.name, 7782, 7785),
                                    ("webarena-verified-shopping_admin", 7780, 7781)):
            with self.subTest(name=name, port=port), self.assertRaises(ValueError):
                SiteConfig(name, port, control)

    def test_unpinned_image_does_not_touch_docker(self):
        with mock.patch("harness.site.IMAGE_DIGEST") as digest, \
                mock.patch("harness.site.subprocess.run") as run:
            digest.read_text.return_value = "am1n3e/webarena-verified-shopping_admin:latest"
            with self.assertRaises(RuntimeError):
                self.site.reset("unused.log")
            run.assert_not_called()

    def test_database_health_is_required_before_configuration(self):
        responses = []
        for success in (False, True):
            response = io.BytesIO(b'{"success":true}' if success else b'{"success":false}')
            response.status = 200
            responses.append(response)
        with mock.patch("harness.site.urllib.request.build_opener") as factory, \
                mock.patch("harness.site.time.sleep") as sleep:
            factory.return_value.open.side_effect = responses
            self.site._wait_control()
            self.assertEqual(factory.return_value.open.call_count, 2)
            sleep.assert_called_once_with(3)

    def test_admin_redirect_cannot_reach_other_worker_or_external_origin(self):
        handler = _OwnOriginRedirect(self.site.origin)
        request = urllib.request.Request(self.site.admin_url)
        for url in ("http://localhost:7780/admin", "http://localhost:7784/admin",
                    "https://example.com/admin"):
            with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, "outside"):
                handler.redirect_request(request, None, 302, "Found", {}, url)
        redirect = handler.redirect_request(request, None, 302, "Found", {},
                                             self.site.origin + "/admin/login")
        self.assertEqual(redirect.full_url, self.site.origin + "/admin/login")


if __name__ == "__main__":
    unittest.main()
