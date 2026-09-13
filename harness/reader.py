"""Incremental, snapshot-bound reader for the semantic hierarchy pilot.

Public API:
    validate_projection(snapshot, projection) -> normalized projection dict
    baseline_projection(snapshot) -> deterministic source-root projection dict
    Reader(snapshot, projection, page_size=12)
    Reader.view() -> observation dict (this records one presentation)
    Reader.step({"op": ..., "target": ..., "value": ...}) -> observation/action receipt

Snapshot nodes use id/role/name/value/children/bid; projections use a groups list
with id/label/parent/source_ids. Returned IDs are g:<group-id> and s:<source-id>.
Only IDs in the most recently returned page may be expanded or acted on.
The source operation with no target exposes source roots; headings, landmarks,
and controls expose paginated native indices. next/previous change pages; up
restores the preceding location and page. No operation searches hidden text.

Browser actions are returned, never performed: {browser_action: {kind: 'click'
or 'fill', bid: str, value?: str}, accounting: {words: 0, choices: 0}, totals: ...}.
An action receipt does not present or charge another view. Construct a NEW Reader after browser changes
so targets cannot remain exposed across source revisions. Invalid operations
raise ReaderError and do not record another presentation or movement.

accounting.words counts whitespace-separated tokens in the JSON observation
before accounting/totals are added (ensure_ascii=False, sort_keys=True). choices
counts displayed items. Repeated view() calls are charged again. totals includes
observations, words, choices, navigation_moves, and browser_actions. Metadata is
included in words; accounting metadata itself is excluded to avoid recursion.
"""

from __future__ import annotations

import copy
import json
from typing import Any


LANDMARK_ROLES = frozenset({
    "banner", "complementary", "contentinfo", "form", "main", "navigation",
    "region", "search", "dialog", "alertdialog",
})
FILL_ROLES = frozenset({"textbox", "searchbox", "combobox", "spinbutton"})
ACTIVATE_ROLES = FILL_ROLES | frozenset({
    "button", "link", "checkbox", "radio", "switch", "tab", "menuitem",
    "menuitemcheckbox", "menuitemradio", "option", "treeitem", "slider",
    "listbox", "select", "disclosuretriangle",
})
STATE_PROPERTIES = frozenset({
    "checked", "selected", "expanded", "disabled", "required", "invalid",
    "readonly", "multiselectable", "level", "valuemin", "valuemax", "valuetext",
})


class ReaderError(ValueError):
    """A malformed snapshot/projection or an invalid reader action."""


