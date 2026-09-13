# Local compression and node recovery

Run the saved-example audit from the repository root:

```sh
python3 experiments/dom-downsampling/recover.py
python3 experiments/dom-downsampling/test_recovery.py
```

The runner inventories distinct saved documents, verifies source hashes when available, and runs `conservative` and `wrappers` profiles in isolated Chromium with network requests blocked. It parses captures without navigating to them or executing their scripts. Existing Playwright/Chromium are used; there are no new dependencies or model calls.

The corpus has 14 datasets and 15 HTML documents: 12 vision-study sites plus the EWH dashboard (main and embedded frame documents) and NYT. The latter HTML files live at paths recorded in their DOM indices under Downloads; unavailable files are reported explicitly. Hierarchy variants and screenshots are not additional captures.

## What recovery means

- **Retained:** the original element remains in compressed HTML, marked with a collision-free `data-sr-node` attribute. Original captured IDs are joined separately using a unique CSS selector and matching tag against the hash-verified source.
- **Collapsed:** a strictly eligible generic wrapper was unwrapped. Its child order and original structure are in the local patch.
- **Excluded:** script/style subtrees are absent from model input, with their content stored locally for recovery. Comments and stripped attributes also remain in the patch.
- **Unresolved metadata join:** a captured selector does not identify exactly one matching element in the parsed source. This is an input/mapping limitation, separate from compression damage.

`restoreCompressed(html, patch)` reconstructs the **browser-normalized original DOM** using only those two artifacts. Retained element text and retained attributes are read from compressed HTML. The patch contains original structural relationships, text offsets/lengths, attribute ordering, removed attribute values, comments, and text of excluded elements. It does not duplicate retained text. Every run checks whether the source itself survives an HTML parse/serialize round trip, then compares the restored serialization against the original parsed DOM and counts recovered elements.

This is not a general-purpose storage compressor: the local patch can be large. It reduces material intended for a model while keeping reversible local evidence. Removed material is **not recoverable from the compressed HTML alone**, and its local availability does not mean the organizer saw or understood it. Sizes include source markers but exclude organizer instructions/schema; they are UTF-8 bytes, not model tokens.

## Verification

Checks cover retained text by owning element, retained attributes, parent relationships (including templates), order, unique source IDs, stable HTML parsing, and exact reconstructed DOM equality. Patches cover whitespace and comments, foreign namespaces, state/relationship attributes, and excluded payloads. Regression tests include malformed source, marker collisions, selective wrapper recovery and intentional compressed-text/ID damage, unexpected additions, and a 300-level nested tree. The runner transfers the nested patch as a JSON string to avoid browser-tool serialization limits.

The two profiles preserve the existing conservative rules. `wrappers` only collapses originally attribute-free HTML divs whose parent is a div and whose sole child is another div. Markers are assigned after eligibility so instrumentation does not suppress collapse. Native semantic tags and text are not summarized. The model may therefore still receive many implementation wrappers; this is an initial recovery baseline, not a claim of optimal compression.

Reports and per-node mapping/patch artifacts are written to `runs/compression/local-recovery/`. Inspect HTML as source text: compressed captures are not sanitized executable pages. Neither visual equivalence nor JavaScript behavior, accessibility-name equivalence, or LLM organization quality is established by DOM recovery. Original source syntax, quoting and casing may be normalized by the browser parser.

A source that is not round-trip-stable is a failed strict-recovery case, not an invitation to normalize repeatedly and hide the difference. NYT is such a case: the original saved HTML grows from 6,791 to 6,815 ordinary document-tree elements (excluding template contents) on a second parse. Its failed artifacts remain inspectable. Recovery equality refers to the first browser-parsed DOM.

## Results from the complete local run

The [full report](../../runs/compression/local-recovery/report.md) covers both profiles on all 15 documents (14 datasets). Twenty-eight of 30 profile trials pass; NYT fails both strict audits. In the 14 passing documents, all 26,996 original parsed elements are reconstructed exactly from compressed HTML plus the patch. Conservative HTML retains all 26,221 elements outside script/style subtrees. The wrapper profile removes only 18 more elements, which the patch restores.

Conservative input shrinks by 65.55% in aggregate and 23.18% at the median, measured in UTF-8 bytes including source markers. **Hacker News, MDN and W3C grow** because the markers cost more than the removed payload. This baseline does not yet choose an uncompressed fallback by size or measure tokenizer costs. Local patches occupy about 14.08 MB for the passing inputs, versus 10.72 MB of raw source; storage savings are not the objective.

| Example | Parsed elements | Retained in conservative HTML | Exactly recovered with patch | HTML byte reduction |
|---|---:|---:|---:|---:|
| NASA | 2,576 | 2,524 | 2,576 | 21.86% |
| IKEA | 3,195 | 3,090 | 3,195 | 76.87% |

Captured-ID mapping is a separate result: 31,379 of 32,037 indexed IDs join to the parsed source. Unresolved IDs: Allrecipes 30, MDN 3, OpenStreetMap 4, EWH dashboard 54, NYT 567. Of these, 91 belong to otherwise passing documents. Do not confuse successful reconstruction of parsed nodes with successful linkage to every older capture ID. Per-node mapping files list every retained, collapsed, excluded or unresolved node.

Seven browser regression tests and JS syntax, Ruff and Mypy checks pass. The corpus command deliberately returns exit code 1 for NYT's recorded audit failure. This completed experiment has not established LLM organization quality or model-token savings.
