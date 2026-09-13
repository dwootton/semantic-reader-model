"""One-site, read-only WebArena-Verified pilot adapter.

The normalized snapshot is the only browser observation intended for the reader.
Raw captures and strict evaluation details are researcher-only artifacts. Browser
reset creates a fresh session, not a database reset: the runner must reset the
disposable application between trials. Only explicitly selected read-only tasks
are permitted here.
"""

from __future__ import annotations

import copy
import importlib.resources
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PILOT_TASK_IDS = (157, 94, 344, 374)
BROWSERGYM_COMMIT = "9e779f087de9a65668b6974d11f9ce9816026e96"
VERIFIED_COMMIT = "6473f72db5dcefc97b5725b59e734504edc28a21"
SETTLING_TIMEOUT_MS = 15000
NETWORK_IDLE_TIMEOUT_MS = 2000
LOADING_MASK_SELECTOR = (
    '.admin__data-grid-loading-mask:visible, [data-role="spinner"]:visible'
)


class CaptureNotReady(RuntimeError):
    """The application is still loading; this is not navigator behavior."""

    def __init__(self, capture_metadata: dict):
        super().__init__("capture_not_ready: a known loading mask remained visible")
        self.capture_metadata = copy.deepcopy(capture_metadata)


def _ax_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    if value is None:
        return ""
    return str(value)


def normalize_ax(observation: dict, snapshot_id: str) -> dict:
    """Preserve all distinct AX nodes, including containers and readable text.

    BrowserGym obtains ``browsergym_id`` from its injected ARIA metadata during
    CDP extraction. AX ``nodeId`` is not a browser action target. Missing bids
    remain None; no locator is guessed from an accessible name or AX node ID.
    CDP can repeat identical InlineTextBox records. Coalesce exact duplicates
    while retaining the original capture and reporting the duplicate counts.
    Conflicting records with the same ID remain an unsupported ambiguity.
    """
    raw_nodes = observation["axtree_object"]["nodes"]
    by_id: dict[str, dict] = {}
    duplicated_ids = set()
    for raw in raw_nodes:
        node_id = str(raw["nodeId"])
        if node_id in by_id:
            if raw != by_id[node_id]:
                raise ValueError("Conflicting AX records share a node ID")
            duplicated_ids.add(node_id)
        else:
            by_id[node_id] = raw
    ids = set(by_id)

    def scoped(node_id: Any) -> str:
        return f"{snapshot_id}:ax:{node_id}"

    nodes = []
    child_ids = set()
    for raw in by_id.values():
        children = [str(item) for item in raw.get("childIds", [])]
        if any(item not in ids for item in children):
            raise ValueError("AX capture contains a missing child reference")
        child_ids.update(children)
        bid = raw.get("browsergym_id")
        nodes.append(
            {
                "id": scoped(raw["nodeId"]),
                "role": _ax_text(raw.get("role")),
                "name": _ax_text(raw.get("name")),
                "value": _ax_text(raw.get("value")),
                "children": [scoped(item) for item in children],
                "bid": str(bid) if bid is not None else None,
                "ignored": bool(raw.get("ignored", False)),
                "description": _ax_text(raw.get("description")),
                "properties": copy.deepcopy(raw.get("properties", [])),
            }
        )
    roots = [
        scoped(raw["nodeId"])
        for raw in by_id.values()
        if str(raw["nodeId"]) not in child_ids
    ]
    if nodes and not roots:
        raise ValueError("AX capture has no root")
    return {
        "snapshot_id": snapshot_id,
        "url": observation["url"],
        "nodes": nodes,
        "roots": roots,
        "capture_metadata": {
            "raw_ax_record_count": len(raw_nodes),
            "unique_ax_node_count": len(by_id),
            "exact_duplicate_records_coalesced": len(raw_nodes) - len(by_id),
            "duplicated_ax_id_count": len(duplicated_ids),
        },
    }


def strict_verdict(result: Any) -> dict:
    """Keep the complete official result; never count partial reward as success."""
    payload = (
        result.model_dump(mode="json")
        if hasattr(result, "model_dump")
        else copy.deepcopy(result)
    )
    components = payload.get("evaluators_results", [])
    payload["strict_success"] = (
        payload.get("status") == "success"
        and payload.get("score") == 1.0
        and bool(components)
        and all(
            item.get("status") == "success" and item.get("score") == 1.0
            for item in components
        )
    )
    return payload


def _dataset() -> list[dict]:
    return json.loads(
        importlib.resources.files("webarena_verified")
        .joinpath("assets/dataset/webarena-verified.json")
        .read_text()
    )


def list_tasks(task_ids: tuple[int, ...] | list[int] = PILOT_TASK_IDS) -> list[dict]:
    """Return only public ID and intent. Hidden evaluator answers stay private."""
    if set(task_ids) - set(PILOT_TASK_IDS):
        raise ValueError("Only the reviewed read-only pilot tasks are supported")
    by_id = {task["task_id"]: task for task in _dataset()}
    return [
        {"task_id": task_id, "intent": by_id[task_id]["intent"]} for task_id in task_ids
    ]


