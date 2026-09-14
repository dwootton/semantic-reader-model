"""Build inspector datasets for the SFT-109 qualitative test cases published on Hugging Face.

Inputs live under runs/sft-109-qualitative/cases/<case-id>/:
  hf/        outline.json, generation.json, output.txt downloaded from the model repo
  pair/      navigation-packet.json, original-outline.json, source.html.txt, provenance.json,
             reference-crosswalk.json copied from the training workstation's readiness bundle
  evidence/  the original collection capture: document.html, geometry.json, environment.json,
             capture.json and compression/ (compact HTML plus its source map)

The saved HTML is parsed offline with the browser parser; no page script runs and no network
request is made. Model references are joined to source elements through recorded artifacts only.
Output datasets go to runs/sft-109-qualitative/datasets/ for `inspector/build_data.py --import-datasets`.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inspector"))
from build_data import validate, variant as to_variant  # noqa: E402

CASES = ROOT / "runs/sft-109-qualitative/cases"
OUT = ROOT / "runs/sft-109-qualitative/datasets"
TITLES = {
    "87342885f0259fefe617d934": "Ergo IRC landing page",
    "3033564736a8c09a9934fba7": "Scribble.rs lobby configuration",
    "12f3146b0d1e7461fa5a32aa": "DebOps service ports documentation",
}
# collection/state_capture.js assigns n-ids to these tags only after all other elements.
COLLECTOR_EXCLUDED = {"script", "style", "noscript", "template", "link", "meta", "base"}
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"

ENUMERATE_JS = r"""
(source) => {
  const doc = new DOMParser().parseFromString(source, 'text/html');
  const all = [...doc.querySelectorAll('*')];
  const index = new Map(all.map((el, i) => [el, i]));
  const KEEP = new Set(['id','role','name','type','title','href','src','alt','placeholder','tabindex','disabled',
    'checked','selected','hidden','value','for','aria-label','aria-labelledby','aria-describedby','aria-expanded',
    'aria-selected','aria-checked','aria-disabled','aria-hidden','aria-controls','aria-haspopup','aria-level',
    'aria-current','lang','class']);
  const SKIP = new Set(['script','style','noscript','template']);
  const norm = s => s.replace(/\s+/g, ' ').trim();
  const cssPath = el => { const parts = []; for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
    let k = 1; for (let s = e.previousElementSibling; s; s = s.previousElementSibling) if (s.localName === e.localName) k++;
    parts.push(`${e.localName}:nth-of-type(${k})`); } return parts.reverse().join(' > '); };
  return all.map((el, i) => {
    const attrs = {}; for (const a of el.attributes) if (KEEP.has(a.name)) attrs[a.name] = a.value.slice(0, 300);
    const own = norm([...el.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join(' '));
    const inert = SKIP.has(el.localName) || !!el.closest('script,style,noscript,template');
    const full = inert ? '' : norm(el.textContent);
    return { index: i, tag: el.localName, parent: el.parentElement ? index.get(el.parentElement) : null,
      children: [...el.children].map(c => index.get(c)), attributes: attrs,
      ownText: inert ? '' : own.slice(0, 600), text: full.slice(0, 1800), textTruncated: full.length > 1800,
      cssPath: cssPath(el), hidden: el.hasAttribute('hidden') || attrs['aria-hidden'] === 'true' };
  });
}
"""

# Mirrors ui_ir/dom/parse.mjs numbering: elements and text nodes in document order, ids from 1.
RECORDS_JS = r"""
(source) => {
  const doc = new DOMParser().parseFromString(source, 'text/html');
  const records = [{id: '0', kind: 'element', tag: '#document', parent: null, ref: null}];
  const stack = [...doc.childNodes].reverse().map(node => ({node, parent: '0'}));
  while (stack.length) {
    const {node, parent} = stack.pop();
    if (node.nodeType !== 1 && node.nodeType !== 3) continue;
    const record = {id: String(records.length), parent, kind: node.nodeType === 3 ? 'text' : 'element', ref: null};
    if (node.nodeType === 3) record.text = node.data;
    else { record.tag = node.localName.toLowerCase(); record.ref = node.getAttribute('data-r'); }
    records.push(record);
    const children = node.localName === 'template' ? node.content.childNodes : node.childNodes;
    for (let i = children.length - 1; i >= 0; i--) stack.push({node: children[i], parent: record.id});
  }
  return records;
}
"""


def b36(number):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if number == 0:
        return "0"
    out = ""
    while number:
        number, rem = divmod(number, 36)
        out = digits[rem] + out
    return out


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Browser:
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.runtime = sync_playwright().start()
        self.browser = self.runtime.chromium.launch(headless=True)
        context = self.browser.new_context(java_script_enabled=False, service_workers="block")
        context.route("**/*", lambda route: route.abort())
        self.page = context.new_page()
        return self

    def __exit__(self, *exc):
        self.browser.close()
        self.runtime.stop()

    def enumerate(self, html):
        return self.page.evaluate(ENUMERATE_JS, html)

    def records(self, html):
        return self.page.evaluate(RECORDS_JS, html)


def check_source_map(elements, source_map):
    if len(elements) != len(source_map):
        raise ValueError(f"element count {len(elements)} differs from compact source map {len(source_map)}")
    for i, (element, entry) in enumerate(zip(elements, source_map)):
        parent = None if entry["parent"] is None else int(entry["parent"], 36)
        if int(entry["id"], 36) != i or entry["tag"].lower() != element["tag"] or parent != element["parent"]:
            raise ValueError(f"compact source map diverges from parsed document at element {i}")


def collector_ids(elements):
    """Map the capture collector's n-ids to parsed element indexes (document order, excluded tags last)."""
    ordered = [e for e in elements if e["tag"] not in COLLECTOR_EXCLUDED] + \
              [e for e in elements if e["tag"] in COLLECTOR_EXCLUDED]
    return {f"n{i + 1}": e["index"] for i, e in enumerate(ordered)}


