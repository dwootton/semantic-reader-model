"""Load audited compact HTML without joining its references to capture IDs.

The source snapshot and omission ledger are checked locally, never added to the
observed source view. Tree edges and mixed text order come from emitted HTML.
"""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "runs/compression/compact-semantic"
PROFILES = ("budget", "structure", "excerpt")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}
PARTIAL_ATTRIBUTES = {"data-excerpt", "data-deferred", "data-omitted-items",
                      "data-relations-deferred", "data-folded", "data-preview"}


class CompactInputError(ValueError):
    """The requested evidence is missing, unaudited, stale, or inconsistent."""


def _read(path):
    try:
        return path.read_bytes()
    except OSError as error:
        raise CompactInputError(f"Cannot read compact evidence: {path.name}") from error


def _json(raw, label):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise CompactInputError(f"Invalid JSON in {label}") from error


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _check_bytes(raw, metadata, label):
    if (not isinstance(metadata, dict)
            or type(metadata.get("bytes")) is not int
            or metadata["bytes"] != len(raw)
            or metadata.get("sha256") != _digest(raw)):
        raise CompactInputError(f"Stale or corrupt {label}: size/SHA256 mismatch")


def _artifact(metadata, label):
    if not isinstance(metadata, dict) or not isinstance(metadata.get("file"), str):
        raise CompactInputError(f"Missing artifact metadata: {label}")
    name = metadata["file"]
    root = ARTIFACT_ROOT.resolve()
    path = root / name
    # Artifacts are flat. Reject absolute paths, traversal, and escaping symlinks.
    if Path(name).name != name or not name or path.resolve().parent != root:
        raise CompactInputError(f"Unsafe artifact path: {label}")
    raw = _read(path)
    _check_bytes(raw, metadata, label)
    return raw


def _verify_current_source(item):
    """Check repo originals when present; never follow arbitrary report paths."""
    examples = (ROOT / "examples").resolve()
    original = Path(item["path"])
    if not original.is_absolute():
        raise CompactInputError("Original source path must be absolute")
    resolved = original.resolve()
    if not (original.is_relative_to(ROOT / "examples") or resolved.is_relative_to(examples)):
        return "snapshot-verified; external original not read"
    if not resolved.is_relative_to(examples):
        raise CompactInputError("Original source path escapes repository examples")
    _check_bytes(_read(resolved), {"bytes": item["sourceBytes"],
                                 "sha256": item["sourceSha256"]}, "current original source")
    return "current repository original and snapshot verified"


