# Compact organizer input

The compactor removes nonreading payload while preserving a **semantic evidence floor**. The 10% original-element target is advisory: controls, record boundaries, names, states, relationships, and short distinct content take precedence. A larger result is reported as a budget miss, never clipped to make the ratio pass.

```sh
python3 experiments/dom-downsampling/compact.py
python3 experiments/dom-downsampling/test_compact.py
```

Current outputs are in `runs/compression/compact-semantic/`. The earlier aggressive outputs remain in `runs/compression/compact-10pct/` for comparison. The runner uses the existing 14 datasets / 15 documents and an isolated browser with network requests blocked; it makes no model calls. Source/input/script hashes bind every artifact to its run.

## What the organizer receives

Each `.request.json` contains the system/user instructions, output contract, reference-attribute name, and one compact HTML representation. Source maps, original snapshots, recovery data, CSS paths, full URLs, embedded assets, and duplicate parent/child arrays stay local. The organizer returns source-backed groups and `needs_expansion` references when more evidence is needed.

## Three profiles

| Profile | Policy |
|---|---|
| `structure` | Remove execution/metadata/assets and unnecessary attributes; collapse unary generic wrappers; preserve branching record boundaries and textual SVG meaning |
| `excerpt` | Also excerpt unprotected long prose and long headings/code with explicit markers; sample long option sets within select/optgroup/datalist |
| `budget` | Also fold only content outside the semantic floor, keeping protected evidence and its ancestor paths even if the 10% target cannot be reached |

All profiles preserve ordinary actions and fields, not only checked or selected exceptions. The floor includes observed control types/values/states, labels and linked help/error text, native and ARIA headings, record/collection/table boundaries, table headers, image descriptions, math/code, definition pairs, complete short statements and list items, and the first paragraph following a heading where present. This is an explicit conservative policy, not a universal inference of which content users consider important.

Generic `div`/`span`/`font`/`center` wrappers with multiple element children remain as source-backed boundaries. No inferred native role is invented. Short lists, recipes, rows, and cards are not sampled away wholesale. Long option sets retain first, second, last, and exceptional choices, native group labels and omission counts; those retained choices survive subsequent budget folding. An ordinary field stays present even when none of its choices is selected.

State and label contexts are protected before excerpting and validated against that earlier evidence. Mixed/disabled/required/expanded states are included. Protected instructions and labels are not prefix-truncated. Other prose has 360-character (`excerpt`) or 180-character (`budget`) limits; long headings allow 512 characters, pre/code/textarea 1,200. Code excerpts preserve whitespace and line breaks, math is not truncated, and shortened owners carry `data-excerpt`. A prefix can omit a qualification, so callers must not treat an excerpt as the full passage.

SVG titles, descriptions, visible text and their necessary containers survive; drawing commands and embedded image bytes remain removed. Scripts, styles, tracking parameters and password values are not added back.

## References, destinations and omissions

- `data-r` (or the collision-free name in the request) identifies source elements.
- `data-target-ref` links a local fragment to an actually emitted source reference. The inspector namespaces this value together with element references. Unresolved or ambiguous targets are marked deferred.
- `data-destination-id` is an opaque destination identity. Different query/fragment destinations stay distinguishable without sending their complete URL. `data-destination` remains only a short descriptive host/path; it is not executable.
- `data-excerpt`, `data-deferred`, `data-folded`, and `data-preview` identify partial evidence. Scope extends to descendants. Previews are source extracts, not semantic summaries.
- `data-omitted-items` counts sampled choice items.
- `data-relations-deferred` names incomplete relationships. Surviving IDREF endpoints remain present; `data-missing-<attribute>` records missing original HTML-ID endpoints separately. These are not source references.

The local source map accounts for every original parsed element and its representing ancestor. References are snapshot-local base-36 IDs, not inspector `eN` IDs. `expandCompact(source, id)` returns raw original HTML for local inspection only. Model-ready expansion still requires filtering, reference binding and request limits; expansion costs must be counted separately.

## Verification and limits

Checks cover stable serialization, reference uniqueness/order, protected control inventory and state, record boundaries, pre-excerpt state/label text, text order through serialization, source disposition, surviving relationships, and embedded payload removal. Budget misses are independent of these checks.

Invalid captured nesting, such as nested NYT links, is normalized through the HTML parser before final serialization. Normalization is accepted only if reference/order, text and protected-inventory checks still pass and the resulting serialization is stable. `serializationNormalized` reports this repair; `sourceRoundTripStable` continues to report whether the original source was stable. Exact original-tree recovery is not claimed.

The implementation has `preservationPolicy: semantic-floor/1`. The compact-input loader requires the new control-inventory and record-boundary checks and verifies all selected artifacts. No computed accessibility names, live CSS state, native action support or joins to unrelated capture IDs are inferred.

## Measured preservation update

All **45 outputs** (three profiles × 15 documents) pass the current checks, including NYT. The updated budget profile retains **21,596 / 34,020 elements**, **5,477 / 5,488 detected controls/links**, and **149,445 / 208,113 content-text characters**. Remaining control-count differences arise before the protected post-cleanup inventory; these raw selector counts include hidden and duplicate variants and are not accessibility-tree counts.

Prepared budget input totals **1,457,860 UTF-8 bytes**, a **52.06% reduction** against the archived legacy organizer baseline of 3,040,991 bytes. This is larger than the old aggressive budget input (203,890 bytes), intentionally preserving evidence that previously disappeared. All 15 budget outputs exceed the requested 10% node target and explicitly report that miss. These are bytes and element counts, not measured model tokens, latency or semantic quality.

The 26 browser regressions include the original ten audited loss patterns, retained dropdown representatives after folding, fragment decoding, and NYT headline/serialization preservation. See `runs/compression/compact-semantic/report.md` for per-document results and `docs/research/compact-semantic-audit.md` for the motivating audit. The previous compactor/report are also archived in `runs/compression/semantic-preservation-baseline/`.

No new organizer-model or user-navigation evaluation has been run for this preservation update. Larger inputs may need regional processing or a larger input budget; the model pipeline must continue to reject oversize input rather than silently truncate it.
