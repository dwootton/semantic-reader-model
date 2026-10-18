# Semantic labeler

Local tool for hand-labeling semantic trees from the compressed DOM of corpus pages. Design and phases: [docs/design/gold-labeling-tool-v0.md](../docs/design/gold-labeling-tool-v0.md). Phases 0–2 are built: corpus fetch, queue and page picker, and the manual editor.

## Run

```sh
python3 scripts/fetch_corpus.py        # once: private corpus → runs/corpus/ (needs .corpus.json and hf auth login)
python3 labeler/queue_order.py         # page order → runs/corpus/queue.json
python3 labeler/server.py              # http://127.0.0.1:8770
```

`/` lists the queue (main and pro groups) with each page's status: **untouched** (no label yet), **in progress** (edited) or **complete** (every content node placed or skipped, no errors). **Next page** opens the first untouched page. `/?check` loads every queued page and writes `runs/corpus/excluded.json`; rerun `queue_order.py` afterwards.

## Labeling a page

The page bar shows ← Queue, previous/next arrows, the page title, its category and URL. The left window, titled **Wireframe** and **Compressed DOM** over its two halves (60% by default; drag the divider, or focus it and use ←/→, to resize, remembered per browser) holds the **wireframe** (boxes and text drawn from captured geometry; there are no screenshots) beside the **compressed DOM** you label from, with the placement actions in its menu bar; scrolling the DOM scrolls the wireframe to match. The right column holds **Unplaced DOM nodes** (with **Ignore all** at its top right) above the **semantic tree** you build, whose menu bar starts with Undo/Redo and has the tree actions and the save status. **Clear Selection** in either menu bar clears the selection. In the compressed DOM, placed nodes fade, and each placed unit is outlined by a hairline above its first row and below its last; **Collapse all** and **Hide placed** are toggles.

1. Select compressed nodes: click, ⌘-click to add, Shift-click for a range, or click a box on the wireframe (Alt-click selects its parent). Drag or scroll the wireframe to pan; zoom with the − / + menu at its top right (click the level to return to fit width), or ⌘/Ctrl+scroll or pinch.
2. Place them with the blue **Add →** / **Add children →** buttons at the right of the menu, or **drag** selected rows onto the semantic tree: the line or box shows whether they land before, after or inside a group. Or use the buttons, which put things in the group highlighted in the tree: the last group you clicked (or the group of the unit you clicked; Esc returns to the page root).
   - **Add** (A): each selected node becomes one unit, covering everything inside it; any units already placed inside it are merged into it.
   - **Add children** (C): each child becomes its own unit (a list's items, say).
   - **Select similar**, then **−** / **+**: nodes on the same tag path as the selection within a scope that many levels up. Level 1 is same-tag siblings; level 2 adds cousins (every `<strong>` in each `<p>` of the same `<div>`); and so on up to the page. The scope container is outlined on the wireframe and highlighted in the tree. **Select siblings** selects every sibling, any tag.
   - **Ignore** (S): not content (decorative, ad, hidden), with a reason. With only ignored nodes selected the same button reads **Unignore**.
   Placing a node that sits inside an existing unit splits that unit down to it, so you can start coarse (whole header) and refine.
3. Shape the tree: drag tree nodes to reorder them or move them into other groups; drag them back onto the compressed DOM to remove them. **Double-click** a group (or press F2) to rename it in place; units keep their DOM text. Grouping happens here: **Group** (G) wraps the selected nodes in a new group named after the first one's text (select a heading unit plus its content and press G); rename it in the tree if needed. With a single group selected the button reads **Ungroup** and removes the group, keeping its contents. Other buttons: Merge groups, move up / down (Alt+↑/↓), move into the group above / out of its group (Alt+→/←), **Unpack** (a unit into units for each of its parts), Remove (Delete). Each tree row has an ellipsis on hover that opens its **summary** (what the group contains, for a reader) and **notes** (why you labeled it this way); rows with either show a note icon instead. The root also takes page notes.
4. **Unplaced DOM nodes** lists content not yet placed or ignored; click an entry to select it, drag it onto the tree to place it, or **Ignore all** to ignore everything listed at once (with one reason; nodes holding a placed unit are left for you). Errors show under the semantic tree; a page with errors stays in progress.
There is no submit: every change autosaves about a second later (⌘Z / ⇧⌘Z undo and redo), and the save status shows whether the page is in progress or complete. A page becomes complete once nothing is unplaced and there are no errors; the server re-checks a complete label against the page's source map and keeps it as in progress if that fails.

## Screenshots

The corpus was captured without screenshots, so `labeler/render_pages.py` renders each page's first screen from its live URL under the capture's own conditions: the collector's `capture_media_safety.js` (copied unchanged: Arial everywhere, media hidden behind grey placeholders, no background images), the same 1365×900 viewport, and only the site's own requests. That makes the screenshot line up with the captured element boxes.

```sh
uv run --with playwright==1.62.0 --with pillow python labeler/render_pages.py --group main --count 100000   # resumable; --check adds overlays
```

In the wireframe pane, **Screenshot | Wireframe** switches between the screenshot (first 900 px, wireframe below it) and the plain wireframe; the choice is remembered. Clicking and selection always use the captured boxes, so they are exact either way. The score beside the toggle says how far the screenshot can be trusted: the share of the capture's first-screen text elements (unique tag + text) found on the live page at the captured position (±4 px, after one shared vertical offset). A low score means the live page has changed or blocks rendering; switch to Wireframe.

## Output

- `runs/labels/<site>__<page>.json`: the semantic tree in the inspector's variant shape (`rootId`, groups and units whose `sourceRefs` are raw DOM IDs) plus `provenance` (status, labeler, timestamps, skips, notes, capture URL and document hash).
- `runs/labels/datasets/label-<page>.json`, written whenever a complete label is saved: a full inspector dataset (raw DOM + `gold` variant, the banana bread layout). View with `python3 inspector/build_data.py --import-datasets runs/labels/datasets`, then the inspector.

The server binds to loopback only, serves just the app, `queue.json` and the six capture files per page, and returns capture HTML as plain text. Page text is inserted with `textContent`; nothing from a capture executes. Everything under `runs/` is gitignored.

## Test

```sh
python3 -m unittest discover -s labeler -p 'test_*.py' -q
node --test labeler/*.test.mjs
```