class _ObservedHTML(HTMLParser):
    """Parse only audited emitted HTML and namespace only its marker values."""

    def __init__(self, html, reference_attribute, namespace, document, ledger):
        super().__init__(convert_charrefs=True)
        self.html = html
        self.reference_attribute = reference_attribute
        self.namespace = namespace
        self.document = document
        self.ledger = ledger
        self.nodes = []
        self.roots = []
        self.stack = []
        self.assignable_ids = []
        self.mapping = {}
        self.replacements = []
        self.line_offsets = [0]
        for match in re.finditer("\n", html):
            self.line_offsets.append(match.end())

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if len(attributes) != len(attrs):
            raise CompactInputError("Duplicate emitted HTML attribute")
        reference = attributes.get(self.reference_attribute)
        if self.reference_attribute in attributes:
            if (not isinstance(reference, str) or not re.fullmatch(r"[0-9a-z]+", reference)
                    or reference not in self.ledger):
                raise CompactInputError("Unknown emitted compact reference")
            source = self.ledger[reference]
            if source["disposition"] != "retained" or source["tag"].lower() != tag:
                raise CompactInputError("Emitted reference disagrees with source ledger")
            if reference in self.mapping:
                raise CompactInputError("Duplicate emitted compact reference")
            key = self.namespace + ":" + reference
            self.mapping[reference] = key
            self.assignable_ids.append(key)
            attributes[self.reference_attribute] = key
            self._replace_attribute(self.reference_attribute, reference, key)
        else:
            key = f"{self.namespace}:synthetic-{len(self.nodes)}"
        if "data-target-ref" in attributes:
            target = attributes["data-target-ref"]
            if not isinstance(target, str) or not re.fullmatch(r"[0-9a-z]+", target):
                raise CompactInputError("Invalid compact target reference")
            attributes["data-target-ref"] = self.namespace + ":" + target
            self._replace_attribute("data-target-ref", target, attributes["data-target-ref"])
        parent = self.stack[-1] if self.stack else None
        own_partial = bool(PARTIAL_ATTRIBUTES.intersection(attributes))
        partial_sources = list(parent["partial_sources"]) if parent else []
        if own_partial:
            partial_sources.append(key)
        node = {"id": key, "parent": parent["id"] if parent else None,
                "children": [], "tag": tag, "text": "", "ownText": "",
                "ownTextAvailable": True, "content": [], "attributes": attributes,
                "hidden": bool((parent and parent["hidden"]) or "hidden" in attributes
                               or attributes.get("aria-hidden") == "true"),
                "document": self.document, "assignable": reference is not None,
                "partial": bool(partial_sources), "partial_sources": partial_sources}
        self.nodes.append(node)
        if parent:
            parent["children"].append(key)
            parent["content"].append({"id": key})
        else:
            self.roots.append(key)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def _replace_attribute(self, attribute, original, replacement):
        # Preserve audited bytes outside the explicitly namespaced values.
        raw = self.get_starttag_text()
        pattern = r"(?<![\w:-])" + re.escape(attribute) + r"\s*=\s*([\"'])(.*?)\1"
        matches = list(re.finditer(pattern, raw, flags=re.DOTALL))
        if len(matches) != 1 or matches[0].group(2) != original:
            raise CompactInputError("Unrecognized compact reference serialization")
        line, column = self.getpos()
        offset = self.line_offsets[line - 1] + column
        match = matches[0]
        self.replacements.append((offset + match.start(2), offset + match.end(2), replacement))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack or self.stack[-1]["tag"] != tag:
            raise CompactInputError(f"Unbalanced emitted compact HTML: {tag}")
        self.stack.pop()

    def handle_data(self, data):
        if self.stack:
            content = self.stack[-1]["content"]
            if content and isinstance(content[-1], str):
                content[-1] += data
            else:
                content.append(data)

    def finish(self):
        self.feed(self.html)
        self.close()
        if self.stack:
            raise CompactInputError("Unclosed emitted compact HTML")
        lookup = {node["id"]: node for node in self.nodes}
        emitted_ids = set(self.assignable_ids)
        for node in self.nodes:
            target = node["attributes"].get("data-target-ref")
            if target is not None and target not in emitted_ids:
                raise CompactInputError("Dangling emitted compact target reference")
        texts = {}
        for node in reversed(self.nodes):
            own = [part for part in node["content"] if isinstance(part, str)]
            text = "".join(part if isinstance(part, str) else texts[part["id"]]
                           for part in node["content"])
            texts[node["id"]] = text
            node["ownText"] = "".join(own).strip()
            node["text"] = text.strip()
        # Derivation above is preorder/reverse-preorder; assert it remains a tree.
        if len(lookup) != len(self.nodes):
            raise CompactInputError("Nonunique compact source-view IDs")
        html = self.html
        for start, end, replacement in sorted(self.replacements, reverse=True):
            html = html[:start] + replacement + html[end:]
        return html


