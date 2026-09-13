"""Audit compression/recovery on unique saved documents without loading them live."""

import argparse
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROFILES = ("conservative", "wrappers")


def inventory():
    """Include missing sources and duplicate aliases in the inventory for auditing."""
    candidates = []
    captures = ROOT / "examples/vision-study/captures"
    for directory in sorted(captures.iterdir()):
        if directory.is_dir():
            item = {"dataset": directory.name, "document": "page",
                    "path": str(directory / "page.html")}
            try:
                capture = json.loads((directory / "capture.json").read_text())
                item["indexedSha256"] = capture.get("source_sha256")
            except (OSError, ValueError):
                # The per-document metadata load reports the concrete failure later.
                pass
            candidates.append(item)
    for dataset in ("ewh-dashboard", "nyt-homepage"):
        index_path = ROOT / "examples" / dataset / "dom-index.json"
        try:
            index = json.loads(index_path.read_text())
            for document in index["documents"]:
                candidates.append({"dataset": dataset, "document": document["id"],
                                   "path": document["path"],
                                   "indexedSha256": document.get("sha256")})
        except (OSError, ValueError, KeyError) as error:
            candidates.append({"dataset": dataset, "document": "index",
                               "path": str(index_path), "status": "skipped",
                               "reason": f"Cannot read document inventory: {error}"})
    seen_paths, seen_hashes = {}, {}
    for item in candidates:
        item["id"] = f"{item['dataset']}--{item['document']}"
        if item.get("status") == "skipped":
            continue
        path = Path(item["path"]).resolve()
        item["path"] = str(path)
        try:
            data = path.read_bytes()
            # Reject undecodable captures rather than silently replacing evidence.
            data.decode("utf-8")
        except (OSError, UnicodeError) as error:
            item.update(status="skipped", reason=str(error))
            continue
        digest = hashlib.sha256(data).hexdigest()
        item.update(sourceSha256=digest, sourceBytes=len(data))
        if item.get("indexedSha256"):
            item["matchesIndexedSha256"] = digest == item["indexedSha256"]
            if not item["matchesIndexedSha256"]:
                item.update(status="skipped", reason="Source hash does not match indexed metadata")
                continue
        duplicate = seen_paths.get(str(path)) or seen_hashes.get(digest)
        if duplicate:
            item.update(status="duplicate", duplicateOf=duplicate)
        else:
            item["status"] = "ready"
            seen_paths[str(path)] = seen_hashes[digest] = item["id"]
    return candidates


def summarize(results):
    summaries = {}
    for profile in PROFILES:
        rows = [row for row in results if row["profile"] == profile]
        measured = [row for row in rows if row["status"] == "passed" and "compressedBytes" in row]
        reductions = [1 - row["compressedBytes"] / row["sourceBytes"]
                      for row in measured if row["sourceBytes"]]
        summaries[profile] = {
            "attempted": len(rows),
            "passed": sum(row["status"] == "passed" for row in rows),
            "failed": sum(row["status"] == "failed" for row in rows),
            "byteSummaryScope": "Passing DOM audits only; excludes invalid candidates",
            "rawSourceBytes": sum(row["sourceBytes"] for row in measured),
            "compressedBytes": sum(row["compressedBytes"] for row in measured),
            "localPatchBytes": sum(row["patchBytes"] for row in measured),
            "medianByteReductionAgainstRaw": statistics.median(reductions) if reductions else None,
            "metadataMatched": sum(row.get("metadataJoin", {}).get("matched", 0) for row in rows),
            "metadataFailed": sum(row.get("metadataJoin", {}).get("failed", 0) for row in rows),
            "metadataSummaryScope": "All completed candidates, including failed DOM audits",
            "sourceElements": sum(row["sourceElements"] for row in measured),
            "retainedElements": sum(row["retainedElements"] for row in measured),
            "collapsedElements": sum(row["collapsedElements"] for row in measured),
            "recoveredElements": sum(row["recoveredElements"] for row in measured),
            "minimumContentRetention": min((row["contentRetention"] for row in measured), default=None),
        }
    return summaries


def load_metadata(item):
    if item["dataset"] in ("ewh-dashboard", "nyt-homepage"):
        path = ROOT / "examples" / item["dataset"] / "dom-index.json"
        nodes = [node for node in json.loads(path.read_text())["nodes"]
                 if node["document"] == item["document"]]
    else:
        path = Path(item["path"]).with_name("capture.json")
        nodes = json.loads(path.read_text())["elements"]
    return [{key: node[key] for key in ("id", "css_path", "tag")} for node in nodes]


