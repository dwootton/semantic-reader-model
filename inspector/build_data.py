"""Export existing local captures; never executes or fetches source pages."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "data"


def read(path):
    return json.loads(path.read_text())


def variant(source):
    result = {"rootId": source.get("root_id", source.get("meta", {}).get("root_id")), "nodes": []}
    for node in source["nodes"]:
        item = {key: node.get(key, default) for key, default in (
            ("id", ""), ("kind", "group"), ("label", ""), ("summary", ""),
            ("children", []), ("origin", "unspecified"))}
        item["sourceRefs"] = list(node.get("source_refs", []))
        for key in ("notes", "reading_text", "display_role", "label_origin"):
            if key in node:
                item[key] = node[key]
        result["nodes"].append(item)
    return result


def dom(source):
    nodes = []
    for raw in source.get("elements", source.get("nodes", [])):
        inert = raw["tag"].lower() in {"script", "style"}
        node = {"id": raw["id"], "parent": raw.get("parent"),
                "children": raw.get("children", []), "tag": raw["tag"],
                "text": "" if inert else raw.get("text", ""),
                "ownText": "" if inert else raw.get("own_text", ""),
                "attributes": raw.get("attributes", {}),
                "cssPath": raw.get("css_path", "")}
        for old, new in (("document", "document"), ("xpath", "xpath"),
                         ("source_line", "sourceLine"), ("rect", "rect"),
                         ("text_truncated", "textTruncated")):
            if old in raw:
                node[new] = raw[old]
        if "own_text" not in raw:
            node["ownTextAvailable"] = False
        computed = raw.get("computed", {})
        node["hidden"] = bool(raw.get("hidden_attribute_ancestor") or raw.get("hidden_evidence")
                              or computed.get("display") == "none" or computed.get("visibility") == "hidden")
        if raw.get("classes") and "class" not in node["attributes"]:
            node["attributes"] = {**node["attributes"], "class": raw["classes"]}
        nodes.append(node)
    return {"roots": [n["id"] for n in nodes if n["parent"] is None], "nodes": nodes}


def validate(dataset):
    """Fail on missing evidence, inconsistent edges, duplicate IDs, or cycles."""
    nodes = dataset["dom"]["nodes"]
    lookup = {n["id"]: n for n in nodes}
    assert len(nodes) == len(lookup), "duplicate DOM IDs"
    for n in nodes:
        if n["parent"] is not None:
            assert n["parent"] in lookup, f"missing parent {n['parent']}"
            assert n["id"] in lookup[n["parent"]]["children"], f"nonreciprocal parent {n['id']}"
        for c in n["children"]:
            assert c in lookup, f"missing DOM child {c}"
            assert lookup[c]["parent"] == n["id"], f"nonreciprocal child {c}"
    def walk(items, roots):
        reached, active = set(), set()
        def visit(key):
            assert key not in active, f"cycle at {key}"
            if key in reached:
                return
            active.add(key)
            for child in items[key]["children"]:
                assert child in items, f"missing hierarchy child {child}"
                visit(child)
            active.remove(key)
            reached.add(key)
        for root in roots:
            assert root in items, f"missing root {root}"
            visit(root)
        assert reached == set(items), f"unreachable nodes: {set(items) - reached}"
    walk(lookup, dataset["dom"]["roots"])
    refs = 0
    for name, tree in dataset["variants"].items():
        indexed = {n["id"]: n for n in tree["nodes"]}
        assert len(indexed) == len(tree["nodes"]), f"duplicate hierarchy IDs in {name}"
        walk(indexed, [tree["rootId"]])
        for node in tree["nodes"]:
            for ref in node["sourceRefs"]:
                assert ref in lookup, f"{name}/{node['id']}: dangling source reference {ref}"
                refs += 1
    return refs


def build(output=OUT):
    output.mkdir(parents=True, exist_ok=True)
    datasets = []
    study = ROOT / "examples/vision-study"
    for directory in sorted((study / "sites").iterdir()):
        if not (directory / "baseline.json").exists():
            continue
        capture_dir = study / "captures" / directory.name
        capture = read(capture_dir / "capture.json")
        view = capture["viewport"]
        image = capture_dir / "viewport.png"
        assert image.read_bytes()[:3] == b"\xff\xd8\xff", f"Unexpected screenshot format: {image}"
        shutil.copyfile(image, output / f"{directory.name}.jpg")
        datasets.append({"id": directory.name, "label": capture["title"], "url": capture["url"],
                         "variants": {v: variant(read(directory / f"{v}.json")) for v in ("baseline", "revised")},
                         "dom": dom(capture), "screenshot": {"url": f"data/{directory.name}.jpg",
                         **{k: view[k] for k in ("width", "height", "scrollX", "scrollY")}},
                         "captureTime": capture.get("started_at"),
                         "limitations": ["Screenshot and DOM were captured sequentially; dynamic page changes may cause alignment differences.",
                                          "Only the first viewport screenshot is registered to these coordinates."]})
    for id_, label, sources in (
        ("ewh-dashboard", "Google Cloud dashboard", {"baseline": "hierarchy.json", "revised": "reader-alternative.json"}),
        ("nyt-homepage", "The New York Times homepage", {"revised": "hierarchy.json"})):
        directory = ROOT / "examples" / id_
        index = read(directory / "dom-index.json")
        datasets.append({"id": id_, "label": label, "url": "",
                         "variants": {v: variant(read(directory / file)) for v, file in sources.items()},
                         "dom": dom(index), "screenshot": None, "documents": index.get("documents", []),
                         "limitations": index.get("limitations", [])})
    catalog = []
    checked = 0
    for dataset in datasets:
        try:
            checked += validate(dataset)
        except AssertionError as error:
            raise ValueError(f"{dataset['id']}: {error}") from error
        (output / f"{dataset['id']}.json").write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")))
        catalog.append({"id": dataset["id"], "label": dataset["label"], "url": dataset["url"],
                        "variants": [{"id": v, "label": "Original hierarchy" if v == "baseline" else "Revised hierarchy"}
                                     for v in dataset["variants"]],
                        "hasScreenshot": dataset["screenshot"] is not None, "domCount": len(dataset["dom"]["nodes"])})
    (output / "catalog.json").write_text(json.dumps({"datasets": catalog}, ensure_ascii=False, indent=2))
    print(f"Exported {len(datasets)} datasets; validated {checked} source references.")
    return datasets


if __name__ == "__main__":
    build()