def _document(item, row, index):
    if (row.get("status") != "passed" or row.get("passed") is not True
            or not isinstance(row.get("checks"), dict) or not row["checks"]
            or not {"controlInventoryPreserved", "recordBoundariesPreserved"} <= row["checks"].keys()
            or any(type(check) is not bool or not check for check in row["checks"].values())):
        raise CompactInputError(f"Compact audit did not pass: {item['id']} / {row.get('profile')}")
    for left, right in (("id", "id"), ("dataset", "dataset"), ("document", "document"),
                        ("path", "sourcePath"), ("sourceSha256", "sourceSha256"),
                        ("sourceBytes", "sourceBytes")):
        if item.get(left) != row.get(right):
            raise CompactInputError("Compact result does not match document inventory")
    source = _artifact(row.get("sourceArtifact"), "original source snapshot")
    _check_bytes(source, {"bytes": item["sourceBytes"], "sha256": item["sourceSha256"]},
                 "inventoried source snapshot")
    freshness = _verify_current_source(item)
    artifacts = row.get("artifacts", {})
    html_raw = _artifact(artifacts.get("html"), "compact HTML")
    ledger_raw = _artifact(artifacts.get("sourceMap"), "source map")
    request_raw = _artifact(artifacts.get("request"), "prepared request")
    try:
        html = html_raw.decode("utf-8")
    except UnicodeError as error:
        raise CompactInputError("Compact HTML is not UTF-8") from error
    reference_attribute = row.get("referenceAttribute")
    if not isinstance(reference_attribute, str) or not re.fullmatch(r"data-r(?:-x)*", reference_attribute):
        raise CompactInputError("Invalid compact reference attribute")
    request = _json(request_raw, "prepared request")
    if (not isinstance(request, dict) or set(request) != {"system", "user"}
            or any(not isinstance(value, str) for value in request.values())):
        raise CompactInputError("Invalid compact request envelope")
    user = _json(request["user"], "prepared user request")
    if (not isinstance(user, dict)
            or set(user) != {"task", "group_budget", "output_schema", "reference_attribute", "html"}
            or user["html"] != html or user["reference_attribute"] != reference_attribute):
        raise CompactInputError("Prepared request does not match compact HTML")
    if (len(html_raw) != row.get("htmlBytes")
            or sum(len(value.encode("utf-8")) for value in request.values()) != row.get("requestInputBytes")):
        raise CompactInputError("Compact byte measurements do not match artifacts")
    ledger = _json(ledger_raw, "source map")
    if not isinstance(ledger, list) or len(ledger) != row.get("sourceElements"):
        raise CompactInputError("Incomplete compact source ledger")
    by_reference = {}
    for entry in ledger:
        if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                or not re.fullmatch(r"[0-9a-z]+", entry["id"])
                or not isinstance(entry.get("tag"), str)
                or entry.get("disposition") not in {"retained", "collapsed", "deferred", "excluded"}
                or entry["id"] in by_reference):
            raise CompactInputError("Invalid compact source ledger entry")
        by_reference[entry["id"]] = entry
    parsed = _ObservedHTML(html, reference_attribute, f"d{index}", item["document"], by_reference)
    namespaced_html = parsed.finish()
    if (len(parsed.nodes) != row.get("outputElements")
            or sum(entry["disposition"] == "retained" for entry in ledger) != len(parsed.nodes)):
        raise CompactInputError("Compact parsed element count differs from audit")
    document = {"id": item["id"], "html": namespaced_html,
                "reference_attribute": reference_attribute, "nodes": parsed.nodes,
                "assignable_ids": parsed.assignable_ids, "roots": parsed.roots, "audit": row}
    provenance = {"id": item["id"], "namespace": f"d{index}", "source_sha256": item["sourceSha256"],
                  "source_artifact": row["sourceArtifact"], "artifacts": artifacts,
                  "source_freshness": freshness, "reference_mapping": parsed.mapping,
                  "model_html_sha256": _digest(namespaced_html.encode("utf-8")),
                  "transform": "Only emitted node references and data-target-ref values receive a document namespace."}
    return document, provenance


