# Semantic labeler

Local tool for hand-labeling semantic trees from the compressed DOM of corpus pages. Design and phases: [docs/design/gold-labeling-tool-v0.md](../docs/design/gold-labeling-tool-v0.md). Phases 0–2 are built: corpus fetch, queue and page picker, and the manual editor.

## Run

```sh
python3 scripts/fetch_corpus.py        # once: private corpus → runs/corpus/ (needs .corpus.json and hf auth login)
python3 labeler/queue_order.py         # page order → runs/corpus/queue.json
python3 labeler/server.py              # http://127.0.0.1:8770
```

`/` lists the queue (main and pro groups) with each page's status; **Next page** opens the first page without a label. `/?check` loads every queued page and writes `runs/corpus/excluded.json`; rerun `queue_order.py` afterwards.

## Labeling a page

Panes: **Compressed DOM** (what you label from), **Semantic tree** (what you build), **Wireframe** (boxes drawn from captured geometry; there are no screenshots). **Raw DOM** in the header adds the raw tree as a fourth pane.

1. Select compressed nodes: click, ⌘-click to add, Shift-click for a range, **Select matches** for everything matching the search, or drag a box on the wireframe (it keeps the outermost nodes, so a box around a card selects the card). Alt-click on the wireframe selects the parent.
2. Place them in the group shown as **Adding to** (the page root at first):
   - **Add** (A): each selected node becomes one unit, covering everything inside it.
   - **Add children** (C): each child becomes its own unit (a list's items, say).
   - **Group** (G, type a label, Enter): a new group holding the selection; Shift+Enter groups the children instead.
   - **One unit** (U): one unit, merging any units already inside it.
   - **Skip** (S): not content (decorative, ad, hidden), with a reason.
   Placing a node that sits inside an existing unit splits that unit down to it, so you can start coarse (whole header) and refine.
3. Shape the tree: select tree nodes and use Group, **Open** (O or double-click; new units go inside that group, Esc goes back up), Unwrap, Merge, ↑ ↓ (Alt+↑/↓), → ← (Alt+→/←, into the group above or out), Move to…, Split a unit into its children, Remove (Delete). Edit a node's label, summary and notes below the tree; the root also takes page notes.
4. **Not placed** lists content still unplaced or unskipped; click an entry to select it. Errors are shown above it and block Submit.
5. **Submit** validates in the browser and again on the server (against the page's source map), then opens the next page.

Edits autosave as a draft about a second after each change; ⌘Z / ⇧⌘Z undo and redo. Editing a submitted label makes it a draft until submitted again.

## Output

- `runs/labels/<site>__<page>.json`: the semantic tree in the inspector's variant shape (`rootId`, groups and units whose `sourceRefs` are raw DOM IDs) plus `provenance` (status, labeler, timestamps, skips, notes, capture URL and document hash).
- `runs/labels/datasets/label-<page>.json`, written on submit: a full inspector dataset (raw DOM + `gold` variant, the banana bread layout). View with `python3 inspector/build_data.py --import-datasets runs/labels/datasets`, then the inspector.

The server binds to loopback only, serves just the app, `queue.json` and the six capture files per page, and returns capture HTML as plain text. Page text is inserted with `textContent`; nothing from a capture executes. Everything under `runs/` is gitignored.

## Test

```sh
python3 -m unittest discover -s labeler -p 'test_*.py' -q
node --test labeler/*.test.mjs
```