def final_answer_schema() -> dict:
    from webarena_verified.types import FinalAgentResponse

    return FinalAgentResponse.model_json_schema()


def _configure_site() -> None:
    os.environ.setdefault("WA_SHOPPING_ADMIN", "http://localhost:7780/admin")
    for name in ("SHOPPING", "REDDIT", "GITLAB", "WIKIPEDIA", "MAP", "HOMEPAGE"):
        os.environ.setdefault(f"WA_{name}", "todo")


def _headers() -> dict[str, str]:
    """Read externally provisioned test auth without logging credential values."""
    path = os.environ.get("PW_EXTRA_HEADERS")
    inline = os.environ.get("SEMANTIC_READER_EXTRA_HEADERS")
    if path and inline:
        raise ValueError(
            "Configure extra headers through either file or environment, not both"
        )
    try:
        values = json.loads(Path(path).read_text() if path else inline or "{}")
    except (OSError, ValueError):
        raise ValueError("Cannot read the configured browser extra headers") from None
    if not isinstance(values, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in values.items()
    ):
        raise ValueError("Browser extra headers must be a JSON object of strings")
    return values


def allowed_request(url: str, site_url: str) -> bool:
    """Only the configured application origin; never metadata/reset services."""
    request = urlsplit(url)
    site = urlsplit(site_url)
    return request.scheme in ("http", "https") and (request.scheme, request.netloc) == (
        site.scheme,
        site.netloc,
    )


