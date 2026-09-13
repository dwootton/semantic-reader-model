"""Disposable Shopping Admin sites with one container and origin per worker."""

from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


IMAGE_DIGEST = Path("/opt/semantic-reader/benchmark-image-digest.txt")
MAGENTO = "/var/www/magento2/bin/magento"


class _OwnOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if f"{parts.scheme}://{parts.netloc}" != self.origin:
            raise RuntimeError("Fresh site redirected outside its worker origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class SiteConfig:
    name: str
    port: int
    control_port: int

    def __post_init__(self):
        if self.port not in (7782, 7784, 7786, 7788) or self.control_port != self.port + 1:
            raise ValueError("Worker site requires a reserved app/control port pair")
        worker = (self.port - 7780) // 2
        if self.name != f"webarena-verified-shopping_admin-worker-{worker}":
            raise ValueError("Worker container name must match its reserved port")

    @property
    def origin(self):
        return f"http://localhost:{self.port}"

    @property
    def admin_url(self):
        return self.origin + "/admin"

    def reset(self, log_path):
        """Reset only this worker; fail closed on lifecycle or URL config errors."""
        started = time.monotonic()
        image = IMAGE_DIGEST.read_text().strip()
        if not re.fullmatch(r"am1n3e/webarena-verified-shopping_admin@sha256:[0-9a-f]{64}", image):
            raise RuntimeError("Benchmark image must be a pinned Shopping Admin digest")
        docker = ["sudo", "-n", "docker"]
        base_url = self.origin + "/"
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as stream:
            # Inspect via a successful listing, so absence differs from daemon or
            # permission failure. Never remove a container by a broad filter.
            listing = subprocess.run(
                docker + ["ps", "-a", "--filter", f"name=^/{self.name}$", "--format", "{{.Names}}"],
                capture_output=True, text=True, check=True, timeout=30,
            )
            names = listing.stdout.splitlines()
            if names and names != [self.name]:
                raise RuntimeError("Unexpected container listing; refusing reset")
            if names:
                subprocess.run(docker + ["rm", "-f", self.name], stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=30)
            # Upstream ShoppingAdminOps._init reads this variable. Supplying it
            # at creation prevents its background init from restoring port 7780.
            subprocess.run(
                docker + ["run", "-d", "--name", self.name,
                          "-p", f"127.0.0.1:{self.port}:80",
                          "-p", f"127.0.0.1:{self.control_port}:8877",
                          "-e", f"WA_ENV_CTRL_EXTERNAL_SITE_URL={base_url}", image],
                stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=30,
            )
            self._wait_control()
            # Adobe Commerce's documented config:set writes to the database;
            # the benchmark image's CLI lives under /var/www/magento2.
            paths = ("web/unsecure/base_url", "web/secure/base_url")
            for path in paths:
                subprocess.run(docker + ["exec", self.name, "php", MAGENTO,
                                        "config:set", path, base_url],
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
            subprocess.run(docker + ["exec", self.name, "php", MAGENTO, "cache:flush"],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
            for path in paths:
                shown = subprocess.run(docker + ["exec", self.name, "php", MAGENTO,
                                                 "config:show", path],
                                       capture_output=True, text=True, check=True, timeout=60)
                if shown.stdout.strip() != base_url:
                    raise RuntimeError(f"Worker site URL configuration mismatch: {path}")
            self._wait_admin()
        return {"method": "isolated_container_recreation", "image": image,
                "container": self.name, "origin": self.origin, "control_port": self.control_port,
                "base_url_verified": True, "elapsed_seconds": time.monotonic() - started,
                "ready_at": datetime.now(timezone.utc).isoformat()}

    def _wait_control(self):
        deadline = time.monotonic() + 180
        opener = urllib.request.build_opener(
            _OwnOriginRedirect(f"http://127.0.0.1:{self.control_port}"))
        while time.monotonic() < deadline:
            try:
                with opener.open(f"http://127.0.0.1:{self.control_port}/status", timeout=10) as response:
                    # Upstream /status checks service health, including MySQL.
                    # Do not log its detailed execution payload: it can contain credentials.
                    if response.status == 200 and json.load(response).get("success") is True:
                        return
            except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
                pass
            time.sleep(3)
        raise RuntimeError("Worker site services did not become ready within 180 seconds")

    def _wait_admin(self):
        deadline = time.monotonic() + 180
        opener = urllib.request.build_opener(_OwnOriginRedirect(self.origin))
        while time.monotonic() < deadline:
            try:
                with opener.open(self.admin_url, timeout=10) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError, http.client.HTTPException):
                pass
            time.sleep(3)
        raise RuntimeError("Worker admin page did not become ready within 180 seconds")
