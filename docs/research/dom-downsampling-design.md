# Conservative DOM downsampling

## Decision

Use deterministic, content-preserving HTML reduction before considering text summarization or structural pruning. A runnable prototype lives in `experiments/dom-downsampling/downsample.js`; it is separate from the benchmark navigator and does not change its AX-only input boundary.

The inspiration is D2Snap's separation of element, attribute, and text reduction. The paper also converts formatting to Markdown and uses relatively aggressive text/element reduction in its reference configuration. For this project, native HTML and preservation take priority. See [paper](https://arxiv.org/html/2508.04412v4) and [research notes](../dom-downsampling-research.md). This prototype is an adaptation, not a reproduction of D2Snap.

## Method

1. Parse the capture with an HTML5 browser parser in an isolated context. This normalizes malformed source before measuring preservation.
2. Remove script/style subtrees and comments, including inside templates. Record these separately as payload removal. Their text is excluded from the content baseline.
3. Remove HTML class attributes and recognized inline event-handler attributes. Keep inline style because it can encode hidden state. Keep IDs, ARIA, label/table references, URLs, image alternatives, form constraints/states, language, direction, hidden/inert, data attributes, unknown attributes, and SVG/MathML structure.
4. Default to **no content-element removal and no text reduction**. Preserve headings, paragraphs, lists, tables, forms, links, images, collapsed regions, repetition, whitespace, and ordering.
5. An optional wrapper mode unwraps only originally attribute-free HTML divs with exactly one div child and a div parent. It does not unwrap spans or wrappers with identity, state, or metadata. This mode is tested on fixtures only; keep it off for the initial real-page baseline.
6. Serialize as a complete HTML document with a standard doctype. Parse the actual output again and reject it if preservation checks fail. A byte budget is advisory: return `overBudget`, never clip content to fit.

No heuristically chosen depth cutoff, viewport-only pruning, text truncation, or token target is needed for the initial version. Small HTML fragments can grow because document scaffolding is added.

## Output contract and checks

`downsampleHTML(source, {unwrap: false, targetBytes: null})` returns `{html, report}`. Load the script into an isolated browser JavaScript context; it exposes this function on `globalThis`.

Every successful output passes:

- Exact concatenated content-text equality, including whitespace and template text.
- Ordered element namespace/tag and retained-attribute inventory equality. This checks IDs, label/ARIA references, destinations, and serialized control states, not just counts.
- Expected element count (only script/style subtrees and explicitly eligible optional wrappers can disappear).
- Exact serialization stability after reparsing, detecting new parser repairs in the emitted HTML.

With wrapper collapse disabled, the transform does not reparent retained nodes. Existing duplicate IDs, broken references, or malformed semantics are preserved rather than repaired; this is not a full HTML conformance validator. The retained inventory plus stable parse guards against additional loss, but does not prove accessible-name or screen-reader equivalence.

## Evidence from saved captures

Ran 8 fixture/profile combinations and all 12 saved vision-study HTML captures in local Chromium. Network requests were blocked, and captured HTML was parsed in detached documents without inserting it into the live page or executing its scripts.

All 12 captures retained **100% of content elements** after script/style removal, **100% of remaining text**, and the complete retained attribute inventory. All output documents passed browser parse/serialize stability.

| Capture | UTF-8 byte reduction |
|---|---:|
| Allrecipes | 53.9% |
| Apple | 75.8% |
| GitHub | 30.2% |
| GOV.UK | 27.2% |
| Hacker News | 21.8% |
| IKEA | 82.1% |
| MDN | 4.9% |
| NASA | 36.4% |
| OpenStreetMap | 29.8% |
| Smithsonian | 37.6% |
| W3C survey | 5.5% |
| Wikipedia | 37.2% |

Median reduction: **33.3%**. Aggregate reduction across all input bytes: **57.8%**. These are byte measurements, not tokenizer measurements or navigation-success results.

Inspected emitted snippets for W3C's survey (native headings, label/for association, caption, row/column headers), Hacker News (nested tables and links), and IKEA (heading and labeled controls). The W3C output retains 15 controls, IKEA 243. Fixture coverage includes mixed inline text, repeated list entries, tables, forms, hidden/collapsed content, custom controls, exact preformatted text, SVG, MathML, templates, wrappers, and malformed source.

Artifacts: [audit JSON](../../experiments/dom-downsampling/report.json), [W3C HTML](../../experiments/dom-downsampling/output/w3c-survey.html), [IKEA HTML](../../experiments/dom-downsampling/output/ikea.html), and the other captures in the same output directory.

## Limits and next integration step

This is HTML evidence for reading/model input, not a visually equivalent or functional replacement page. Removing styles/classes can lose pseudo-element content, CSS-driven visibility and layout meaning; removing scripts loses behavior. Hidden source content is deliberately retained. The output is **not a sanitizer**: URLs, embedded resources, and other active content remain. View it as source text or parse it in the isolated, network-blocked runner.

Saved HTML cannot recover live property-only input values, focus, event listeners registered via JavaScript, shadow trees, iframe documents, canvas content, or computed visibility. Relative URLs still need their original document URL. A live adapter should capture those facts in a separate provenance/state record before reduction, with snapshot-scoped action IDs rather than relying on CSS selectors. Do not silently route these raw DOM captures into the benchmark navigator: the existing researcher-only boundary explicitly warns about hidden application data.

Before production adoption, measure tokenizer size, live state/action-target retention, computed accessible names, and task success. Keep the conservative profile as the fallback whenever a more aggressive candidate loses protected evidence or exceeds a predeclared loss allowance.

## Reproduce

From the repository root, using the already installed Playwright and Chromium:

```sh
python3 experiments/dom-downsampling/check.py
node --check experiments/dom-downsampling/downsample.js
ruff check experiments/dom-downsampling/check.py
mypy --follow-imports=skip experiments/dom-downsampling/check.py
```

No new dependencies were added. All listed checks passed. Generated output stays local.