def _ids(value: Any, description: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise ReaderError(f"{description} must be a list of nonempty string IDs")
    if len(set(value)) != len(value):
        raise ReaderError(f"{description} contains duplicate IDs")
    return list(value)


def _assert_acyclic(edges: dict[str, list[str]], description: str) -> None:
    # Iterative traversal also accepts the very deep AX trees of real websites.
    complete: set[str] = set()
    for root in edges:
        active: set[str] = set()
        pending = [(root, False)]
        while pending:
            node_id, leaving = pending.pop()
            if leaving:
                active.remove(node_id)
                complete.add(node_id)
            elif node_id in active:
                raise ReaderError(f"{description} contains a cycle at {node_id}")
            elif node_id not in complete:
                active.add(node_id)
                pending.append((node_id, True))
                pending.extend((child, False) for child in reversed(edges[node_id]))


def _snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, dict], list[str]]:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("snapshot_id"), str) or not snapshot["snapshot_id"]:
        raise ReaderError("snapshot_id must be a nonempty string")
    if not isinstance(snapshot.get("url"), str) or not isinstance(snapshot.get("nodes"), list):
        raise ReaderError("snapshot needs a URL string and nodes list")
    nodes: dict[str, dict] = {}
    for raw in snapshot["nodes"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise ReaderError("source node IDs must be nonempty strings")
        if raw["id"] in nodes:
            raise ReaderError(f"duplicate source ID: {raw['id']}")
        for key in ("role", "name", "value"):
            if not isinstance(raw.get(key), str):
                raise ReaderError(f"source {raw['id']} needs a {key} string")
        if raw.get("bid") is not None and (not isinstance(raw["bid"], str) or not raw["bid"]):
            raise ReaderError(f"source {raw['id']} has an invalid bid")
        nodes[raw["id"]] = {**raw, "children": _ids(raw.get("children"), "source children")}
    roots = _ids(snapshot.get("roots"), "source roots")
    for target in roots + [child for node in nodes.values() for child in node["children"]]:
        if target not in nodes:
            raise ReaderError(f"unknown source reference: {target}")
    _assert_acyclic({key: node["children"] for key, node in nodes.items()}, "source tree")
    # Preserve disconnected capture nodes instead of silently losing them.
    reachable: set[str] = set()

    def include(root: str) -> None:
        pending = [root]
        while pending:
            current = pending.pop()
            if current not in reachable:
                reachable.add(current)
                pending.extend(nodes[current]["children"])

    for root in roots:
        include(root)
    child_ids = {child for node in nodes.values() for child in node["children"]}
    for source_id in list(nodes):
        if source_id not in reachable and source_id not in child_ids:
            roots.append(source_id)
            include(source_id)
    if reachable != set(nodes):
        raise ReaderError("source nodes cannot all be reached from roots")
    return nodes, roots


def validate_projection(snapshot: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    """Validate references/topology; omission from groups is allowed via fallback."""
    nodes, _ = _snapshot(snapshot)
    if not isinstance(projection, dict) or not isinstance(projection.get("groups"), list):
        raise ReaderError("projection needs a groups list")
    groups: dict[str, dict] = {}
    for raw in projection["groups"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise ReaderError("group IDs must be nonempty strings")
        if raw["id"] in groups:
            raise ReaderError(f"duplicate group ID: {raw['id']}")
        if not isinstance(raw.get("label"), str) or not raw["label"].strip():
            raise ReaderError(f"group {raw['id']} needs a nonempty label")
        if "parent" not in raw or (raw["parent"] is not None and not isinstance(raw["parent"], str)):
            raise ReaderError(f"group {raw['id']} needs a string or null parent")
        source_ids = _ids(raw.get("source_ids"), "group source_ids")
        for source_id in source_ids:
            if source_id not in nodes:
                raise ReaderError(f"unknown source reference: {source_id}")
        groups[raw["id"]] = {
            "id": raw["id"], "label": raw["label"], "parent": raw["parent"],
            "source_ids": source_ids,
        }
    edges: dict[str, list[str]] = {key: [] for key in groups}
    for group in groups.values():
        if group["parent"] is not None:
            if group["parent"] not in groups:
                raise ReaderError(f"unknown group parent: {group['parent']}")
            edges[group["parent"]].append(group["id"])
    _assert_acyclic(edges, "projection")
    return {"groups": list(groups.values())}


def baseline_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Source-root baseline (not native semantic grouping or a generated method)."""
    nodes, roots = _snapshot(snapshot)
    return {"groups": [
        {"id": f"source-root-{index}", "label": nodes[root]["name"] or nodes[root]["role"] or "Source root",
         "parent": None, "source_ids": [root]}
        for index, root in enumerate(roots)
    ]}


class Reader:
    """Local, paginated navigation over a fixed snapshot and its projection."""

    def __init__(self, snapshot: dict[str, Any], projection: dict[str, Any], page_size: int = 12):
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ReaderError("page_size must be a positive integer")
        self.snapshot = copy.deepcopy(snapshot)
        self.nodes, self.roots = _snapshot(self.snapshot)
        self.projection = validate_projection(self.snapshot, projection)
        self.groups = {group["id"]: group for group in self.projection["groups"]}
        self.children: dict[str | None, list[str]] = {None: []}
        for group in self.groups.values():
            self.children.setdefault(group["parent"], []).append(group["id"])
        self.page_size = page_size
        self.location: tuple[str, str | None] = ("hierarchy", None)
        self.page = 0
        self.history: list[tuple[tuple[str, str | None], int]] = []
        self.exposed: dict[str, dict] = {}
        self.totals = dict(words=0, choices=0, observations=0, navigation_moves=0, browser_actions=0)

    def _source_item(self, source_id: str) -> dict[str, Any]:
        node = self.nodes[source_id]
        role = node["role"].lower()
        states = {}
        for prop in node.get("properties", []):
            value = prop.get("value", {}).get("value")
            if prop.get("name") in STATE_PROPERTIES and isinstance(value, (str, bool, int, float)):
                states[prop["name"]] = value
        actions = []
        if node.get("bid") and role in ACTIVATE_ROLES:
            actions.append("activate")
        if node.get("bid") and role in FILL_ROLES:
            actions.append("fill")
        return {"id": f"s:{source_id}", "kind": "source", "label": node["name"] or node["role"] or "Unnamed source",
                "role": node["role"], "value": node["value"], "description": node.get("description", ""),
                "states": states, "expandable": bool(node["children"]), "actions": actions}

    def _items(self) -> list[dict[str, Any]]:
        kind, target = self.location
        if kind == "hierarchy":
            items = [{"id": f"g:{group_id}", "kind": "group", "label": self.groups[group_id]["label"],
                      "expandable": True, "actions": []} for group_id in self.children.get(target, [])]
            if target is not None:
                grouped_sources: set[str] = set()
                pending = list(self.children.get(target, []))
                while pending:
                    child = pending.pop()
                    grouped_sources.update(self.groups[child]["source_ids"])
                    pending.extend(self.children.get(child, []))
                items.extend(self._source_item(sid) for sid in self.groups[target]["source_ids"] if sid not in grouped_sources)
            return items
        if kind == "source":
            source_ids = self.roots if target is None else self.nodes[target]["children"]
        elif kind == "group-source":
            source_ids = self.groups[target]["source_ids"]
        else:
            source_ids = [sid for sid, node in self.nodes.items() if (
                (kind == "headings" and node["role"].lower() == "heading") or
                (kind == "landmarks" and node["role"].lower() in LANDMARK_ROLES) or
                (kind == "controls" and node["role"].lower() in ACTIVATE_ROLES)
            )]
        return [self._source_item(source_id) for source_id in source_ids]

    def view(self) -> dict[str, Any]:
        """Return and charge for one localized observation, including repeats."""
        all_items = self._items()
        pages = max(1, (len(all_items) + self.page_size - 1) // self.page_size)
        items = all_items[self.page * self.page_size:(self.page + 1) * self.page_size]
        self.exposed = {item["id"]: item for item in items}
        available_ops = ["source", "headings", "landmarks", "controls"]
        if self.history:
            available_ops.append("up")
        if self.page:
            available_ops.append("previous")
        if self.page + 1 < pages:
            available_ops.append("next")
        if any(item["expandable"] for item in items):
            available_ops.append("expand")
        available_ops.extend(op for op in ("activate", "fill") if any(op in item["actions"] for item in items))
        kind, target = self.location
        label = kind
        if target is not None:
            if kind in ("hierarchy", "group-source"):
                label = self.groups[target]["label"]
            elif kind == "source":
                label = self.nodes[target]["name"] or self.nodes[target]["role"]
        observation = {
            "snapshot_id": self.snapshot["snapshot_id"], "url": self.snapshot["url"],
            "location": {"kind": kind, "target": target, "label": label, "depth": len(self.history)},
            "items": items, "page": self.page + 1, "pages": pages, "available_ops": available_ops,
        }
        accounting = {"words": len(json.dumps(observation, ensure_ascii=False, sort_keys=True).split()), "choices": len(items)}
        self.totals["observations"] += 1
        for key, amount in accounting.items():
            self.totals[key] += amount
        observation["accounting"] = accounting
        observation["totals"] = dict(self.totals)
        return copy.deepcopy(observation)

    def _target(self, value: Any) -> tuple[str, str, dict]:
        if not isinstance(value, str) or not value:
            raise ReaderError("operation requires a disclosed target ID")
        matches = [key for key in self.exposed if key == value or key[2:] == value]
        if len(matches) != 1:
            raise ReaderError(f"target is undisclosed or ambiguous: {value}")
        key = matches[0]
        return key[0], key[2:], self.exposed[key]

    def _enter(self, kind: str, target: str | None = None) -> None:
        self.history.append((self.location, self.page))
        self.location, self.page = (kind, target), 0

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        """Apply a reader move, or return an adapter-ready browser action."""
        if not isinstance(action, dict) or not isinstance(action.get("op"), str):
            raise ReaderError("action needs an op string")
        op = action["op"]
        browser_action = None
        if op in ("expand", "activate", "fill") or (op == "source" and action.get("target") is not None):
            prefix, target, item = self._target(action.get("target"))
            if op in ("activate", "fill"):
                if op not in item["actions"]:
                    raise ReaderError(f"target does not support {op}: {item['id']}")
                browser_action = {"kind": "click" if op == "activate" else "fill", "bid": self.nodes[target]["bid"]}
                if op == "fill":
                    if not isinstance(action.get("value"), str):
                        raise ReaderError("fill requires a string value")
                    browser_action["value"] = action["value"]
            elif op == "source" and prefix == "g":
                self._enter("group-source", target)
            elif prefix == "g":
                self._enter("hierarchy", target)
            elif item["expandable"]:
                self._enter("source", target)
            else:
                raise ReaderError(f"source target has no children: {item['id']}")
        elif op in ("source", "headings", "landmarks", "controls"):
            self._enter(op)
        elif op == "up":
            if not self.history:
                raise ReaderError("already at the root location")
            self.location, self.page = self.history.pop()
        elif op in ("next", "previous"):
            new_page = self.page + (1 if op == "next" else -1)
            if new_page < 0 or new_page * self.page_size >= len(self._items()):
                raise ReaderError(f"no {op} page")
            self.page = new_page
        else:
            raise ReaderError(f"unsupported operation: {op}")
        self.totals["browser_actions" if browser_action else "navigation_moves"] += 1
        if browser_action:
            return {"snapshot_id": self.snapshot["snapshot_id"], "browser_action": browser_action,
                    "accounting": {"words": 0, "choices": 0}, "totals": dict(self.totals)}
        return self.view()
