"""Bounded Vertex REST client using only the verified lab user's credentials."""

import json
import os
from pathlib import Path
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from harness.lab_config import load_lab_config

_LAB_CONFIG = load_lab_config(required=False)
# Retain metadata imports for runners; cloud operations require explicit config.
ACCOUNT = _LAB_CONFIG.account if _LAB_CONFIG else ""
PROJECT = _LAB_CONFIG.project if _LAB_CONFIG else ""
CONFIGURATION = _LAB_CONFIG.configuration if _LAB_CONFIG else ""
GCLOUD = _LAB_CONFIG.gcloud if _LAB_CONFIG else []


def _require_lab_config():
    if _LAB_CONFIG is None:
        raise RuntimeError("Cloud access requires a local .lab-config.json; see .lab-config.example.json")
    return _LAB_CONFIG


CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class CredentialRefreshRequired(RuntimeError):
    pass


def local_lab_token():
    """Refresh only the named user's token; never consult application defaults."""
    lab = _require_lab_config()
    forbidden = (
        "CLOUDSDK_AUTH_ACCESS_TOKEN", "CLOUDSDK_AUTH_ACCESS_TOKEN_FILE",
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", "CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT",
        "GOOGLE_APPLICATION_CREDENTIALS",
    )
    if any(os.environ.get(name) for name in forbidden):
        raise RuntimeError("Credential overrides are not allowed for the lab pilot")
    config = json.loads(subprocess.check_output(
        lab.gcloud + ["config", "configurations", "describe", lab.configuration, "--format=json"],
        text=True,
    ))
    core = config["properties"]["core"]
    if core.get("account") != lab.account or core.get("project") != lab.project:
        raise RuntimeError("Lab configuration identity/project mismatch")
    auth = config.get("properties", {}).get("auth", {})
    if any(auth.get(key) for key in ("impersonate_service_account", "credential_file_override", "access_token_file")):
        raise RuntimeError("Configured credential overrides are not allowed")
    # The installed gcloud implementation refreshes for an explicit scope,
    # rather than returning a cached token close to its actual expiration.
    return subprocess.check_output(
        lab.gcloud + ["auth", "print-access-token", f"--scopes={CLOUD_SCOPE}"], text=True,
    ).strip()


def local_lab_envelope():
    """Mint and verify a scoped lab token; return only a private envelope."""
    lab = _require_lab_config()
    token = local_lab_token()
    query = urllib.parse.urlencode({"access_token": token})
    request = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v2/tokeninfo?" + query, data=b"", method="POST",
    )
    checked_at = time.time()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            info = json.load(response)
    except (OSError, urllib.error.URLError, ValueError):
        # Tokeninfo takes a query parameter. Do not surface a URL or chained
        # HTTP exception that could include the credential.
        raise RuntimeError("Could not verify the lab token identity and expiration") from None
    if info.get("email") != lab.account or info.get("verified_email") is not True:
        raise RuntimeError("Issued token does not identify the approved lab user")
    if CLOUD_SCOPE not in info.get("scope", "").split():
        raise RuntimeError("Issued token lacks the required cloud scope")
    lifetime = int(info.get("expires_in", 0))
    if lifetime < 600:
        raise RuntimeError("New lab token has insufficient remaining lifetime")
    return {
        "account": lab.account, "project": lab.project, "issued_at": checked_at,
        "expires_at": checked_at + lifetime, "access_token": token,
    }


def read_lab_token(path):
    """Read a private token envelope created by infra/refresh_token.py."""
    lab = _require_lab_config()
    path = Path(path)
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise RuntimeError("Lab token file must be a private regular file (0600)")
    envelope = json.loads(path.read_text())
    if envelope.get("account") != lab.account or envelope.get("project") != lab.project:
        raise RuntimeError("Lab token envelope identity/project mismatch")
    if float(envelope.get("expires_at", 0)) <= time.time() + 60:
        raise CredentialRefreshRequired("Lab token needs refresh before further model requests")
    return envelope["access_token"]


class ModelError(RuntimeError):
    pass