class Benchmark:
    def __init__(self, task_id: int, *, seed: int = 42):
        if task_id not in PILOT_TASK_IDS:
            raise ValueError("Task is outside the reviewed read-only pilot set")
        self.task_id = task_id
        self.seed = seed
        self._env: Any = None
        self._observation: dict | None = None
        self._snapshot: dict | None = None
        self._finished = False
        self._last_action_error = ""
        self._capture_metadata: dict = {}

    @property
    def intent(self) -> str:
        return list_tasks([self.task_id])[0]["intent"]

    @property
    def last_action_error(self) -> str:
        return self._last_action_error

    @property
    def capture_metadata(self) -> dict:
        return copy.deepcopy(self._capture_metadata)

    def reset(self) -> dict:
        """Fresh browser session. The runner separately restores application data."""
        self.close()
        _configure_site()
        headers = _headers()
        header_login = "X-M2-Admin-Auto-Login" in headers

        from browsergym.core.env import BrowserEnv
        from browsergym.webarena_verified.task import WebArenaVerifiedTask

        class PilotTask(WebArenaVerifiedTask):
            def __init__(inner, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if header_login:
                    # BrowserGym otherwise always attempts password UI login,
                    # even when the optimized site has already auto-logged in.
                    def login(site, page):
                        if site != "shopping_admin":
                            raise ValueError(
                                "Header login is only configured for shopping_admin"
                            )
                        page.goto(inner.webarena_instance.urls[site])

                    inner.webarena_instance.ui_login = login

            def setup(inner, page):
                site_url = inner.webarena_instance.urls["shopping_admin"]

                def guard(route):
                    if allowed_request(route.request.url, site_url):
                        route.continue_()
                    else:
                        route.abort("blockedbyclient")

                page.context.route("**/*", guard)
                return super().setup(page)

            def validate(inner, page, chat_messages):
                # Keep scoring entirely out of the action/observation loop.
                # Only Benchmark.finish stops tracing and invokes the official
                # evaluator; the origin guard above constrains navigation.
                return 0.0, False, "", {}

        self._env = BrowserEnv(
            task_entrypoint=PilotTask,
            task_kwargs={"task_id": self.task_id},
            headless=True,
            slow_mo=0,
            timeout=30000,
            tags_to_mark="all",
            pw_context_kwargs={
                "extra_http_headers": headers,
                "service_workers": "block",
            },
        )
        try:
            observation, _ = self._env.reset(seed=self.seed)
        except Exception:
            self.close()
            raise
        self._finished = False
        return self._capture(observation)

    def _capture(self, observation: dict) -> dict:
        """Apply the same bounded readiness policy after reset and every action.

        Network idle is advisory because polling can keep a page busy. Visible
        Magento grid/spinner masks are decisive. The waiting budget is 15s;
        BrowserGym's fresh DOM/AX extraction adds its ordinary capture cost.
        Readiness checks inspect only loading state and never supply DOM/script
        results to the navigator. `_get_obs` is the pinned BrowserGym recapture
        implementation; it does not run an actor action or score the task.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        started = time.monotonic()
        deadline = started + SETTLING_TIMEOUT_MS / 1000
        settling = {
            "policy": "network-idle-then-known-loading-masks-v1",
            "waiting_budget_ms": SETTLING_TIMEOUT_MS,
            "network_idle_budget_ms": NETWORK_IDLE_TIMEOUT_MS,
            "network_idle_timeout": False,
            "loading_mask_timeout": False,
            "status": "settling",
            "duration_ms": 0,
        }
        self._capture_metadata = {"settling": settling}
        self._snapshot = None
        self._observation = observation
        self._last_action_error = observation.get("last_action_error", "")
        page = self._env.page
        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=min(NETWORK_IDLE_TIMEOUT_MS, SETTLING_TIMEOUT_MS),
            )
        except PlaywrightTimeoutError:
            settling["network_idle_timeout"] = True

        while True:
            masks = page.locator(LOADING_MASK_SELECTOR)
            remaining_ms = max(0, (deadline - time.monotonic()) * 1000)
            if masks.count() and remaining_ms > 0:
                try:
                    masks.first.wait_for(state="hidden", timeout=remaining_ms)
                except PlaywrightTimeoutError:
                    settling["loading_mask_timeout"] = True
                else:
                    # More than one independently loading grid can be present.
                    continue

            # The earlier BrowserGym observation may contain only the spinner.
            # Re-extract actual source IDs and preserve the actor's error text.
            observation = self._env._get_obs()
            self._observation = observation
            self._last_action_error = observation.get("last_action_error", "")
            if not page.locator(LOADING_MASK_SELECTOR).count():
                settling["status"] = "ready"
                break
            if time.monotonic() >= deadline:
                settling["loading_mask_timeout"] = True
                settling["status"] = "capture_not_ready"
                settling["duration_ms"] = round((time.monotonic() - started) * 1000)
                raise CaptureNotReady(self._capture_metadata)

        settling["duration_ms"] = round((time.monotonic() - started) * 1000)
        self._snapshot = normalize_ax(observation, uuid.uuid4().hex)
        self._snapshot["capture_metadata"].update(self._capture_metadata)
        self._capture_metadata = copy.deepcopy(self._snapshot["capture_metadata"])
        return copy.deepcopy(self._snapshot)

    def raw_capture(self) -> dict:
        """Researcher-only AX/DOM capture, excluding goal, task config, and chat.

        Do not put this result into navigator context. DOM may contain hidden
        application data; the reader fallback uses normalized AX exclusively.
        """
        if self._observation is None:
            raise RuntimeError("Call reset before requesting a capture")
        keys = (
            "url",
            "dom_object",
            "axtree_object",
            "extra_element_properties",
            "focused_element_bid",
        )
        capture = {
            key: copy.deepcopy(self._observation[key])
            for key in keys
            if key in self._observation
        }
        capture["capture_metadata"] = self.capture_metadata
        return capture

    def act(self, action: dict) -> dict:
        """Execute one grounded click/fill; reader must also require exposure."""
        if self._env is None or self._snapshot is None or self._finished:
            raise RuntimeError("No active benchmark trial")
        if (
            action.get("snapshot_id", self._snapshot["snapshot_id"])
            != self._snapshot["snapshot_id"]
        ):
            raise ValueError("Stale snapshot action")
        bid = action.get("bid")
        if not isinstance(bid, str) or bid not in {
            node["bid"] for node in self._snapshot["nodes"] if node["bid"] is not None
        }:
            raise ValueError("Action bid is absent from the current AX snapshot")
        kind = action.get("kind")
        if kind == "click":
            code = f"click({bid!r})"
        elif kind == "fill" and isinstance(action.get("value"), str):
            code = f"fill({bid!r}, {action['value']!r})"
        else:
            raise ValueError("Supported actions are click and fill with a string value")
        observation, _, terminated, truncated, _ = self._env.step(code)
        if terminated or truncated:
            raise RuntimeError(
                "Browser task ended unexpectedly before an explicit final answer"
            )
        return self._capture(observation)

    def finish(self, answer: dict | str) -> dict:
        """Return official full scoring without BrowserGym's reward averaging.

        Keep this result out of all generator/navigator contexts: component
        details include expected values. The raw trace is temporary because it
        can contain application cookies and external authentication headers.
        """
        if self._env is None or self._finished:
            raise RuntimeError("No active benchmark trial")
        from webarena_verified.types import WebArenaVerifiedTask
        from webarena_verified.types.eval import TaskEvalContext
        from webarena_verified.types.tracing import NetworkTrace

        task = self._env.task
        evaluator = task.evaluator.evaluator
        response_raw = json.dumps(answer) if isinstance(answer, dict) else answer
        with tempfile.TemporaryDirectory(prefix="semantic-evaluation-") as directory:
            trace_path = Path(directory) / "trace.zip"
            self._env.page.context.tracing.stop(path=trace_path)
            self._finished = True
            context = TaskEvalContext(
                task=WebArenaVerifiedTask.model_validate(task.config),
                agent_response_raw=response_raw,
                network_trace=NetworkTrace.from_content(trace_path),
                config=evaluator.config,
            )
            result = evaluator.evaluate_task(context=context)
        return strict_verdict(result)

    def close(self) -> None:
        if self._env is not None:
            config_file = getattr(getattr(self._env, "task", None), "config_file", None)
            try:
                self._env.close()
            finally:
                self._env = None
                if config_file:
                    Path(config_file).unlink(missing_ok=True)
        self._observation = None
        self._snapshot = None
        self._capture_metadata = {}
