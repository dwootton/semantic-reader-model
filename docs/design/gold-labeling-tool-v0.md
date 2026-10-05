# Gold labeling tool, v0

Design status: draft for discussion, 4 October 2026. Nothing here is implemented.

## Goal

Make producing a banana-bread-quality example (`examples/banana-bread/allrecipes.json`) a sitting of minutes, not an afternoon of hand-written JSON. A person picks the next capture, builds one semantic tree whose depth is the zoom level, and submits a validated variant that the existing inspector, metrics and training export already understand.

The labeler always starts from the compressed DOM and always finishes in the same editor. Two ways to change the tree, freely mixed:

- **Manual:** select compressed nodes (in the tree or on the screenshot), group, label and order them, layer by layer.
- **LLM:** describe what surfaces on the page and the refined structure wanted; the model edits the tree.

Every page starts the same way, whatever its source: the labeler sees only the compressed DOM, with no silver outline or prior tree shown, and reduces it semantically. Drafts (silver outlines, LLM generation) are an opt-in tool once editing has begun, never the default starting point, so labels aren't anchored on a model's answer.

## v1 scope

Manual labeling of **main-corpus** pages only: compressed DOM in, semantic tree out, via the editor's selection and batch operations on the tree and geometry wireframe. LLM edits and drafts come after; the picker already shows the Pro group.

## What exists today

| Piece | Where | Reuse |
|---|---|---|
| Output format | `variants.<name>` in any inspector dataset: `rootId`, `nodes[{id, kind, label, summary, children, sourceRefs, origin, reading_text, display_role}]` | Save labels in exactly this shape. Groups are `kind: "group"`, leaves are `kind: "dom"` with one `sourceRef`. |
| Structural validation | `inspector/build_data.py:62` `validate()` | Run on submit. |
| Tree/DOM/screenshot linking, search, keyboard nav | `inspector/app.mjs`, `inspector/model.mjs` | Base of the editor page. |
| Full vs compressed tree mapping | `inspector/compression.mjs`, `inspector/compression-model.mjs` | Compact-node → raw-ID resolution and "representative" mapping for folded nodes. |
| Wireframe from geometry | inspector's SFT-109 screenshot pane | Selection surface when a capture has no pixels. |
| Spoken preview | `inspector/narration.mjs` | Hear how each zoom level reads. |
| Model outline contract | `prompts/semantic_outline/contract.py` (`page, scope, outline[{depth,label,refs}], needs_expansion`) and `rubric-v1.md` | LLM output contract and validation; trivial conversion to/from the variant shape. |
| Compactors | `experiments/dom-downsampling/compact.py` (compact HTML, what SFT trains on) and `ui_ir/` (newer IR) | Produce the compressed view the labeler works on. |
| Publishing | `scripts/build_pages_demo.py` sanitizer | Only route for a label to leave the machine publicly. |

### How banana bread was made

Recovered from the archive (`local-artifacts` package, `examples/vision-study/`). Allrecipes is one of twelve sites in a "structure vs. vision" pilot (`PROTOCOL.md`), authored by an agent session in the order:

1. **Baseline** from DOM semantics and AX text only, screenshots unseen. Written as a script, `sites/allrecipes/build_baseline.py`, using a small `Hierarchy` helper (`section(id, label, refs, summary, parent=…)`, `dom(ref)`), with loops over repeated cards and steps. `baseline.json` is its output.
2. **Vision review** of the actual screenshots (first viewport plus two later scrolled viewports), recorded in `vision-review.json` as changed / confirmed / rejected relationships with cited pixel evidence.
3. **Revised** tree from that review, plus `report.md`.

So "authored" means LLM-agent-authored code over raw IDs, with an evidence log, not a human labeling UI. The tool replaces step 1's script with direct manipulation.

## Data source

The corpus is a **private** Hugging Face storage bucket, `hf://buckets/milintuns/semantic-reader-project-archive-bucket` (1.1 GB, 110 files), a copy of Dylan's 2026-09-14 preservation archive. Kept private: third-party content and credential-shaped text.

