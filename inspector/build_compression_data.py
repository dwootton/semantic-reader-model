"""Export hash-verified compression comparisons as inert JSON, without fetching pages."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "runs/compression/compact-10pct"
DEFAULT_OUTPUT = ROOT / "inspector/data/compression"
LABELS = {
    "allrecipes": "Allrecipes", "apple": "Apple", "github": "GitHub",
    "gov-uk": "GOV.UK", "hacker-news": "Hacker News", "ikea": "IKEA",
    "mdn": "MDN", "nasa": "NASA", "openstreetmap": "OpenStreetMap",
    "smithsonian": "Smithsonian", "w3c-survey": "W3C Survey",
    "wikipedia": "Wikipedia", "nyt-homepage": "New York Times",
}
# DOMParser creates an inert document. It is never attached to the live page.
# Traversal deliberately mirrors compact.js, including template.content.
PARSE_TREE = r"""({source, compressed, marker}) => {
    const doc = new DOMParser().parseFromString(source, 'text/html');
    const nodes = [], roots = [];
    const children = node => node.localName === 'template' && node.content
        ? [...node.content.childNodes] : [...node.childNodes];
    function visit(node, parent) {
        if (node.nodeType !== 1) {
            for (const child of children(node)) visit(child, parent);
            return;
        }
        const id = compressed ? 'c' + nodes.length : nodes.length.toString(36);
        const item = {id, parent: parent ? parent.id : null, children: [],
            tag: node.localName,
            text: children(node).filter(n => n.nodeType === 3).map(n => n.data).join(' '),
            attributes: Object.fromEntries([...node.attributes].map(a => [a.name,a.value]))};
        if (compressed) item.sourceId = node.getAttribute(marker);
        nodes.push(item);
        if (parent) parent.children.push(id); else roots.push(id);
        for (const child of children(node)) visit(child, item);
    }
    visit(doc, null);
    return JSON.stringify({roots,nodes});
}"""


def verified_artifact(directory: Path, entry: dict[str, Any]) -> bytes:
    """Reject changed or escaped artifacts instead of exporting misleading joins."""
    path = (directory / entry["file"]).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError(f"Artifact escapes run directory: {entry['file']}")
    content = path.read_bytes()
    if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise ValueError(f"Artifact hash/length mismatch: {entry['file']}")
    return content


def validate_mapping(source: dict[str, Any], tree: dict[str, Any],
                     source_map: list[dict[str, Any]], report: dict[str, Any]) -> None:
    originals = source["nodes"]
    if len(originals) != report["sourceElements"] or len(source_map) != len(originals):
        raise ValueError("Source inventory count differs from recorded run")
    for node, record in zip(originals, source_map, strict=True):
        if (node["id"], node["tag"]) != (record["id"], record["tag"]):
            raise ValueError(f"Source preorder mapping drift at {node['id']}")
    if len(tree["nodes"]) != report["outputElements"]:
        raise ValueError("Output element count differs from recorded run")
    lookup = {node["id"]: node for node in originals}
    seen: set[str] = set()
    for node in tree["nodes"]:
        ref = node["sourceId"]
        # The compressor deliberately omits references on these two native roots.
        if ref is None and node["tag"] in {"html", "head"}:
            ref = "0" if node["tag"] == "html" else "1"
            matches = [n for n in originals if n["tag"] == node["tag"]]
            if len(matches) != 1 or matches[0]["id"] != ref:
                raise ValueError("Cannot infer unique original html/head reference")
            node["sourceId"] = ref
        if ref not in lookup or lookup[ref]["tag"] != node["tag"] or ref in seen:
            raise ValueError(f"Invalid/duplicate compressed reference: {ref}")
        seen.add(ref)
    expected = {record["id"] for record in source_map if record["disposition"] == "retained"}
    if expected != seen:
        raise ValueError("Emitted elements disagree with retained source-map inventory")


def build(run: Path = DEFAULT_RUN, output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    run_report = json.loads((run / "report.json").read_text())
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in run_report["results"]:
        grouped.setdefault(row["id"], []).append(row)
    if len(grouped) != run_report["uniqueDocumentCount"]:
        raise ValueError("Incomplete document inventory")
    documents = []
    exported: list[tuple[str, dict[str, Any]]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.abort())
        try:
            for document_id, rows in grouped.items():
                page = context.new_page()
                try:
                    first = rows[0]
                    source_bytes = verified_artifact(run, first["sourceArtifact"])
                    source = json.loads(page.evaluate(PARSE_TREE, {
                        "source": source_bytes.decode("utf-8"), "compressed": False, "marker": ""}))
                    label = LABELS.get(first["dataset"], first["dataset"])
                    if first["dataset"] == "ewh-dashboard":
                        label = "EWH Dashboard" if first["document"] == "dom" else "EWH Embedded frame"
                    data: dict[str, Any] = {"id": document_id, "label": label,
                        "dataset": first["dataset"], "document": first["document"],
                        "source": source, "profiles": {}}
                    for row in rows:
                        if row["sourceSha256"] != first["sourceSha256"]:
                            raise ValueError("Profiles have different source snapshots")
                        verified_artifact(run, row["sourceArtifact"])
                        # Verify every recorded artifact, including the exact organizer request.
                        artifacts = {key: verified_artifact(run, entry)
                                     for key, entry in row["artifacts"].items()}
                        tree = json.loads(page.evaluate(PARSE_TREE, {
                            "source": artifacts["html"].decode("utf-8"), "compressed": True,
                            "marker": row["referenceAttribute"]}))
                        source_map = json.loads(artifacts["sourceMap"])
                        validate_mapping(source, tree, source_map, row)
                        data["profiles"][row["profile"]] = {
                            "tree": tree, "sourceMap": source_map, "report": row}
                    budget = next(row for row in rows if row["profile"] == "budget")
                    entry = {key: budget[key] for key in (
                        "sourceElements", "outputElements", "nodeRatio", "sourceBytes", "outputBytes",
                        "passed", "checks", "sourceRoundTripStable", "nodeBudgetMet")}
                    entry.update(id=document_id, label=label, file=f"{document_id}.json",
                                 profiles=list(data["profiles"]))
                    documents.append(entry)
                    exported.append((entry["file"], data))
                finally:
                    page.close()
        finally:
            context.close()
            browser.close()
    # Write only after the whole corpus verifies, so failures do not publish partial results.
    output.mkdir(parents=True, exist_ok=True)
    for filename, data in exported:
        (output / filename).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    catalog = {"documents": documents, "createdAt": run_report["createdAt"],
               "measurement": run_report["measurement"],
               "limitations": ["Saved HTML parsed inertly; no original page scripts or network requests run.",
                   "Direct text and attributes remain local and are displayed as text, never executed.",
                   "Template children use a logical template parent for browsing."]}
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2))
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build(args.run, args.output)
    print(f"Exported {len(result['documents'])} verified documents to {args.output}")
