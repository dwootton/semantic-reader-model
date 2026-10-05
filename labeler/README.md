# Semantic labeler

Local tool for hand-labeling semantic trees from the compressed DOM of corpus pages. Design and phases: [docs/design/gold-labeling-tool-v0.md](../docs/design/gold-labeling-tool-v0.md). Phase 1 (current): page picker and a read-only view linking each page's compressed tree to its raw DOM. Editing arrives in phase 2.

## Run

```sh
python3 scripts/fetch_corpus.py        # once: private corpus → runs/corpus/ (needs .corpus.json and hf auth login)
python3 labeler/queue_order.py         # page order → runs/corpus/queue.json
python3 labeler/server.py              # http://127.0.0.1:8770
```

- `/` lists the queue (main and pro groups); **Next page** opens the first unlabeled page.
- `/?page=<site>/<page>&group=main` opens one page. Click a node in either tree to select its counterpart; collapsed raw elements select the compressed node they were folded into. Arrow keys move and expand, Enter selects.
- `/?check` loads every queued page in the browser and writes `runs/corpus/excluded.json`; rerun `queue_order.py` afterwards to drop failing pages.

The server binds to loopback only, serves just the app, `queue.json` and the six capture files per page, and returns capture HTML as plain text. Page text is inserted with `textContent`; nothing from a capture executes. Everything under `runs/` is gitignored.

## Test

```sh
python3 -m unittest discover -s labeler -p 'test_*.py' -q
node --test labeler/*.test.mjs
```