- **Auth:** the standard HF token (`hf auth login`, or `HF_TOKEN`). The `hf` CLI is installed with `uv tool install huggingface_hub` (v2.1.1).
- **Bucket path:** gitignored `.corpus.json` (`{"bucket": "hf://buckets/…"}`), committed `.corpus.example.json`.
- **Fetch:** `hf buckets cp` the packages needed into `runs/archive/`, then `tools/restore_screened.py` (in the bucket) verifies SHA-256s and extracts VM packages. Files are content-addressed tar shards, not browsable per-page files, so a fetch step must download a package and restore it, not sync individual pages.

### What's in it

| Package | Contents | Use |
|---|---|---|
| `vm/public-research-v1` (10 shards, ~510 MB) | Main corpus: **2,845 pages / 5,684 states** across 471 sites. Per state: `document.html`, `geometry.json` (bounds + computed styles per element), `ax.json`, `correspondence.json` (AX↔DOM), and `compression/document-00000.html` + `.source-map.json` (the compact view and its raw mapping). Plus silver outlines from `gemini-3.8-flash`: three independent passes per page (`labels/<id>-pass{1,2,3}/result.json`, ~1,800 each) in the outline contract, refs as `d0:<base36>` compact IDs. | The labeling queue. |
| `pro-annotations` (60 MB) | Gemini Pro outlines and LLM reviews for a subset of **the same pages** (all ~230 page IDs are in the main corpus). The SFT training data came from these. | Not a separate set to label: a stronger draft for those pages, and gold on them measures the teacher SFT imitated. |
| `vm/paired-labels-*` | 329 completed paired finals (277 SFT candidates). | Drafts; overlap with the above. |
| `local-artifacts` (29 MB) | `examples/vision-study/` (12 sites with captures, screenshots, baseline/revised/condensed trees and reports), `inspector/data`, compression outputs. | The 12 authored examples, including banana bread's sources. |

**No screenshots in the main corpus.** Captures are `media_suppressed_browser_state`; only the 12 vision-study sites have pixels. Screenshot-pane selection therefore runs on the geometry wireframe for nearly every page.

**Adapter already exists.** `scripts/build_sft109_qualitative.py` turns exactly this capture layout (document.html + geometry + compression + source map, with `d0:` refs resolved) into an inspector dataset with a wireframe. The labeler's loader generalizes it from three hand-picked cases to any page in the restored corpus.

Labels are written under `runs/labels/` (gitignored via `/runs/`) and synced to the bucket; see Shared labels and claims.

## Key decision: label on the compressed tree, store raw IDs

The person sees and selects compressed nodes, but every saved `sourceRef` is a raw DOM ID, as in banana bread. Compact IDs (`n…` aliases) are per-run and would break when the compactor changes. The compression mapping already resolves compact → raw; a folded node maps to its representative raw ID and is flagged.

## The flow

1. **Queue.** Two groups: **main** (main corpus) and **pro** (main-corpus pages that also have a Gemini Pro outline). Each page is `todo`, `claimed` or `submitted`, read from the bucket; open the next `todo`.
2. **Edit** the tree (below), generating drafts whenever useful. Autosaves as `draft`.
3. **Submit.** Runs validation, writes `runs/labels/<capture>.json` with provenance, opens the next capture. Errors block submit; warnings (e.g. uncovered content) are shown but don't.

## Editor

Three panes: compressed tree (left), semantic tree being built (middle), screenshot or wireframe (right). Selecting in any pane highlights in the others. The raw DOM is loaded with every page but hidden; a **Raw DOM** toggle shows it as an extra pane for checking what a compressed node stands for.

**Layer-by-layer (top-down).** Level 1: select the page's major regions and name them. Then drill into one region; only its unassigned nodes are shown; repeat. Depth in the semantic tree is the zoom level, so this matches how the tree will be read.

**Batch selection.** Shift/Cmd-click in the compressed tree, select a subtree, search-then-select-all matches, or lasso on the screenshot (see below).

**Batch operations on a selection:**