def load_compact(dataset_id, profile="budget"):
    """Return compact-only source evidence and separate local provenance.

    Every inventoried document is required. ``documents[*].html`` is model-ready
    evidence; provenance and audit objects must never be sent to the model.
    """
    if not isinstance(dataset_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", dataset_id):
        raise CompactInputError("Invalid compact dataset ID")
    if profile not in PROFILES:
        raise CompactInputError("Compact profile must be budget, structure, or excerpt")
    report_raw = _read(ARTIFACT_ROOT / "report.json")
    report = _json(report_raw, "compact report")
    if not isinstance(report, dict):
        raise CompactInputError("Invalid compact report")
    for field, filename in (("compressorSha256", "compact.js"), ("runnerSha256", "compact.py")):
        if report.get(field) != _digest(_read(ROOT / "experiments/dom-downsampling" / filename)):
            raise CompactInputError(f"Stale compact artifacts: {filename} SHA256 changed; regenerate them")
    inventory, results = report.get("inventory"), report.get("results")
    if not isinstance(inventory, list) or not isinstance(results, list):
        raise CompactInputError("Missing compact document inventory")
    items = [item for item in inventory if isinstance(item, dict) and item.get("dataset") == dataset_id]
    if not items or any(item.get("status") != "ready" for item in items):
        raise CompactInputError("No complete ready compact inventory for " + dataset_id)
    ids = [item.get("id") for item in items]
    if any(not isinstance(key, str) for key in ids) or len(set(ids)) != len(ids):
        raise CompactInputError("Invalid or duplicate compact inventory document IDs")
    rows = [row for row in results if isinstance(row, dict)
            and row.get("dataset") == dataset_id and row.get("profile") == profile]
    if len(rows) != len(items) or {row.get("id") for row in rows} != set(ids):
        raise CompactInputError("Missing or duplicate compact document results")
    row_by_id = {row["id"]: row for row in rows}
    documents, document_provenance = [], []
    for index, item in enumerate(items):
        document, provenance = _document(item, row_by_id[item["id"]], index)
        documents.append(document)
        document_provenance.append(provenance)
    nodes = [node for doc in documents for node in doc["nodes"]]
    roots = [key for doc in documents for key in doc["roots"]]
    limitations = [
        "Only emitted compact HTML is observed; deferred original content is not model evidence.",
        "Partial markers apply to the marked element and its descendants; previews are incomplete extracts.",
        "Compact references are document-local parser references, not original inspector capture IDs.",
        "No live CSS, geometry, or capture-ID joins are inferred from saved HTML.",
    ]
    metrics = {"original_nodes": sum(row["sourceElements"] for row in rows),
               "exposed_nodes": len(nodes),
               "exposed_reference_nodes": sum(len(doc["assignable_ids"]) for doc in documents),
               "deferred_nodes": sum(row["omittedElements"] for row in rows),
               "collapsed_nodes": sum(row["collapsedElements"] for row in rows),
               "excluded_nodes": sum(row["excludedElements"] for row in rows),
               "partial_nodes": sum(node["partial"] for node in nodes),
               "html_bytes": sum(len(doc["html"].encode("utf-8")) for doc in documents),
               "artifact_html_bytes": sum(row["htmlBytes"] for row in rows),
               "source_bytes": sum(row["sourceBytes"] for row in rows),
               "deferred_relations": sum(row["deferredRelations"] for row in rows),
               "original_text_characters": sum(row["sourceTextCharacters"] for row in rows),
               "exposed_text_characters": sum(row["exposedTextCharacters"] for row in rows),
               "preview_characters": sum(row["previewCharacters"] for row in rows),
               "original_controls": sum(row["originalControls"] for row in rows),
               "exposed_controls": sum(row["exposedControls"] for row in rows)}
    return {"dataset": {"id": dataset_id, "label": f"{dataset_id} · compact {profile}",
                        "url": "", "variants": {}, "screenshot": None,
                        "dom": {"roots": roots, "nodes": nodes}, "limitations": limitations},
            "documents": documents,
            "provenance": {"profile": profile, "report_sha256": _digest(report_raw),
                           "created_at": report.get("createdAt"),
                           "compressor_sha256": report["compressorSha256"],
                           "runner_sha256": report["runnerSha256"],
                           "documents": document_provenance},
            "metrics": metrics}
