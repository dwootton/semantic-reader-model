"""Explicit cloud identity configuration; never discover credentials or defaults."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


@dataclass(frozen=True)
class LabConfig:
    account: str
    project: str
    configuration: str

    @property
    def gcloud(self):
        return [
            "gcloud", f"--configuration={self.configuration}",
            f"--account={self.account}", f"--project={self.project}",
        ]


def load_lab_config(path=None, *, required=True):
    """Load operator-approved identity from a local file, never from ADC."""
    path = Path(path or os.environ.get("SEMANTIC_LAB_CONFIG") or
                Path(__file__).resolve().parents[1] / ".lab-config.json")
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        if not required:
            return None
        raise RuntimeError("Cloud access requires a local .lab-config.json; see .lab-config.example.json") from None
    except (OSError, ValueError):
        raise RuntimeError("Could not read valid lab configuration JSON") from None
    if not isinstance(data, dict) or set(data) != {"account", "project", "configuration"}:
        raise RuntimeError("Lab configuration must contain only account, project, and configuration")
    if not all(isinstance(value, str) for value in data.values()):
        raise RuntimeError("Lab configuration values must be strings")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", data["account"]):
        raise RuntimeError("Lab configuration requires an explicit user email")
    if data["account"].endswith(".gserviceaccount.com"):
        raise RuntimeError("Service accounts are not allowed for the lab client")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", data["project"]):
        raise RuntimeError("Lab configuration requires a valid project ID")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", data["configuration"]):
        raise RuntimeError("Lab configuration requires an explicit named gcloud configuration")
    if any(value.startswith("YOUR_") or value.endswith("@example.com") for value in data.values()):
        raise RuntimeError("Replace example lab configuration values before cloud access")
    return LabConfig(**data)
