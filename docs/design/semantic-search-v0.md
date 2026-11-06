# Semantic search v0 (experiment)

Search one corpus page for an element by meaning: "login" should surface log in, register, account and the like,
each result a node you can jump to. It does not build a semantic outline. This is an experiment to see how
well a small offline embedding model does, and how fast it is.

## Scope

- One page at a time, computed live. Nothing is precomputed, cached on disk or stored between page opens.
- Scores and timings are shown (for development).
- It lives beside the labeler (same server, its own page) and touches no labeling state.

## How it works

1. **Page open.** `/search?page=<site>/<page>` loads the page with the labeler's `loadPage` (`labeler/corpus.mjs`),
   so ids match the labeler: the candidates are the compact nodes (`src-…`), whose text comes from the raw DOM.
2. **Text per node.** One short string per candidate:
   - own text (for elements with none, their compressed-DOM descendants' text joined with ` · `, truncated;
     `textContent` runs words together)
   - `aria-label`, `title`, `alt`, `placeholder`, `value` on buttons
   - the `href` path (`/account/login` becomes "account login")
   - `id` and `class` split into words (`login-btn` becomes "login btn")
   - the tag or role ("link", "button", "input")
   - context: the nearest landmark above it ("in navigation", "in footer")

   Nodes with no text left are skipped.
3. **Embed the page.** The browser POSTs the strings to `POST /api/embed`; the server returns one vector each.
   The page holds them in memory while it is open and shows how long embedding took.
4. **Search.** Each query is embedded through the same endpoint (a few ms). In the browser:
   `score = cosine(query, node) + 0.1 × (query words found literally in id/class/href/text)`. Then a cut-off
   (default 0.72: bge-small puts unrelated text at about 0.55–0.65; adjustable on the page), the top 20, and a node is folded under a matching ancestor so one login form
   doesn't fill the list.
5. **Results.** A list with score, tag and text. Clicking a result highlights and scrolls to the node in the page
   copy (the same sandboxed iframe and `data-sr-sel` marking as the labeler). Pages without a copy (36) show
   only the list.

## Exact tier: a superset of a screen reader's Find (2026-11-06)

Screen readers (NVDA, JAWS) search the browse-mode text: visible text plus spoken names, as a case-insensitive
substring. So results now come in two tiers:

- **Exact, always shown, ignoring the cut-off.** `speakable()` walks `document.html` in order and builds one
  string: text, `aria-labelledby` / `aria-label` (which replace a link's, button's or heading's contents), `alt`,
  input values and placeholders; it skips `aria-hidden`, `hidden` and elements the capture saw as
  `display:none` / `visibility:hidden`. `findExact()` matches the query there (case- and whitespace-insensitive,
  no length cap) and pins each match to the smallest compressed-DOM node holding all of it, so a phrase running
  across a link lands on its paragraph. It approximates the browser's accessible-name rules (no CSS generated
  content).
- **Meaning, below, above the cut-off**, without nodes already in Exact. Their embedded text now also uses
  `aria-labelledby` and `<label for>`. The exact-word bonus counts only what a screen reader never speaks: id,
  class, name and href words. Results inside hidden parts of the page say "not spoken".

## Model

`BAAI/bge-small-en-v1.5` through `fastembed` (ONNX on CPU, no torch, about 130 MB downloaded once to the
fastembed cache). It turns a string into one 384-number vector; strings with similar meaning get vectors that
point the same way. It was pretrained on general English and tuned on query–passage pairs, so it knows that
"sign in" is close to "login" but knows nothing about web pages in particular, hence the literal-match boost.
Swapping models is one line, for comparing later.

## Server

- `POST /api/embed {texts: [...]}` → `{vectors: [[...]], model, ms}`. Batched, with a limit on text count and length.
- `fastembed` is imported lazily on the first call, so the labeler still runs with plain `python3`. To use
  search, start the server with `uv run --with fastembed python labeler/server.py`; without it the endpoint
  returns 501 with that command.
- The model loads once per server process (that is the model, not page data).

Why the browser builds the strings: `loadPage` already parses the capture with the browser's HTML parser,
which is what the `src-…` ids are counted from. Parsing it again in Python could number elements differently.

## Files

- `labeler/search.html`, `labeler/search.mjs`: the page (a page picker plus query box, results, page copy).
- `labeler/server.py`: `/search` route and `/api/embed`.
- `labeler/search-text.mjs` + test: the node-to-string and scoring functions (pure, with a node test).

## Out of scope for now (later, if results call for it)

- A bigger embedding model (bge-base, about 4× slower).
- A reranker over the top 20 (more accurate, plus 100–300 ms per query).
- Query expansion with an LLM through Ollama ("login" → sign in, register, account, password).
- Searching the whole corpus, which would need a precomputed index.

## Checking it

By hand on about 5 pages with queries like login, search, pricing, contact, download, docs, newsletter signup,
noting what ranks top and the embed and query times.
