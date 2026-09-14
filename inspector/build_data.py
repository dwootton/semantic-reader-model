"""Export existing local captures; never executes or fetches source pages."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "data"
LABELER_ROOT = ROOT / "runs/labeler-test"
VARIANT_LABELS = {"baseline": "Original hierarchy", "revised": "Revised hierarchy",
                  "condensed": "Condensed hierarchy", "labeler-v1": "Labeler v1",
                  "labeler-v2": "Labeler v2", "sft-109": "Qwen3.5-9B SFT-109 output",
                  "silver-reference": "Silver reference (Gemini teacher)",
                  "gold": "Gold standard (authored, review pending)"}


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


def add_labeler_variants(dataset, labeler_root=LABELER_ROOT):
    """Import saved trees whose references already use this capture's IDs.

    Never interpret compact/parser IDs as capture IDs or silently drop references.
    Validate every candidate before changing the dataset.
    """
    imported = {}
    for version in ("v1", "v2"):
        path = labeler_root / version / f"{dataset['id']}.hierarchy.json"
        if not path.exists():
            continue
        source = read(path)
        if source.get("site_id") != dataset["id"]:
            raise ValueError(f"{path.name}: labeler tree belongs to another capture")
        tree = variant(source)
        if any(n["kind"] == "dom" and not n["sourceRefs"] for n in tree["nodes"]):
            raise ValueError(f"{path.name}: labeler reading unit has no source references")
        name = f"labeler-{version}"
        try:
            validate({**dataset, "variants": {name: tree}})
        except AssertionError as error:
            raise ValueError(f"{path.name}: {error}") from error
        tree["provenance"] = {"kind": "saved-labeler-output", "version": version,
                              "file": f"{version}/{path.name}",
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "method": source.get("method", ""),
                              "scope": source.get("scope", "")}
        imported[name] = tree
    dataset["variants"].update(imported)
    return list(imported)


def import_labeler_examples(output=OUT, labeler_root=LABELER_ROOT):
    """Add local labeler variants to an existing export, retaining its catalog."""
    catalog = read(output / "catalog.json")
    pending = []
    count = 0
    for entry in catalog["datasets"]:
        dataset = read(output / f"{entry['id']}.json")
        if dataset["id"] != entry["id"]:
            raise ValueError("Catalog and capture identity differ")
        names = add_labeler_variants(dataset, labeler_root)
        if not names:
            continue
        validate(dataset)
        entry["variants"] = [v for v in entry["variants"] if v["id"] not in names]
        entry["variants"].extend({"id": name, "label": VARIANT_LABELS[name]} for name in names)
        pending.append(dataset)
        count += len(names)
    # A bad tree must not leave earlier captures or the catalog partly imported.
    for dataset in pending:
        (output / f"{dataset['id']}.json").write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")))
    (output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
    print(f"Imported {count} labeler trees across {len(pending)} captures.")
    return pending


def import_datasets(output, source):
    """Add prebuilt datasets (for example scripts/build_sft109_qualitative.py) to an existing export.

    Every dataset is validated before anything is written; a screenshot must be a JPEG beside its JSON.
    Existing catalog entries with the same id are replaced; other captures are untouched.
    """
    catalog = read(output / "catalog.json")
    pending = []
    for path in sorted(Path(source).glob("*.json")):
        dataset = read(path)
        if dataset.get("id") != path.stem or not dataset.get("variants"):
            raise ValueError(f"{path.name}: dataset id must match the file name and include variants")
        try:
            validate(dataset)
        except AssertionError as error:
            raise ValueError(f"{path.name}: {error}") from error
        image = None
        if dataset.get("screenshot"):
            image = path.with_suffix(".jpg")
            if dataset["screenshot"]["url"] != f"data/{dataset['id']}.jpg" or image.read_bytes()[:3] != b"\xff\xd8\xff":
                raise ValueError(f"{path.name}: screenshot must be data/{dataset['id']}.jpg beside the dataset")
        labels, settings = dataset.get("variantLabels", {}), dataset.get("variantSettings", {})
        # A variant with a setting key stays out of the Hierarchy menu until that inspector setting is on.
        entry = {"id": dataset["id"], "label": dataset["label"], "url": dataset.get("url", ""),
                 "variants": [{"id": v, "label": labels.get(v, VARIANT_LABELS.get(v, v.title() + " hierarchy")),
                               **({"setting": settings[v]} if v in settings else {})}
                              for v in dataset["variants"]],
                 "hasScreenshot": dataset.get("screenshot") is not None, "domCount": len(dataset["dom"]["nodes"])}
        pending.append((dataset, image, entry))
    for dataset, image, entry in pending:
        if image is not None:
            shutil.copyfile(image, output / image.name)
        (output / f"{dataset['id']}.json").write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")))
        catalog["datasets"] = [e for e in catalog["datasets"] if e["id"] != entry["id"]] + [entry]
    (output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
    print(f"Imported {len(pending)} datasets into {output}.")
    return [d for d, _, _ in pending]


def build(output=OUT, labeler_root=LABELER_ROOT):
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
                         "variants": {v: variant(read(directory / f"{v}.json")) for v in ("baseline", "revised", "condensed")
                                      if (directory / f"{v}.json").exists()},
                         "dom": dom(capture), "screenshot": {"url": f"data/{directory.name}.jpg",
                         **{k: view[k] for k in ("width", "height", "scrollX", "scrollY")}},
                         "captureTime": capture.get("started_at"),
                         "limitations": ["Screenshot and DOM were captured sequentially; dynamic page changes may cause alignment differences.",
                                          "Only the first viewport screenshot is registered to these coordinates."]})
    for id_, label, sources in (
        ("ewh-dashboard", "Google Cloud dashboard", {"baseline": "hierarchy.json", "revised": "reader-alternative.json", "condensed": "condensed.json"}),
        ("nyt-homepage", "The New York Times homepage", {"revised": "hierarchy.json", "condensed": "condensed.json"})):
        directory = ROOT / "examples" / id_
        index = read(directory / "dom-index.json")
        datasets.append({"id": id_, "label": label, "url": "",
                         "variants": {v: variant(read(directory / file)) for v, file in sources.items()
                                      if (directory / file).exists()},
                         "dom": dom(index), "screenshot": None, "documents": index.get("documents", []),
                         "limitations": index.get("limitations", [])})
    catalog = []
    checked = 0
    for dataset in datasets:
        add_labeler_variants(dataset, labeler_root)
        try:
            checked += validate(dataset)
        except AssertionError as error:
            raise ValueError(f"{dataset['id']}: {error}") from error
        (output / f"{dataset['id']}.json").write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")))
        catalog.append({"id": dataset["id"], "label": dataset["label"], "url": dataset["url"],
                        "variants": [{"id": v, "label": VARIANT_LABELS.get(v, v.title() + " hierarchy")}
                                     for v in dataset["variants"]],
                        "hasScreenshot": dataset["screenshot"] is not None, "domCount": len(dataset["dom"]["nodes"])})
    (output / "catalog.json").write_text(json.dumps({"datasets": catalog}, ensure_ascii=False, indent=2))
    print(f"Exported {len(datasets)} datasets; validated {checked} source references.")
    return datasets


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--labeler-root", type=Path, default=LABELER_ROOT)
    parser.add_argument("--labeler-only", action="store_true",
                        help="Add saved labeler trees to the current export without rebuilding captures")
    parser.add_argument("--import-datasets", type=Path, metavar="DIR",
                        help="Add prebuilt dataset JSON/JPEG pairs from DIR to the current export")
    args = parser.parse_args()
    if args.import_datasets:
        import_datasets(args.output, args.import_datasets)
    elif args.labeler_only:
        import_labeler_examples(args.output, args.labeler_root)
    else:
        build(args.output, args.labeler_root)
