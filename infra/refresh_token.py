"""Send a short-lived lab-user token over restricted SSH without printing it."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.model import GCLOUD, local_lab_envelope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vm", default="semantic-reader-pilot")
    parser.add_argument("--zone", default="us-central1-a")
    parser.add_argument("--iap", action="store_true")
    args = parser.parse_args()
    envelope = local_lab_envelope()
    # This fixed path is outside the repository and is writable only by the SSH user.
    command = (
        "umask 077; mkdir -p /tmp/semantic-reader-auth; "
        "chmod 700 /tmp/semantic-reader-auth; "
        "cat > /tmp/semantic-reader-auth/token.new; "
        "mv /tmp/semantic-reader-auth/token.new /tmp/semantic-reader-auth/token.json"
    )
    subprocess.run(
        GCLOUD + ["compute", "ssh", args.vm, f"--zone={args.zone}",
                  *(["--tunnel-through-iap"] if args.iap else []),
                  "--quiet", f"--command={command}"],
        input=json.dumps(envelope), text=True, check=True,
    )
    print("Refreshed verified lab-user token on the pilot VM; expiry:", envelope["expires_at"])


if __name__ == "__main__":
    main()