- Group as… (new group, type a label)
- Add to existing group / move up/down / reorder
- Make one reading unit (collapse a subtree into a single leaf, e.g. a recipe card)
- Make each child a leaf (e.g. ingredient list items)
- Unwrap group / merge groups
- Skip (decorative, ads, hidden), with a reason so coverage stays honest
- **Repeat structure** (semi-automatic): after grouping one card, the tool finds siblings with the same DOM shape (same tag/child signature under the same parent, e.g. ten "Most-Saved" cards) and offers to apply the same grouping with labels taken from each card's heading. One click to accept, all previewed first. Deterministic, no LLM.

**Always visible:**

- **Coverage:** content-bearing compact nodes not yet placed or skipped. The main completeness check banana bread never had.
- **Checks:** `validate()` plus what it lacks: leaf text matches DOM text; a child's refs lie inside its parent's region; reading order follows document order unless overridden; no ancestor/descendant overlap between leaves (rubric v1).
- **Zoom preview:** the tree read at level 1, 2, 3 as text, optionally spoken via `narration.mjs`.

Undo/redo throughout.

### Screenshot selection: feasibility

Feasible, with one limit to plan around. Every captured node carries a page-coordinate `rect` (banana bread: all 5,145 nodes, page 18,435 px tall). Selecting by rectangle is a geometry query: pick nodes whose rect lies inside the lasso, then keep the outermost compressed nodes so a lasso around a card selects the card, not its 40 descendants. Clicking selects the smallest compressed node under the cursor; a modifier walks up to its parent.

The limit is pixels: the main corpus is media-suppressed (no screenshots), and banana bread's screenshot covers only the first 1280×720 viewport. So the selection surface is the existing wireframe (boxes + text drawn from `geometry.json`), which is selectable the same way; real pixels only for the 12 vision-study sites. Geometry also carries computed styles (font size/weight, colors), so the wireframe can render headings larger and bold to read more like the page. Known gaps: nodes with zero-size or offscreen rects (collapsed menus, hidden dialogs) are only selectable from the tree, and overlays can cover content they don't contain.

## LLM edits

1. The person writes what surfaces first ("site header; the recipe: overview, ingredients, steps, nutrition, tips; community Q&A and reviews; related recipes; footer") plus any notes ("each step is its own stop; ads skipped"), optionally scoped to the selected region.
2. The model gets the description, the current tree, the compact view and the rubric, and returns the outline contract. `contract.validate_output` rejects unknown refs before anything is shown.
3. The result is shown as a diff against the current tree; accept or reject. Follow-ups ("split reviews into helpful and recent") work the same way.

"Generate draft" is the same call with no description. The existing silver outlines (up to three Gemini passes per page, or the Pro final where one exists) are offered as free drafts.

Model calls go through a loopback endpoint on the local server; no keys in the page. Each call is recorded in provenance.

- **v1: Ollama, local and free.** Reuse `harness/ollama_model.py`, which already talks to `127.0.0.1:11434`, verifies the model is installed, and refuses cloud-backed Ollama models. Model is a setting (any installed tag). Ollama is not installed on this machine yet. Local models will draft worse than Gemini Pro on long pages; the editor is the fallback, so that is acceptable for v1.
- **v2: paid cloud.** `harness/model.py` (Vertex AI Gemini, authenticated as the named gcloud user in `.lab-config.json`, no API keys; `gemini-3.1-pro-preview` is the judge default and the silver outlines came from a Gemini Pro run), or a Claude API client. Added when credentials exist.

## Saved file

The existing variant shape plus a provenance block:

```json
{
  "capture": "allrecipes",
  "rootId": "page",
  "nodes": [ ... ],
  "provenance": {
    "labeler": "…", "started": "…", "submitted": "…",
    "status": "draft | submitted",
    "llm_calls": [{ "model": "…", "prompt_version": "…", "instruction": "…", "accepted": true }],
    "skipped": { "e5130": "advertisement iframe" },
    "notes": { "page": "…", "site-header": "…" }
  }
}
```

Imports into the inspector through the existing `--import-datasets` path. Converts to the outline contract (`depth, label, refs`) for training.

## Shared labels and claims

