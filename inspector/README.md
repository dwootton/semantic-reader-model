# Semantic Inspector

A local two-pane inspector for semantic projections and their source trees. A clean checkout uses the synthetic demo from `python3 scripts/prepare_demo.py`; the original local research corpus contains 14 captured examples. The semantic hierarchy is on the left; the original captured DOM tree is on the right. A screenshot tab provides visual bounds for the 12 captures with registered first-viewport images.

## Open

To generate and compare **whole-page** and **region-composed** hierarchies on these captures, use the [interactive comparison test](COMPARISON.md).

```sh
python3 inspector/serve.py --port 8765
```

Visit [the inspector](http://127.0.0.1:8765/). It binds only to loopback and serves only this directory. No GCP resources, credentials, external scripts, or new dependencies are required. It does not execute the saved sites' JavaScript or perform their original actions.

## Explore

- Choose a capture and its original, revised, or condensed hierarchy (`?variant=condensed` in the URL selects it on load and the choice sticks while switching captures). NYT has revised and condensed only. Condensed hierarchies are the 2026-09-13 re-authoring described in [docs/research/condensed-hierarchies.md](../docs/research/condensed-hierarchies.md); rebuild them with `python3 scripts/condensed_hierarchies/build_all.py`.
- Local labeler examples also appear in the **Hierarchy** menu: **Labeler v1** and **Labeler v2** for Hacker News, MDN, and Smithsonian, and **Labeler v2** for IKEA. These saved model outputs use the same original DOM IDs and registered screenshots as the authored variants, so selection, reverse linking, and screenshot highlights work in the regular interface. [Open Hacker News with Labeler v2](http://127.0.0.1:8765/?site=hacker-news&variant=labeler-v2).
- Three held-out **SFT-109 test cases** (Ergo IRC landing page, Scribble.rs lobby configuration, DebOps service ports) show the [Qwen3.5-9B SFT-109 adapter](https://huggingface.co/Dwootton/semantic-reader-qwen3.5-9b-sft-109) output beside the silver teacher outline it was trained to imitate. [Open Scribble.rs with the model output](http://127.0.0.1:8765/?site=sft109-scribblers&variant=sft-109). The right pane is the original captured DOM; each outline reference was resolved through the recorded alias packet, compact source map, and capture geometry, so selection, reverse linking, and screenshot highlights work. These captures were media-suppressed, so the screenshot tab shows a wireframe drawn from captured element geometry and saved DOM text rather than pixels. Rebuild with `python3 scripts/build_sft109_qualitative.py` then `python3 inspector/build_data.py --import-datasets runs/sft-109-qualitative/datasets`; the case bundles under `runs/sft-109-qualitative/` combine the HF result files, the training workstation's readiness pairs, and the archived collection captures, and stay out of git.
- **Gold standard: hidden/shown** in the header controls whether authored gold-standard hierarchies appear in the Hierarchy menu, so you can review model output blind first. The choice is remembered in this browser; `?gold=1` or `?gold=0` in the URL overrides it for that visit ([Scribble.rs with gold shown](http://127.0.0.1:8765/?site=sft109-scribblers&variant=gold&gold=1)). The three SFT-109 cases carry a gold candidate authored on 2026-09-14 from the full captured DOM following [the labeler rubric](../docs/research/semantic-outline-labeler-rubric.md); it is AI-authored and awaits human review, and its source is `runs/sft-109-qualitative/gold/author_gold.py`. Datasets mark such variants with a `variantSettings` entry; the catalog carries it as `setting` on the variant.
- Switch the left pane between **Hierarchy** and **Raw DOM**. Each view keeps its own expansion state. A pinned hierarchy selection highlights all linked source nodes when switching to Raw DOM; selecting a raw node maps back to the hierarchy when switching back. Both raw-DOM panes match by the same original element ID, including nodes without semantic annotations.
- Hover over a node for a temporary cross-highlight. Click or press Enter/Space to pin the selection.
- Selecting a hierarchy node reveals and highlights its source DOM references. Turn off **Include child references** to restrict selection to the node's explicitly attached references.
- Selecting a DOM element reveals its matching hierarchy nodes. If no exact annotation exists, the nearest mapped DOM ancestor is shown with a dashed highlight and an explicit explanation.
- Search either tree by label/text or source ID. Selection reveals matching paths in the other pane and clears that pane's search so linked elements are not hidden by a filter.
- Open **Statistics** to compare structural size, depth, direct target coverage, and modeled navigation for the selected capture/variant. The same directly mapped targets are used for every navigation column; costs are estimates rather than observed screen-reader performance. Selected targets also show estimates in the footer. [Computed report and methodology](METRICS.md).
- Use **Expand all** to open every level of the semantic hierarchy or either raw DOM pane and clear that pane’s search. **Collapse** returns to the top-level groups.
- Toggle **Narration: off/on** in the header to hear the current node as you focus or select it in either tree. Speech includes text, role, depth, and expanded/collapsed state. Moving interrupts earlier speech; switching narration off stops it immediately. It starts off on reload. This is a speech preview over the saved tree, not a full screen reader. It uses the browser’s [speech synthesis](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis); audible output depends on browser voice support.
- Use the arrow keys, Home, and End inside each tree. Right skips descendants to the next element at the same or a higher level, continuing past the end of a sibling list. Left moves to the previous sibling. Down expands the current node if needed and enters its first child; on a leaf it uses the same forward fallback as Right. Up returns to its parent. At the end of the tree, focus stays put. Use disclosure buttons or Collapse to close branches.
- In Screenshot view, select a hierarchy node to see its saved bounds. Click a highlighted rectangle to select that DOM element. Off-viewport references remain available in the DOM tree.

The footer shows the selected relationship, references, source attributes, and locator. Original source IDs are scoped to each saved capture; they are not durable IDs for live pages.

## Refresh data

The commands below require the excluded local research captures and original example builders. They are not needed for the synthetic demo.

```sh
python3 inspector/build_data.py
```

The exporter adapts the two original examples and twelve-site vision study into one schema. It preserves IDs, multiple source references, available text, and frame roots. Script/style text is excluded. Screenshots are copied from the original registered viewport captures, with their actual JPEG extension. Static EWH and NYT captures have no registered screenshot or direct-text-node field.

When `runs/labeler-test/v1` or `v2` contains `SITE.hierarchy.json`, the exporter also imports those saved trees. To add or refresh them in an existing local export without rebuilding the captures:

```sh
python3 inspector/build_data.py --labeler-only
```

Use `--labeler-root PATH` for another directory with the same `v1`/`v2` layout, and `--output PATH` for another inspector data directory. `--import-datasets DIR` adds prebuilt dataset JSON/JPEG pairs (validated first) and replaces catalog entries with the same id. Imports validate capture identity, tree structure, and every source reference before writing. Existing variants, DOM, screenshots, and catalog metadata are retained; repeated imports update the same menu choices. Input trees must already use the original capture IDs; compact/parser references need an explicit mapping first. Imported variants retain a source file hash and scope. The saved runs and exported data remain excluded from git and from the separately reviewed public demo.

## Checks

```sh
python3 -m unittest discover -s inspector -p test_build_data.py -v
node --test inspector/model.test.mjs
node --test inspector/metrics.test.mjs
node inspector/build_metrics_report.mjs
node --check inspector/app.mjs
python3 -m py_compile inspector/serve.py inspector/build_data.py
```

Model tests exercise many-to-many references, descendant expansion, explicit ancestor fallback, separate document roots, filtering, screenshot clipping, and every exported variant. Export tests reject broken references and DOM structure.

## Limits

This is a capture inspector, not a live website proxy. Screenshots cover one saved viewport and may differ from geometry because the original captures were sequential/dynamic. No screenshot should be inferred for EWH or NYT. Source DOM inclusion, accessibility exposure, and visible bounds are different facts. Raw capture metadata can include session-specific chrome; keep this local unless a separately reviewed export is requested.

## Static Pages build

The published landing page opens the reviewed Banana Bread example by default and also lists the three SFT-109 test cases. Build into an empty directory with `python3 scripts/build_pages_demo.py --destination /tmp/semantic-pages`. The build includes only the static inspector assets and the reviewed datasets in `examples/`; it has no model runner or comparison API. Refresh a public dataset from the local export with `python3 scripts/build_pages_demo.py --prepare sft109-ergo sft109-scribblers sft109-debops`. Source exports are sanitized, so their metrics describe the published view.
