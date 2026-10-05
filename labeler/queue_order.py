"""Build runs/corpus/queue.json: the fixed order in which corpus pages are offered for labeling.

Rule (docs/design/gold-labeling-tool-v0.md, "Queue order"): pages are split into the pro group
(listed in pro-pages.json) and the main group. Within each group, pass 1 takes one page from every
site, cycling through categories (one site from category A, then B, then C, ..., then back to A);
pass 2 repeats with each site's second page, and so on. Categories, sites within a category and
pages within a site are shuffled with a fixed seed, so the same corpus and seed give the same order.

Only desktop states (state-000) with all six capture files are eligible. Pages listed in
runs/corpus/excluded.json (written by the labeler's corpus check) are left out of the order and
listed under "excluded", so a later re-check still covers them.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "runs/corpus"
SEED = 20261004
STATE = "state-000"
CAPTURE_FILES = ("capture.json", "environment.json", "document.html", "geometry.json",
                 "compression/document-00000.html", "compression/document-00000.source-map.json")
RULE = ("one page per site first, round-robin by category; seeded shuffle of categories, "
        "sites within a category and pages within a site")


def round_robin(pages, seed):
    """Order page records by the queue rule. Each record needs 'page', 'site' and 'category'."""
    rng = random.Random(seed)
    by_category = defaultdict(lambda: defaultdict(list))
    for record in sorted(pages, key=lambda r: r["page"]):
        by_category[record["category"]][record["site"]].append(record)
    categories = sorted(by_category)
    rng.shuffle(categories)
    # Per category: its sites in shuffled order, each with its pages in shuffled order.
    lanes = {}
    for category in categories:
        sites = sorted(by_category[category])
        rng.shuffle(sites)
        for site in sites:
            rng.shuffle(by_category[category][site])
        lanes[category] = [by_category[category][site] for site in sites]
    ordered, depth = [], 0
    while len(ordered) < len(pages):
        # One pass: the depth-th page of every site, taking one site per category per turn.
        cursors = {c: [s for s in lanes[c] if len(s) > depth] for c in categories}
        while any(cursors.values()):
            for category in categories:
                if cursors[category]:
                    ordered.append(cursors[category].pop(0)[depth])
        depth += 1
    return ordered


def collect(corpus):
    """Eligible page records, pages that failed the corpus check, and skip counts by reason."""
    root = corpus / "public-research-v1/captures"
    excluded_path = corpus / "excluded.json"
    excluded = {e["page"]: e.get("error", "") for e in json.loads(excluded_path.read_text())["pages"]} \
        if excluded_path.exists() else {}
    pages, failed, skipped = [], [], defaultdict(int)
    for page_dir in sorted(p for p in root.glob("*/*") if p.is_dir()):
        page = f"{page_dir.parent.name}/{page_dir.name}"
        state = page_dir / STATE
        if not all((state / name).is_file() for name in CAPTURE_FILES):
            skipped["no complete desktop capture"] += 1
            continue
        if page in excluded:
            skipped["failed corpus check"] += 1
            failed.append({"page": page, "error": excluded[page]})
            continue
        record = json.loads((state / "capture.json").read_text())["record"]
        pages.append({"page": page, "site": page_dir.parent.name, "site_id": record.get("site_id"),
                      "url": record.get("url"), "category": record.get("category") or "Uncategorized"})
    return pages, failed, dict(skipped)


def build(corpus=CORPUS, seed=SEED):
    pages, failed, skipped = collect(corpus)
    pro = set(json.loads((corpus / "pro-pages.json").read_text()))
    groups = {"pro": [p for p in pages if p["page"] in pro], "main": [p for p in pages if p["page"] not in pro]}
    queue = {"version": 1, "seed": seed, "state": STATE, "rule": RULE, "skipped": skipped,
             "groups": {name: [{**r, "order": i + 1} for i, r in enumerate(round_robin(group, seed))]
                        for name, group in groups.items()},
             # Kept so a re-run of the corpus check covers them too.
             "excluded": failed}
    (corpus / "queue.json").write_text(json.dumps(queue, indent=1))
    return queue


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    queue = build(args.corpus, args.seed)
    counts = {name: len(group) for name, group in queue["groups"].items()}
    print(f"Wrote {args.corpus / 'queue.json'}: {counts}; skipped {queue['skipped']}")


if __name__ == "__main__":
    main()
