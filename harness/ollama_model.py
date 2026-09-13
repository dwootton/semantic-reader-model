"""Bounded local-only Ollama transport for the hierarchy comparison."""

import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from harness.model import ModelError


OLLAMA_URL = "http://127.0.0.1:11434"
TEMPLATE_TOKEN_ALLOWANCE = 1024


def json_schema(schema):
    """Translate Vertex schema types and nullable flags without changing data."""
    if not isinstance(schema, dict):
        raise ValueError("Response schema must be an object")
    result = {}
    for key, value in schema.items():
        if key == "nullable":
            continue
        if key == "type":
            result[key] = ([item.lower() for item in value] if isinstance(value, list)
                           else value.lower())
        elif key in ("properties", "$defs", "definitions", "patternProperties"):
            result[key] = {name: json_schema(child) for name, child in value.items()}
        elif key in ("items", "additionalProperties", "not", "if", "then", "else") and isinstance(value, dict):
            result[key] = json_schema(value)
        elif key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            result[key] = [json_schema(child) for child in value]
        else:
            result[key] = value
    if schema.get("nullable") is True:
        kind = result.get("type")
        if isinstance(kind, str):
            result["type"] = [kind, "null"] if kind != "null" else kind
        elif isinstance(kind, list):
            result["type"] = list(dict.fromkeys([*kind, "null"]))
        else:
            result = {"anyOf": [result, {"type": "null"}]}
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("Local Ollama redirects are not allowed")