def alias_to_compact_ref(records, packet, crosswalk):
    """n-alias -> data-r reference through the recorded packet aliases and the reparsed compact HTML."""
    by_id = {r["id"]: r for r in records}

    def owning_ref(record):
        while record is not None:
            if record.get("ref"):
                return record["ref"]
            record = by_id.get(record["parent"]) if record["parent"] is not None else None
        return None
    mapping = {}
    for alias, source in packet["aliases"]["nodes"].items():
        document, record_id = source.split(":", 1)
        if document != "d0":
            raise ValueError(f"unexpected document namespace in alias {alias}: {source}")
        mapping[alias] = owning_ref(by_id[record_id])
    conflicts = [(ref, entry["refs"]) for ref, entry in crosswalk.items()
                 if entry.get("refs") and mapping.get(entry["refs"][0]) != ref]
    if conflicts:
        raise ValueError(f"alias mapping disagrees with recorded crosswalk: {conflicts[:5]}")
    return mapping


def build_dom(elements, source_map, geometry, n_index):
    ledger = {entry["id"]: entry for entry in source_map}
    rects = {}
    for row in geometry["elements_and_text"]:
        index = n_index.get(row.get("dom_id"))
        if index is not None and row.get("bounds"):
            x, y, w, h = row["bounds"]
            rects[index] = {"x": x, "y": y, "width": w, "height": h}
    nodes = []
    for e in elements:
        key = b36(e["index"])
        node = {"id": f"src-{key}", "parent": None if e["parent"] is None else f"src-{b36(e['parent'])}",
                "children": [f"src-{b36(c)}" for c in e["children"]], "tag": e["tag"],
                "text": e["text"], "ownText": e["ownText"], "textTruncated": e["textTruncated"],
                "attributes": e["attributes"], "cssPath": e["cssPath"], "hidden": e["hidden"]}
        entry = ledger[key]
        node["compact"] = {"disposition": entry["disposition"],
                           "ref": f"d0:{key}" if entry.get("representedBy") == key else None}
        if e["index"] in rects:
            node["rect"] = rects[e["index"]]
        nodes.append(node)
    return {"roots": [n["id"] for n in nodes if n["parent"] is None], "nodes": nodes}, len(rects)