def markdown(report):
    lines = ["# Local DOM compression and recovery", "",
             f"Inventory: {report['datasetCount']} datasets, {len(report['inventory'])} documents; "
             f"{report['uniqueDocumentCount']} unique readable documents tested.", "",
             "Sizes are UTF-8 bytes, not model tokens. Compressed HTML is the model payload; "
             "the recovery patch stays local. Recovery uses that patch and is not evidence "
             "that the compressed HTML alone can recreate removed nodes. "
             "Organizer/model quality and rendered appearance were not tested.", "",
             "| Document | Profile | Raw bytes | Sent bytes | Saved | Retained / source elements | "
             "Collapsed | Recovered | Audit | Metadata IDs matched |", "|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for row in report["results"]:
        if "compressedBytes" not in row:
            lines.append(f"| {row['id']} | {row['profile']} | {row['sourceBytes']} | — | — | — | — | — | failed | — |")
            continue
        reduction = 1 - row["compressedBytes"] / row["sourceBytes"] if row["sourceBytes"] else 0
        recovered = row.get("recoveredElements")
        recovered_text = f"{recovered:,}" if recovered is not None else "—"
        joined = row.get("metadataJoin", {})
        lines.append(f"| {row['id']} | {row['profile']} | {row['sourceBytes']:,} | "
                     f"{row['compressedBytes']:,} | {reduction:.1%} | "
                     f"{row['retainedElements']:,} / {row['sourceElements']:,} | "
                     f"{row['collapsedElements']:,} | {recovered_text} | {row['status']} | "
                     f"{joined.get('matched', 0)} / {joined.get('total', 0)} |")
    notices = [f"- {item['id']}: {item['status']} — "
               f"{item.get('reason', 'same source as ' + item.get('duplicateOf', ''))}"
               for item in report["inventory"] if item["status"] != "ready"]
    notices.extend(f"- {row['id']} ({row['profile']}): {row['error']}"
                   for row in report["results"] if row.get("error"))
    if notices:
        lines.extend(["", "Inventory omissions and errors:", "", *notices])
    lines.extend(["", "See report.json for source hashes, exact preservation checks, "
                  "local patch sizes, and per-profile summaries.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "runs/compression/local-recovery")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    documents = inventory()
    results = []
    compressor_source = (HERE / "recovery.js").read_bytes()
    compressor_sha = hashlib.sha256(compressor_source).hexdigest()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser_version = browser.version
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.abort())
        try:
            for item in documents:
                if item["status"] != "ready":
                    continue
                for profile in PROFILES:
                    row = {"id": item["id"], "dataset": item["dataset"],
                           "document": item["document"], "sourcePath": item["path"],
                           "sourceSha256": item["sourceSha256"],
                           "sourceBytes": item["sourceBytes"], "profile": profile}
                    page = None
                    try:
                        source = Path(item["path"]).read_bytes()
                        if hashlib.sha256(source).hexdigest() != item["sourceSha256"]:
                            raise ValueError("Source changed after inventory")
                        page = context.new_page()
                        page.goto("about:blank")
                        page.add_script_tag(content=compressor_source.decode("utf-8"))
                        # JSON avoids Playwright's recursive object serializer overflowing
                        # on deeply nested saved application DOMs such as EWH.
                        result = json.loads(page.evaluate(
                            "x => JSON.stringify(runRecoveryExperiment(x.source, x.profile, x.metadata))",
                            {"source": source.decode("utf-8"), "profile": profile,
                             "metadata": load_metadata(item)}))
                        stem = f"{item['id']}--{profile}"
                        html_path = output / f"{stem}.html"
                        patch_path = output / f"{stem}.patch.json"
                        html_path.write_text(result["html"], encoding="utf-8")
                        patch_path.write_text(json.dumps(result["patch"], ensure_ascii=False,
                                                         separators=(",", ":")), encoding="utf-8")
                        mapping_path = output / f"{stem}.mapping.json"
                        mapping_path.write_text(json.dumps(result["sourceMatches"],
                                                          ensure_ascii=False, indent=2) + "\n")
                        row.update(result["report"])
                        joined = row.get("metadataJoin", {})
                        row["mappingStatus"] = "complete" if joined.get("failed") == 0 else "incomplete"
                        row.update(status="passed" if result["report"]["passed"] else "failed",
                                   htmlFile=html_path.name, patchFile=patch_path.name,
                                   mappingFile=mapping_path.name,
                                   patchArtifactBytes=patch_path.stat().st_size)
                    except Exception as error:  # Preserve evidence from other documents on failure.
                        row.update(status="failed", error=f"{type(error).__name__}: {error}")
                    finally:
                        if page is not None:
                            page.close()
                    results.append(row)
                    print(f"{row['id']} {profile}: {row['status']}", flush=True)
        finally:
            browser.close()
    report = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "compressorSha256": compressor_sha, "browserVersion": browser_version,
        "datasetCount": len({item["dataset"] for item in documents}),
        "uniqueDocumentCount": sum(item["status"] == "ready" for item in documents),
        "measurement": "UTF-8 bytes; not tokens; no organizer/model quality evaluation",
        "recovery": "Compressed HTML plus a local-only recovery patch",
        "inventory": documents, "results": results, "profiles": summarize(results),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "report.md").write_text(markdown(report))
    print(f"Report: {output / 'report.md'}")
    return int(any(row["status"] == "failed" for row in results)
               or any(item["status"] == "skipped" for item in documents))


if __name__ == "__main__":
    raise SystemExit(main())