class OllamaClient:
    def __init__(self, output_dir, *, num_ctx=131072, max_calls=40):
        if isinstance(num_ctx, bool) or not isinstance(num_ctx, int) or num_ctx < 1:
            raise ValueError("Ollama context size must be a positive integer")
        if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 0:
            raise ValueError("Ollama call budget must be a nonnegative integer")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.num_ctx = num_ctx
        self.max_calls = max_calls
        self.calls = 0
        self.deadline: float | None = None
        self.usage = {}
        # A local request must not inherit a proxy or follow a remote redirect.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _check_time(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise ModelError("Local model run time budget exhausted")

    def _log(self, event):
        with (self.output_dir / "model_calls.jsonl").open("a") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _request(self, path, payload, record):
        self._check_time()
        record.update(path=path, request=payload)
        request = urllib.request.Request(
            OLLAMA_URL + path,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        timeout = 1800.0 if self.deadline is None else min(1800.0, self.deadline - time.monotonic())
        if timeout <= 0:
            raise ModelError("Local model run time budget exhausted")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            record.update(http_status=error.code, response_text=raw)
            try:
                message = json.loads(raw).get("error", raw)
            except (ValueError, AttributeError):
                message = raw
            raise ModelError(f"Local Ollama HTTP {error.code}: {str(message)[:500]}") from error
        except (OSError, urllib.error.URLError) as error:
            raise ModelError(
                "Could not reach local Ollama at 127.0.0.1:11434, or its request timed out. "
                "Start Ollama locally and check the run time budget."
            ) from error
        try:
            body = json.loads(raw)
        except ValueError as error:
            record["response_text"] = raw
            raise ModelError("Local Ollama returned invalid JSON") from error
        record["response"] = body
        if not isinstance(body, dict):
            raise ModelError("Local Ollama API response must be a JSON object")
        if body.get("error"):
            raise ModelError(f"Local Ollama: {str(body['error'])[:500]}")
        self._check_time()
        return body

    @staticmethod
    def _reject_remote(record):
        if "remote_host" in record or "remote_model" in record:
            raise ModelError("Cloud-backed Ollama models are not allowed; choose an installed local model")

    def _verify_model(self, model, event):
        if not isinstance(model, str) or not model.strip():
            raise ModelError("Choose an installed local Ollama model")
        if ":cloud" in model.lower() or "-cloud" in model.lower():
            raise ModelError("Cloud-backed Ollama models are not allowed; choose an installed local model")
        checks = event["validation"]
        tags_record = {}
        checks.append(tags_record)
        tags = self._request("/api/tags", None, tags_record)
        names = {model, model + ":latest"} if ":" not in model.rsplit("/", 1)[-1] else {model}
        installed = next((item for item in tags.get("models", [])
                          if isinstance(item, dict) and (item.get("name") in names or item.get("model") in names)), None)
        if installed is None:
            raise ModelError(f"Ollama model {model!r} is not installed locally; no model was downloaded")
        self._reject_remote(installed)
        show_record = {}
        checks.append(show_record)
        shown = self._request("/api/show", {"model": model}, show_record)
        self._reject_remote(shown)
        info = shown.get("model_info", {})
        lengths = [value for key, value in info.items()
                   if key.endswith(".context_length") and isinstance(value, int)
                   and not isinstance(value, bool) and value > 0]
        if not lengths:
            raise ModelError("Cannot verify this local model's native context length; no prompt was sent")
        native_context = min(lengths)
        if self.num_ctx > native_context:
            raise ModelError(
                f"Requested Ollama context {self.num_ctx:,} exceeds the model's native context "
                f"{native_context:,}; lower the configured context. No prompt was sent."
            )
        return {"model_digest": installed.get("digest"), "native_context_length": native_context}

    def _verify_loaded_model(self, model, digest, event):
        record = {}
        event["validation"].append(record)
        running = self._request("/api/ps", None, record)
        names = {model, model + ":latest"} if ":" not in model.rsplit("/", 1)[-1] else {model}
        loaded = next((item for item in running.get("models", [])
                       if isinstance(item, dict) and (item.get("name") in names or item.get("model") in names)), None)
        if loaded is None:
            raise ModelError("Cannot verify the model's loaded context after generation; this sample was rejected")
        self._reject_remote(loaded)
        observed = {
            "loaded_context_length": loaded.get("context_length"),
            "loaded_size_vram": loaded.get("size_vram"),
            "loaded_model_digest": loaded.get("digest"),
        }
        record.update(observed)
        event.update(observed)
        context = loaded.get("context_length")
        if isinstance(context, bool) or not isinstance(context, int) or context < 1:
            raise ModelError("Cannot verify the model's loaded context length; this sample was rejected")
        if context < self.num_ctx:
            raise ModelError(
                f"Ollama loaded a smaller context ({context:,}) than requested ({self.num_ctx:,}); "
                "input may have been truncated, so this sample was rejected. "
                "Use a smaller model or a smaller supported context with a smaller capture/region."
            )
        if digest and loaded.get("digest") and loaded["digest"] != digest:
            raise ModelError("Loaded Ollama model digest differs from the installed model checked before generation; this sample was rejected")
        return observed

    def generate(self, model, system, prompt, *, purpose, max_tokens=4096, response_schema=None):
        """Return a JSON object and comparison-compatible stats, with no retries."""
        if self.calls >= self.max_calls:
            raise ModelError("Local model call budget exhausted")
        self._check_time()
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("Maximum output tokens must be a positive integer")
        schema = "json" if response_schema is None else json_schema(response_schema)
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "stream": False, "think": False, "format": schema,
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": max_tokens},
            "keep_alive": "5m",
        }
        # One token per UTF-8 byte deliberately overestimates normal tokenization.
        # Include the schema and template allowance; never silently shorten input.
        input_bound = (len(system.encode("utf-8")) + len(prompt.encode("utf-8"))
                       + len(json.dumps(schema, ensure_ascii=False).encode("utf-8"))
                       + TEMPLATE_TOKEN_ALLOWANCE)
        started = time.monotonic()
        event = {
            "backend": "ollama", "model": model, "purpose": purpose,
            "started_at": time.time(), "request": payload, "validation": [],
            "num_ctx": self.num_ctx, "input_token_upper_bound": input_bound,
            "input_bound_method": "conservative UTF-8 bytes plus schema and 1024 template tokens",
        }
        try:
            if input_bound + max_tokens > self.num_ctx:
                raise ModelError(
                    f"Input's conservative token bound ({input_bound:,}) plus output budget "
                    f"({max_tokens:,}) exceeds the configured context ({self.num_ctx:,}). "
                    "Choose a smaller capture/region or a larger supported context. "
                    "This bound is not an actual token count; no input was truncated or sent."
                )
            verified = self._verify_model(model, event)
            event.update(verified)
            self._check_time()
            self.calls += 1
            event["call"] = self.calls
            chat_started = time.monotonic()
            body = self._request("/api/chat", payload, event)
            elapsed = time.monotonic() - chat_started
            if body.get("done_reason") == "length":
                raise ModelError("Local model reached its output token limit; the hierarchy is incomplete")
            if body.get("done") is not True:
                raise ModelError("Local model did not finish its response; the hierarchy is incomplete")
            try:
                result = json.loads(body.get("message", {}).get("content", ""))
            except (ValueError, TypeError, AttributeError) as error:
                raise ModelError("Local model returned incomplete or invalid JSON") from error
            if not isinstance(result, dict):
                raise ModelError("Local model response must be a JSON object")
            verified.update(self._verify_loaded_model(model, verified["model_digest"], event))
            usage = {
                "promptTokenCount": body.get("prompt_eval_count", 0),
                "candidatesTokenCount": body.get("eval_count", 0),
            }
            usage["totalTokenCount"] = sum(usage.values())
            for key, value in usage.items():
                self.usage[key] = self.usage.get(key, 0) + value
            metadata = {
                "call": self.calls, "backend": "ollama", "model_version": body.get("model", model),
                "usage": usage, "elapsed_seconds": elapsed,
                "operation_elapsed_seconds": time.monotonic() - started,
                "num_ctx": self.num_ctx, "input_token_upper_bound": input_bound,
                "input_bound_method": event["input_bound_method"],
                "done_reason": body.get("done_reason"), **verified,
            }
            for key in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
                if isinstance(body.get(key), (int, float)):
                    metadata[key + "_seconds"] = body[key] / 1_000_000_000
            event["metadata"] = metadata
            return result, metadata
        except ModelError as error:
            event["error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            event["elapsed_seconds"] = time.monotonic() - started
            self._log(event)