Labels live in the bucket, not only on one laptop, and several people can label at once without duplicating work. The bucket is the only shared state; no server or database.

```
hf://buckets/<ns>/<bucket>/labels/
  claims/<page-id>.json            {"labeler", "claimed_at"}
  submitted/<page-id>/<labeler>.json   the saved label file
```

- **Identity:** the labeler's HF username (`hf auth whoami`). Nothing to configure.
- **Opening the queue:** list `labels/claims/` and `labels/submitted/` once; pages with a submission or a live claim are hidden from others.
- **Claiming:** opening a page writes its claim file. Claims expire after 24 hours without a submit, so abandoned pages return to the queue.
- **Race:** buckets have no locking, so two people opening the same page at the same second can both claim it. After writing a claim, the tool re-reads the claims; the earliest `claimed_at` wins and the other is moved to the next page. With a handful of labelers this is rare and costs at most a duplicate label, never a lost one.
- **Submitting:** uploads `submitted/<page-id>/<labeler>.json` and keeps a local copy in `runs/labels/`. Files are per labeler, so nobody can overwrite someone else's label.
- **Drafts** stay local (autosave); only submits are shared.
- **Deliberate overlap:** a configurable fraction of pages (say 10%) can be served to a second labeler on purpose, to measure agreement later. Off in v1.

Access: other labelers need write access to the bucket. A personal namespace likely can't grant that; moving the bucket to an HF organization (`hf buckets move`) is the expected route.

## Where it lives

A separate app, not part of `inspector/`. The inspector is a read-only viewer whose static files are published to GitHub Pages; the labeler writes labels, syncs to the bucket and calls Ollama, so it gets its own server and keeps the public viewer's security assumptions unchanged.

```
labeler/
  server.py     loopback only, stdlib: static app, read-only /corpus/ (queue.json + the six
                capture files per page), POST /labels → runs/labels/; later claims/sync (phase 3)
                and an Ollama proxy (phase 5)
  index.html    page picker + editor
  labeler.mjs   UI
  corpus.mjs    capture files → page model, in the browser
  queue_order.py  builds runs/corpus/queue.json
```

It imports the reusable pure modules from `inspector/` (`model.mjs`, `narration.mjs`, `compression-model.mjs`) rather than copying them, and `validate()` from `inspector/build_data.py`. Submitted labels can still be viewed in the inspector through its existing `--import-datasets` path.

## Labeling is exploratory

These labels are a precursor to deciding what a good tree is, so the tool imposes no policy. Instead it captures the reasoning: a free-text `notes` field per capture and per group ("kept nav as one stop because…"). Existing references to read alongside, not enforce: the judge's four criteria (`training/judge-rubric.md`: coverage, grounding, grouping, labels, 0–3) and the teacher labeler prompt (`prompts/semantic_outline/rubric-v1.md`). Once enough examples exist, the notes become the written policy.

## Phases

