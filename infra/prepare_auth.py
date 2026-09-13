"""Provision public benchmark test-account headers outside repository artifacts."""

import json
import os
from pathlib import Path

from browsergym.webarena.instance import WebArenaInstance


def main():
    os.environ.setdefault("WA_SHOPPING_ADMIN", "http://localhost:7780/admin")
    for name in ("SHOPPING", "REDDIT", "GITLAB", "WIKIPEDIA", "MAP", "HOMEPAGE"):
        os.environ.setdefault(f"WA_{name}", "todo")
    credentials = WebArenaInstance().credentials["shopping_admin"]
    directory = Path("/tmp/semantic-reader-auth")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "benchmark-headers.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump({"X-M2-Admin-Auto-Login": credentials["username"] + ":" + credentials["password"]}, stream)
    print("Benchmark authentication prepared outside the workspace.")


if __name__ == "__main__":
    main()