def outline_tree(outline, prefix, origin, label_origin, resolve, dom_nodes, body_id):
    """Depth-indented outline -> labeler-style tree; unresolvable refs become annotated groups."""
    lookup = {n["id"]: n for n in dom_nodes}
    nodes, stack, unmapped = [], [], []
    for i, line in enumerate(outline):
        node_id = f"{prefix}{i}"
        refs, missing = [], []
        for ref in line["refs"]:
            target = resolve(ref)
            (refs if target in lookup else missing).append(target or ref)
        unmapped.extend((node_id, m) for m in missing)
        node = {"id": node_id, "label": line["label"], "children": [], "origin": origin,
                "label_origin": label_origin, "outline_refs": list(line["refs"])}
        if refs:
            targets = [lookup[r] for r in refs]
            node.update(kind="dom", source_refs=refs,
                        summary=", ".join(f"<{t['tag']}>" for t in targets)[:200],
                        reading_text=" ".join(t["text"] for t in targets if t["text"])[:400],
                        display_role=targets[0]["attributes"].get("role") or targets[0]["tag"])
        else:
            node.update(kind="group", source_refs=[body_id] if i == 0 else [], summary="")
        if missing:
            node["notes"] = "Unresolved model references kept for review: " + ", ".join(missing)
        while stack and stack[-1][0] >= line["depth"]:
            stack.pop()
        if stack:
            nodes[stack[-1][1]]["children"].append(node_id)
        elif i:
            nodes[0]["children"].append(node_id)  # tolerate a second depth-0 line
        stack.append((line["depth"], i))
        nodes.append(node)
    return {"root_id": f"{prefix}0", "nodes": nodes}, unmapped


def wireframe(dom, geometry, elements, n_index, viewport, destination):
    """Draw captured element boxes and DOM text at captured text positions; no pixel screenshot exists."""
    from PIL import Image, ImageDraw, ImageFont
    by_index = {e["index"]: e for e in elements}
    rows = [r for r in geometry["elements_and_text"] if r.get("dom_id") in n_index and r.get("bounds")]
    bottom = max([r["bounds"][1] + r["bounds"][3] for r in rows if r["bounds"][2] > 0] + [viewport["height"]])
    width, height = viewport["width"], int(min(max(math.ceil(bottom), viewport["height"]), 4000))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    palette = {"a": "#2b6cb0", "button": "#444444", "input": "#444444", "select": "#444444", "textarea": "#444444",
               "img": "#bbbbbb", "svg": "#bbbbbb", "nav": "#9ab", "header": "#9ab", "footer": "#9ab", "main": "#9ab",
               "section": "#9ab", "table": "#a88", "tr": "#caa", "td": "#dcc", "th": "#caa"}
    sizes = {}
    for row in sorted(rows, key=lambda r: -(r["bounds"][2] * r["bounds"][3])):
        x, y, w, h = row["bounds"]
        tag = by_index[n_index[row["dom_id"]]]["tag"]
        size = row.get("styles", {}).get("font-size", "16px")
        sizes[row["dom_id"]] = max(9, min(30, int(float(size.rstrip("px") or 16)))) if size.endswith("px") else 14
        if w <= 0 or h <= 0 or tag in {"html", "body", "head"}:
            continue
        color = palette.get(tag, "#e4e4e4")
        if tag in {"img", "svg"}:
            draw.rectangle([x, y, x + w, y + h], fill="#eeeeee", outline=color)
        elif tag in {"button", "input", "select", "textarea"}:
            draw.rectangle([x, y, x + w, y + h], fill="#f2f4ff", outline=color, width=2)
        else:
            draw.rectangle([x, y, x + w, y + h], outline=color)
    boxes = {}
    for box in geometry.get("text_boxes", []):
        if box.get("text_parent_dom_id") in n_index and box.get("bounds"):
            boxes.setdefault(box["text_parent_dom_id"], []).append(box)
    for dom_id, group in boxes.items():
        element = by_index[n_index[dom_id]]
        words = (element["ownText"] or element["text"]).split()
        if not words:
            continue
        size = sizes.get(dom_id, 14)
        try:
            font = ImageFont.truetype(FONT, size)
        except OSError:
            font = ImageFont.load_default(size=size)
        fill = "#2b6cb0" if element["tag"] == "a" else "#222222"
        for box in sorted(group, key=lambda b: (b["bounds"][1], b["bounds"][0])):
            x, y, w, h = box["bounds"]
            line = ""
            while words:
                candidate = (line + " " + words[0]).strip()
                if line and font.getlength(candidate) > w:
                    break
                line = candidate
                words.pop(0)
            if line:
                draw.text((x, y), line, fill=fill, font=font)
            if not words:
                break
    image.save(destination, "JPEG", quality=85)
    return {"width": width, "height": height}