| Phase | Delivers | Done when |
|---|---|---|
| 0. Data ✅ | `.corpus.json`, `scripts/fetch_corpus.py`: downloads the main package, checks every shard and file SHA-256, unpacks only the labeler's files into `runs/corpus/` (2.2 GB, 39,773 files), lists the 285 Pro pages; `--verify` re-checks offline | Done 2026-10-04 |
| 1. Loader + queue ✅ | `labeler/`: `queue_order.py` (one page per site first, round-robin by category), `server.py`, in-browser `corpus.mjs` (ports the SFT-109 builder's DOM join), page picker and read-only page view; corpus check | Any queued page opens with raw DOM ↔ compressed tree linking |
| 2. Manual editor ✅ | `labeler/index.html` editable: three panes, multi-select (tree, search, wireframe rectangle), group / label / move / unwrap / merge / one reading unit / skip, coverage list, undo/redo, local autosave, Submit with `validate()` via POST to `labeler/server.py` | A main page can be labeled end to end, and the output imports into the inspector |
| 3. Editor speedups | Select similar with a − / + scope level (same tag path under a scope n levels up: siblings, then cousins, …) and Select siblings; all grouping happens in the tree, the compressed row only places, selects and skips (Group each was tried and removed 2026-10-05); units keep their DOM text and are not renamable | Ten cards become ten titled groups in a few clicks |
| 4. Shared labels | Claims and submissions in the bucket, queue hides taken pages, claim expiry, HF username as labeler | Two labelers on two machines never get the same page |
| 5. LLM edits | Ollama draft and instruction edits, shown as diffs; silver drafts opt-in | A description produces a valid, accepted edit |

**UI pass (2026-10-05).** Page bar: queue, previous/next, title, category, URL. Left 2/3: wireframe and compressed DOM side by side, one-way scroll sync (DOM drives wireframe), placement actions in its menu bar. Right 1/3: unplaced nodes above the semantic tree with its own menu bar. The raw DOM pane and Submit are gone: a page is **untouched**, **in progress** or **complete** (nothing unplaced, no errors), every edit autosaves, the server re-validates complete labels (keeping them in progress if that fails), and complete saves write the inspector dataset.

Later on 2026-10-05: the wireframe lasso was replaced by drag-to-pan (click still selects, Alt-click the parent) plus a zoom menu and ⌘/Ctrl+scroll zoom; One unit was folded into Add (Add merges units already inside a node); Skip was renamed Ignore; Group each and Move to were removed.

Phases 3 and 4 were swapped on 2026-10-04 so the editor is settled before anything is built around it. A whole-label checker (unit text matches DOM text, regions, reading order) can run later as a standalone script over submitted labels; it is not built into the editor.

Not planned: real screenshots for the 12 vision-study sites, and paid cloud models. The queue has two groups, main and pro.

### Phase 1 plan: loader + queue

**What a page is.** Each page has two states: `state-000` desktop (1365×900) and `state-001` mobile (390×844). Label the desktop state: 2,841 pages (4 pages have only a mobile capture and are skipped).

**IDs.** Same scheme as the published SFT-109 examples. Raw element = `src-<base36 document-order index>` from parsing `document.html`. The compact source map uses the same indexes, so a retained compact node *is* its raw element, and a folded one points at its `representedBy` element. Geometry rows use the collector's `n<k>` IDs, mapped by its order rule (document order, `script/style/noscript/template/link/meta/base` last).

**Parse in the browser, not Playwright.** The SFT-109 builder parses `document.html` with headless Chromium. The labeler already runs in a browser, so `DOMParser` there does the same job: no new dependency, nothing prebuilt for 2,841 pages, and each page is built when opened. HTML parsing is standardized, and every load is checked against the source map's element count and tags, so a mismatch is caught, not silently mislabeled.

**Deliverables:**

1. `labeler/queue_order.py` → `runs/corpus/queue.json`, built as described in **Queue order** below. One small test.
2. `labeler/server.py`: loopback-only stdlib server serving the app and a read-only `/corpus/` route onto `runs/corpus/`, allowing only `queue.json` and the six capture files. One test.
3. `labeler/corpus.mjs`:
   - `parseDocument(html)`: browser-only port of the builder's element enumeration.
   - `buildDataset(...)`: pure function from parsed elements, source map, geometry, capture and environment to a page model. Ports `check_source_map`, `collector_ids` and `build_dom`. Adds the **compressed tree** (retained nodes, each parented to its nearest retained ancestor), the labeler's starting point.
   - `node --test` with synthetic elements.
4. `labeler/index.html`, read-only for now:
   - **Page picker:** pro / main tabs, the queue in order with each page's URL, category and status (todo / draft / submitted, from `runs/labels/` for now; shared claims in phase 3), search by URL or category, and a **Next page** button that opens the first todo. Any page can be opened, but Next is the default so the coverage order holds.
   - **Page view:** compressed tree linked to the raw DOM (click one, the other highlights). Phase 2 makes it editable and adds the wireframe.
5. Corpus check: a one-off in-browser pass over all 2,841 pages reporting any page whose parse disagrees with its source map or lacks geometry. Failing pages go to `runs/corpus/excluded.json` and are left out of the queue.

**Queue order** (decided 2026-10-04). The corpus is 2,841 desktop pages from 471 sites in 111 categories; sites range from 1 to 20 pages (median 3) and categories from 1 to 136 pages.

1. **Eligible:** every desktop state (`state-000`) with compact view, source map and geometry that passes the corpus check.
2. **Groups:** pages listed in `pro-pages.json` (285) are **pro**; the rest are **main**. Each group is ordered separately by the same rule.
3. **Order: one page per site first, round-robin by category.**
   - Pass 1 takes one page from every site (≈471 pages), cycling through categories: one page from category A, then B, then C, …, then back to A.
   - Pass 2 repeats the cycle with each site's second page, and so on until every page is placed.
   - Within a category, sites are shuffled with a fixed seed, and each site's pages are shuffled with the same seed.
4. **Frozen:** written once to `queue.json` with the seed and the rule recorded in its header, identical for every labeler. Rebuilding with the same seed and corpus gives the same order.

Why: early labels are the most valuable, so they should cover as many different sites as possible (pages on one site mostly share a template) and every category before any repeats. Plain round-robin by category was rejected because a 20-page site in a small category would come up on every turn of that category; random order was rejected because it mirrors the corpus skew toward large categories and sites.

The queue is only an order. "Next page" = the first page in the chosen group's order with no submission and no live claim (phase 3), so labelers never coordinate by hand.

**Done when:** the picker lists the queue and any page opens in the labeler with raw DOM ↔ compressed tree linking working, and the corpus check reports how many pages are usable.

**Result (2026-10-04).** Built as planned; run instructions in `labeler/README.md`. Queue: 2,556 main + 285 pro pages (4 skipped: mobile-only). Corpus check: all 2,841 pages pass (document hash, parse = source map, geometry present, every compact node retained); a full check takes about 35 seconds. Findings: the compactor never marks `<html>`/`<head>` with `data-r`, so the compressed tree starts at `<title>` and `<body>`; geometry covers only rendered elements (e.g. 545 of 1,268 on one docs page), which bounds what the phase 2 wireframe can draw; the server's listen backlog was raised from 5 to 64 because six parallel fetches per page dropped connections.

**Deferred to phase 5:** silver drafts. Their IDs aren't page IDs; the mapping is in `labels/state.json`, which phase 5 adds to the fetch.

### Phase 2 result (2026-10-04)

Built in `labeler/`: `label-model.mjs` (every edit as a pure, tested operation), `wireframe.mjs` (rectangle and click selection over geometry), the editor in `labeler.mjs`, and `POST /api/labels` (draft, or submit validated server-side with `inspector/build_data.py`'s `validate()` against a DOM rebuilt from the page's source map) plus `POST /api/export`. Usage is in `labeler/README.md`.

Decisions made while building:

- **A unit covers its whole compressed subtree.** Placing a node inside an existing unit splits that unit down the path to it (siblings stay units), so labeling can go coarse to fine: place the whole header, then open its group and pull out the navigation. Placing a container that already holds units merges them into it (decided 2026-10-05; Undo reverts it).
- **New units and groups are inserted in document order** within their group; manual moves override that.
- **Group `sourceRefs` stay empty** except the root, which references `<title>`; regions are carried by the units. `validate()` accepts this, and the inspector shows the tree with its links.
- **Coverage** counts compressed nodes with direct text or an interactive or media tag that are neither inside a unit nor skipped.
- **Labeler identity** is the OS user name until phase 3 switches to the HF username.

Verified in headless Chrome on a real page: grouping, add-children, wireframe drag, the overlap refusal, skip, undo/redo, rename, full coverage, submit with server validation, export, auto-advance to the next page, and the exported dataset opening in the inspector with no console errors.

## Open questions

1. **Order within main:** random, or spread across site categories so a few large sites don't dominate early labels.
2. **Which compressed view:** compact HTML (what SFT-109 trained on) or `ui_ir`? Recommend compact HTML until the model input changes.
3. **Zoom levels:** is depth alone enough, or do some nodes need an explicit "appears at level N"?

## Not in v0

Human review pass, hosted multi-user server, accounts beyond HF usernames, agreement statistics.