class LabClient:
    def __init__(self, output_dir, token_file=None, max_calls=650, min_interval=10.0, max_attempts=6,
                 shared_budget=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = token_file or os.environ.get("SEMANTIC_LAB_TOKEN_FILE")
        self.max_calls = max_calls
        self.shared_budget = shared_budget
        if min_interval < 0 or max_attempts < 1:
            raise ValueError("Request interval must be nonnegative and attempts positive")
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self._next_request_at = {}
        self.deadline: float | None = None
        self.calls = 0
        self.usage = {}
        self._local_token = None
        self._local_expires_at = 0
        self.auth_wait_seconds = 360.0

    def _token(self):
        if self.token_file:
            return read_lab_token(self.token_file)
        if self._local_token is None or time.time() + 60 >= self._local_expires_at:
            envelope = local_lab_envelope()
            self._local_token = envelope["access_token"]
            self._local_expires_at = envelope["expires_at"]
        return self._local_token

    def _log(self, event):
        with (self.output_dir / "model_calls.jsonl").open("a") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _credential_event(self, phase, model, purpose):
        with (self.output_dir / "credential_events.jsonl").open("a") as stream:
            stream.write(json.dumps({
                "phase": phase, "model": model, "purpose": purpose, "at": time.time(),
            }) + "\n")

    def _wait_for_token(self, model, purpose, rejected=None):
        """Wait for the authorized monitor to rotate a private file, never fallback."""
        self._credential_event("waiting", model, purpose)
        if not self.token_file:
            self._local_token = None
        stop = time.monotonic() + self.auth_wait_seconds
        while True:
            self._check_time()
            try:
                token = self._token()
            except CredentialRefreshRequired:
                token = None
            if token is not None and token != rejected:
                self._credential_event("resumed", model, purpose)
                return token
            if time.monotonic() >= stop:
                raise ModelError("No refreshed lab credential arrived within the waiting budget")
            self._check_time(5)
            time.sleep(5)

    def _pace(self, model):
        delay = max(0.0, self._next_request_at.get(model, 0.0) - time.monotonic())
        self._check_time(delay)
        if delay:
            time.sleep(delay)
        self._next_request_at[model] = time.monotonic() + self.min_interval
        return delay

    def _check_time(self, proposed_wait=0.0):
        if self.deadline is not None and time.monotonic() + proposed_wait >= self.deadline:
            raise ModelError("Pilot run time budget exhausted")

    @staticmethod
    def _backoff(attempt, headers=None):
        delay = min(60.0, 15.0 * 2 ** attempt)
        try:
            retry_after = float((headers or {}).get("Retry-After", 0))
        except (TypeError, ValueError):
            retry_after = 0
        return min(60.0, max(delay, retry_after))

    def generate(self, model, system, prompt, *, purpose, max_tokens=4096, response_schema=None):
        """Return parsed JSON plus usage metadata. Request logs never include auth."""
        operation_started = time.monotonic()
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingLevel": "LOW"},
            },
        }
        if response_schema is not None:
            payload["generationConfig"]["responseSchema"] = response_schema
        if len(prompt) > 1000000:
            raise ModelError("Input exceeds the pilot size cap; it was not truncated")
        for attempt in range(self.max_attempts):
            if self.calls >= self.max_calls:
                raise ModelError("Pilot model call budget exhausted")
            self._check_time()
            lab = _require_lab_config()
            try:
                bearer = self._token()
            except CredentialRefreshRequired:
                bearer = self._wait_for_token(model, purpose)
            self._check_time()
            if self.shared_budget is None:
                pacing_seconds = self._pace(model)
                call_id = self.calls + 1
            else:
                from harness.shared_budget import BudgetExhausted, DeadlineExceeded
                try:
                    admission = self.shared_budget.reserve(model, deadline=self.deadline)
                except (BudgetExhausted, DeadlineExceeded) as error:
                    raise ModelError(str(error)) from error
                pacing_seconds = admission["pacing_seconds"]
                call_id = admission["call"]
            self._check_time()
            self.calls += 1
            started = time.time()
            event = {
                "call": call_id, "model": model, "purpose": purpose,
                "started_at": started, "attempt": attempt + 1, "request": payload,
                "pacing_seconds": pacing_seconds,
            }
            request = urllib.request.Request(
                f"https://aiplatform.googleapis.com/v1/projects/{lab.project}/locations/global/"
                f"publishers/google/models/{model}:generateContent",
                data=json.dumps(payload).encode(),
                headers={"Authorization": "Bearer " + bearer, "Content-Type": "application/json"},
            )
            try:
                timeout = 120 if self.deadline is None else min(120, max(0.1, self.deadline - time.monotonic()))
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    body = json.load(response)
                usage = body.get("usageMetadata", {})
                for key, value in usage.items():
                    if isinstance(value, (int, float)):
                        self.usage[key] = self.usage.get(key, 0) + value
                parts = [
                    part.get("text", "")
                    for candidate in body.get("candidates", [])
                    for part in candidate.get("content", {}).get("parts", [])
                    if not part.get("thought")
                ]
                text = "".join(parts)
                event.update(response=body, elapsed_seconds=time.time() - started)
                self._log(event)
                try:
                    result = json.loads(text)
                except json.JSONDecodeError as error:
                    raise ModelError("Model returned incomplete or invalid JSON") from error
                if not isinstance(result, dict):
                    raise ModelError("Model response must be a JSON object")
                return result, {
                    "call": call_id, "model_version": body.get("modelVersion", model),
                    "usage": usage, "elapsed_seconds": event["elapsed_seconds"],
                    "operation_elapsed_seconds": time.monotonic() - operation_started,
                }
            except urllib.error.HTTPError as error:
                try:
                    message = json.loads(error.read()).get("error", {}).get("message", "")
                except (ValueError, AttributeError):
                    message = "HTTP request failed"
                event.update(error={"status": error.code, "message": message[:800]},
                             elapsed_seconds=time.time() - started)
                retry = (error.code in (429, 500, 502, 503, 504)
                         and attempt + 1 < self.max_attempts and self.calls < self.max_calls)
                if retry:
                    event["retry_delay_seconds"] = self._backoff(attempt, error.headers)
                self._log(event)
                if error.code == 401 and attempt + 1 < self.max_attempts and self.calls < self.max_calls:
                    self._wait_for_token(model, purpose, rejected=bearer)
                    continue
                if retry:
                    self._check_time(event["retry_delay_seconds"])
                    time.sleep(event["retry_delay_seconds"])
                    continue
                raise ModelError(f"Vertex HTTP {error.code}: {message[:300]}") from error
            except (TimeoutError, urllib.error.URLError) as error:
                event.update(error={"type": type(error).__name__},
                             elapsed_seconds=time.time() - started)
                retry = attempt + 1 < self.max_attempts and self.calls < self.max_calls
                if retry:
                    event["retry_delay_seconds"] = self._backoff(attempt)
                self._log(event)
                if retry:
                    self._check_time(event["retry_delay_seconds"])
                    time.sleep(event["retry_delay_seconds"])
                    continue
                raise ModelError("Vertex request timed out or network failed") from error