def build_case(browser, case_dir):
    case_id = case_dir.name
    slug = (case_dir / "slug").read_text().strip()
    evidence, pair, hf = case_dir / "evidence", case_dir / "pair", case_dir / "hf"
    capture = read(evidence / "capture.json")
    environment = read(evidence / "environment.json")
    source_map = read(evidence / "compression/document-00000.source-map.json")
    geometry = read(evidence / "geometry.json")
    packet = read(pair / "navigation-packet.json")
    crosswalk = read(pair / "reference-crosswalk.json")
    provenance = read(pair / "provenance.json")
    document_html = (evidence / "document.html").read_text(encoding="utf-8")
    if sha(evidence / "document.html") != capture["documents"][0]["sha256"]:
        raise ValueError(f"{case_id}: saved document hash differs from capture manifest")
    compact_html = (pair / "source.html.txt").read_text(encoding="utf-8")
    stripped = compact_html.replace('data-r="d0:', 'data-r="').replace('data-target-ref="d0:', 'data-target-ref="')
    if stripped != (evidence / "compression/document-00000.html").read_text(encoding="utf-8"):
        raise ValueError(f"{case_id}: model input HTML is not the capture's compact output")

    elements = browser.enumerate(document_html)
    check_source_map(elements, source_map)
    n_index = collector_ids(elements)
    dom, rect_count = build_dom(elements, source_map, geometry, n_index)
    aliases = alias_to_compact_ref(browser.records(compact_html), packet, crosswalk)

    def resolve(ref):
        compact = aliases.get(ref) if ref.startswith("n") else ref
        if compact and compact.startswith("d0:"):
            return f"src-{compact[3:]}"
        return None
    body_id = next(n["id"] for n in dom["nodes"] if n["tag"] == "body")
    model_outline = read(hf / "outline.json")
    reference_outline = read(pair / "original-outline.json")
    model_tree, model_unmapped = outline_tree(model_outline["outline"], "sft-", "model", "model", resolve, dom["nodes"], body_id)
    reference_tree, reference_unmapped = outline_tree(reference_outline["outline"], "ref-", "teacher", "teacher", resolve, dom["nodes"], body_id)
    generation = read(hf / "generation.json")
    hf_source = read(CASES.parent / "hf-source.json")
    variants = {
        "sft-109": {**to_variant(model_tree), "provenance": {
            "kind": "hf-qualitative-output", "repo": hf_source["repo"], "revision": hf_source["revision"],
            "file": f"{hf_source['path']}/{case_id}/outline.json", "sha256": sha(hf / "outline.json"),
            "generation": generation, "page": model_outline["page"], "scope": model_outline["scope"],
            "needs_expansion": model_outline["needs_expansion"], "unmapped_refs": model_unmapped,
            "method": "Greedy BF16 generation with the SFT-109 LoRA adapter; references resolved through the recorded alias packet"}},
        "silver-reference": {**to_variant(reference_tree), "provenance": {
            "kind": "silver-reference-outline", "source": provenance["source"], "logical_path": provenance["logical_path"],
            "artifact_sha256": provenance["artifact_sha256"], "sha256": sha(pair / "original-outline.json"),
            "labeler": "Gemini teacher pipeline (automated silver label, human review pending)",
            "page": reference_outline["page"], "scope": reference_outline["scope"], "unmapped_refs": reference_unmapped}},
    }
    gold_path = CASES.parent / "gold" / f"{case_id}.json"
    if gold_path.exists():
        gold = read(gold_path)
        variants["gold"] = {**to_variant(gold), "provenance": {
            "kind": "authored-gold-candidate", "authored_at": gold.get("authored_at"), "authored_by": gold.get("authored_by"),
            "method": gold.get("method"), "scope": gold.get("scope"), "sha256": sha(gold_path),
            "rubric": "docs/research/semantic-outline-labeler-rubric.md",
            "review_status": "AI-authored from the full captured DOM; human review pending"}}
    dataset_id = f"sft109-{slug}"
    OUT.mkdir(parents=True, exist_ok=True)
    image = wireframe(dom, geometry, elements, n_index, environment["viewport"], OUT / f"{dataset_id}.jpg")
    dataset = {
        "id": dataset_id, "label": f"{TITLES.get(case_id, slug)} · SFT-109 test case", "url": capture["final_url"],
        "variants": variants, "dom": dom,
        "screenshot": {"url": f"data/{dataset_id}.jpg", **image, "scrollX": 0, "scrollY": 0,
                       "kind": "wireframe", "note": "Wireframe drawn from captured element geometry and saved DOM text; the media-suppressed capture recorded no pixel screenshot."},
        "captureTime": capture["captured_at"],
        "limitations": [
            "Held-out SFT test page: the model saw only the compact HTML shown as compact refs, never the full DOM or a screenshot.",
            "No pixel screenshot exists for this media-suppressed capture; the screenshot pane is a wireframe from captured geometry and saved DOM text.",
            "Element boxes come from the live capture geometry; elements without recorded geometry have no box.",
            "Silver reference outline is an automated teacher label, not human gold.",
            "Gold standard hierarchy was authored from the full captured DOM on 2026-09-14 following the labeler rubric and awaits human review; it is hidden until the Gold standard setting is on.",
        ],
        "provenance": {"case_id": case_id, "capture": {"url": capture["final_url"], "captured_at": capture["captured_at"],
                                                      "document_sha256": capture["documents"][0]["sha256"],
                                                      "viewport": environment["viewport"], "browser": environment.get("browser_version")},
                       "compact_source_map_sha256": sha(evidence / "compression/document-00000.source-map.json"),
                       "packet_hash": packet["packetHash"], "collector_id_scheme": "document order, script/style/noscript/template/link/meta/base last",
                       "geometry_elements": rect_count, "source_elements": len(elements)},
        "variantLabels": {"sft-109": "Qwen3.5-9B SFT-109 output", "silver-reference": "Silver reference (Gemini teacher)",
                          "gold": "Gold standard (authored, review pending)"},
        # Variants carrying a setting key are listed only when that inspector setting is switched on.
        "variantSettings": {"gold": "gold"},
    }
    validate(dataset)
    (OUT / f"{dataset_id}.json").write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")))
    model_units = [n for n in model_tree["nodes"] if n["kind"] == "dom"]
    print(f"{dataset_id:18s} elements={len(elements):4d} geometry={rect_count:4d} model_units={len(model_units):3d} "
          f"model_unmapped={len(model_unmapped)} reference_unmapped={len(reference_unmapped)} image={image['width']}x{image['height']}")
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    args = parser.parse_args()
    with Browser() as browser:
        for case_dir in sorted(p for p in args.cases.iterdir() if p.is_dir()):
            build_case(browser, case_dir)


if __name__ == "__main__":
    main()
