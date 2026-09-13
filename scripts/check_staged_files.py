"""Check staged Git bytes without printing suspected credential values."""

import argparse
from pathlib import PurePosixPath
import re
import subprocess


LOCAL_PREFIXES = (
    "runs/", ".omx/", "inspector/data/", "inspector/qa/",
    "experiments/dom-downsampling/output/",
)
LOCAL_FILES = {"AGENTS.md", "infra/README.md", ".lab-config.json"}
PUBLIC_EXAMPLE_FILES = {
    "examples/banana-bread/allrecipes.json", "examples/banana-bread/allrecipes.jpg",
    "examples/banana-bread/catalog.json", "examples/banana-bread/README.md",
}
PATTERNS = {
    "private key": rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    "Google API key": rb"AIza[0-9A-Za-z_-]{30,}",
    "Google OAuth access token": rb"ya29\.[0-9A-Za-z._~-]{20,}",
    "GitHub token": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})",
    "provider API key": rb"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{28,}",
    "AWS access key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "JWT": rb"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}",
    "credential-bearing URL": rb"[?&](?:access_token|refresh_token|api_key|X-Amz-Signature|X-Goog-Signature)=[A-Za-z0-9%._~-]{20,}",
    "literal authorization header": rb"[Bb]earer [A-Za-z0-9._~-]{24,}",
}


def scan_blob(path, data):
    """Return locations/types only; matched values never leave this function."""
    issues = []
    name = PurePosixPath(path).name.lower()
    forbidden = (
        path in LOCAL_FILES or path.startswith(LOCAL_PREFIXES)
        or (path.startswith("examples/") and not path.startswith("examples/demo/")
            and path not in PUBLIC_EXAMPLE_FILES)
        or (name.startswith(".env") and name != ".env.example")
        or name in {"token.json", "benchmark-headers.json", "application_default_credentials.json"}
        or name.startswith("credentials")
        or name.endswith((".pem", ".key", ".p12", ".pfx", ".pyc"))
        or any(part in {"__pycache__", "node_modules", ".venv", ".mypy_cache", ".ruff_cache"}
               for part in PurePosixPath(path).parts)
    )
    if forbidden:
        issues.append((path, 0, "local-only file"))
    if len(data) > 5 * 1024 * 1024:
        issues.append((path, 0, "file exceeds 5 MiB; review before publication"))
    for label, pattern in PATTERNS.items():
        for match in re.finditer(pattern, data):
            issues.append((path, data.count(b"\n", 0, match.start()) + 1, label))
    return issues


def git(*args):
    return subprocess.check_output(["git", *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Scan every index entry, not only staged changes")
    args = parser.parse_args()
    raw = (git("ls-files", "-z") if args.all else
           git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"))
    paths = [path.decode() for path in raw.split(b"\0") if path]
    issues = []
    for path in paths:
        entry = git("ls-files", "--stage", "--", path).decode().split()[0]
        if entry not in {"100644", "100755"}:
            issues.append((path, 0, "symlink or submodule requires manual review"))
            continue
        issues.extend(scan_blob(path, git("show", f":{path}")))
    for path, line, label in issues:
        print(f"{path}:{line}: {label}")
    print(f"Scanned {len(paths)} staged files; {len(issues)} findings. Matched values are never printed.")
    raise SystemExit(bool(issues))


if __name__ == "__main__":
    main()
