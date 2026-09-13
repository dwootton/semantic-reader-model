# Semantic audit of compact organizer input

Audit date: 2026-09-12. Scope: the existing `compact.js` transform, its three saved profiles, the test suite, and the compact inputs used by the regional organizer. The compactor and its production behavior were not changed. No model or cloud calls were made for this audit.

## Verdict

The current **budget** profile is useful as a coarse expansion outline, but it removes too much evidence to be the sole input for meaningful regional organization. It often retains a section heading while removing the fields, actions, objects, or relationships that explain the section. Marking an omission is valuable, but does not replace the omitted evidence.

The largest losses occur in global budget folding and list sampling, rather than prose excerpting alone. Some cheaper structural reductions also need correction: useful record boundaries, local link targets, native select labels, and SVG text can disappear even in `structure` mode.

Recommended direction: preserve a compact inventory of meaningful units and their relationships, then defer their long bodies. Keep the 10% element ratio as a diagnostic rather than allowing it to override the evidence needed by the organizer.

## Measured tradeoff

The matched table below uses **13 datasets / 14 documents** whose three profile audits all pass. NYT is excluded here because its structure/excerpt outputs fail parse stability; its artifacts remain useful diagnostic evidence. EWH's two document requests are summed against its one archived legacy organizer request.

| Profile | Organizer input bytes | Reduction versus archived legacy input | Detected controls/links retained | Content text retained |
|---|---:|---:|---:|---:|
| Legacy normalized input | 2,824,952 | — | Different representation; not a count baseline | Different representation |
| Structure | 1,092,047 | 61.3% | 4,323 / 4,326 = 99.93% | 99.95% |
| Excerpt | 745,854 | 73.6% | 2,716 / 4,326 = 62.8% | 71.3% |
| Budget | 167,299 | 94.1% | 489 / 4,326 = 11.3% | 9.0% |

Bytes count the archived system/user requests, not model tokens. Control counts use the compactor's HTML selector and include hidden elements and repeated responsive variants; they are not visible-control or accessibility-tree counts. Text percentages exclude preview strings, which are tracked separately (5,831 preview characters in this matched budget subset). High retention of text and controls does not establish preservation of their associations.

All 45 candidate artifact sets were checked against recorded sizes and hashes (180 artifact references, including repeated source snapshots). Current compressor and runner hashes match the report. Machine-readable totals and per-document comparisons are in [summary.json](../../runs/compression/semantic-audit-20260912/summary.json).

## Findings and what to add back

### 1. Ordinary fields and primary actions disappear

**High priority; observed in real captures.** GOV.UK retains “Apply online” but drops the “Start now” action (`6s`). W3C Survey retains its form and legends but drops every field, field label, and submit control. OpenStreetMap loses its From/To fields and named map tools such as Zoom In, Layers, and Share. These elements survive the lighter profiles.

The exception selector protects checked/selected/current/invalid/alert cases, not a normal unselected field. A form's lower folding priority applies only when the form itself is the candidate; a larger ancestor can still remove it. [Selectors and folding](../../experiments/dom-downsampling/compact.js#L30)

**Add back:** a field/action inventory for each in-scope region: source reference, control type, observed label/name evidence, current value/state, required/optional instructions, label/help/error relationships, and primary/submit/cancel actions. Fold long choice lists inside fields; retain the identity of the field. For explicitly inactive regions, a named deferred control inventory may be sufficient; do not indiscriminately restore hidden or duplicate controls.

### 2. Useful record boundaries are erased before budgeting

**High priority; observed and reproduced.** Generic multi-child `div`/`span` wrappers are flattened after class removal. IKEA product title, price, offer terms, cart action, and stock evidence consequently become flat siblings. A synthetic pair of cards becomes one flat heading/price/button sequence while the audit passes. [Wrapper collapse](../../experiments/dom-downsampling/compact.js#L133)

**Add back:** one source-backed boundary around candidate records, especially repeated cards, rows, stories, and field bundles. Collapse unary presentation wrappers, but preserve branching boundaries that associate multiple meaningful children. Preserve the original generic tag or mark it as a grouping candidate; do not invent a native semantic role.

### 3. Headings survive while reading units disappear

**High priority; observed.** Budget folding removes NYT's paragraph-based story headlines, teasers, and destinations while preserving editorial `h2` headings. Allrecipes loses ingredients and directions beneath surviving section headings. MDN loses tutorial title-description pairs. The model receives category names with little evidence of the things in those categories.

**Add back:** an item/title reference inventory for every retained collection, plus coherent representative records. Preserve linked story titles and source-backed candidate titles even when they are paragraphs. Keep title, price/value/units, qualifications, byline/date/genre, destination/action, and useful alt/caption associations where present. These should remain attributable to the same original record.

Preserving every long body is unnecessary. Preserving what each item is and how its parts belong together is essential for this task. NYT's failed structure/excerpt audits must be repaired before either becomes a deployment baseline. [Reading-unit evidence](compact-audit-reading-units.md)

### 4. Sampling treats short distinct items as disposable repetition

**High priority; observed.** Allrecipes' seven ingredients are sampled down to flour, baking soda, and bananas, dropping salt, sugar, butter, and eggs. IKEA filter categories are reduced to three. In other cases the later budget pass removes even the representative items retained by the excerpt pass.

**Add back:** all short distinct choices/categories and complete short enumerations. For long repeated collections, retain every item's compact identity/title and count, with full records for representative or important items. Keep sampled table rows with their column headers. Sample inside `optgroup` while retaining its native `label`, group identity, count, and selected options; the current allowlist strips that label and the sampler misses options nested inside groups. [Sampling](../../experiments/dom-downsampling/compact.js#L186)

Sampling remains appropriate for a declared preview task, but a sampled recipe or questionnaire must not be treated as complete regional evidence.

### 5. One prefix preview misses the facts that distinguish sections

**High priority; observed.** GOV.UK's main preview is spent on its introduction, while the urgency alternative, travel warning, and debit/credit-card prerequisite disappear. W3C loses “Fields are required if not otherwise noted” even though it retains the optional newsletter legend. OpenStreetMap's map preview contains scale/copyright text, but its useful actions were named in attributes rather than `textContent`.

**Add back:** a short content span associated with each heading/fieldset, complete short instructions and qualifiers, and compact descriptions of named controls. Protect complete short label/value/unit and condition-bearing statements rather than always taking a leading prefix. Where a long passage is excerpted, preserve the partial marker and make expansion available before conclusions requiring the omitted text.

### 6. Relationship and destination distinctions are removed

**Medium priority; observed and reproduced.** `#content` and `#page` become the descriptive destination `/` even when their target elements survive. Distinct search-query destinations can collapse to the same path. If one IDREF endpoint is missing, the compactor deletes the entire relationship attribute, including its surviving endpoints. [Destinations](../../experiments/dom-downsampling/compact.js#L104), [IDREF cleanup](../../experiments/dom-downsampling/compact.js#L251)

**Add back:** validated in-page target references; distinct destination identities; preserved known IDREF endpoints with explicit metadata for missing endpoints. Preserve short semantically relevant destination distinctions where supported, without restoring tracking strings or embedded assets. A missing relationship should identify what evidence is deferred, not merely name the removed attribute.

### 7. Some protection rules and checks miss semantic loss

**High priority for correctness; reproduced synthetic cases.** Ten small counterexamples all return `report.passed=true` while losing evidence:

- A long alert loses the final “Do not submit another payment” instruction. `stateContextPreserved` still passes because its expected text is recorded after excerpting.
- An ancestor fold removes a form, math, or code even though some of those elements are excluded as direct folding candidates.
- An ARIA heading and an `aria-checked="mixed"` checkbox are omitted.
- SVG processing retains only the first available title/description and removes visible SVG text.
- Long preformatted excerpts normalize away line breaks.
- Useful wrapper, destination, and partial-IDREF distinctions disappear as described above.

**Fix:** compute protected evidence before destructive stages; propagate protection through ancestor-fold decisions; include the relevant role/state equivalents; preserve SVG textual meaning while removing geometry; retain preformatted whitespace. Compare protected labels, help/error text, and states against the pre-excerpt evidence. [Detailed rule audit](compact-audit-rules.md)

The existing eleven tests pass. Some intentionally affirm a partial outline, including a form with zero remaining fields. Those tests are appropriate for the documented encoding contract, but do not establish that the result is sufficient for semantic organization.

## Proposed semantic preservation floor

Before permitting a fold, ensure the model-visible representation retains:

1. The identity and boundary of each meaningful in-scope record or region.
2. Distinguishing titles/names and short value/unit/qualification associations.
3. An inventory of its relevant actions and fields, with observed states and label/help/error relationships.
4. Collection identity/cardinality, short distinct options, and table-header context for exposed values.
5. Explicit omitted-content and deferred-relationship descriptions, with stable source references.

This is a proposed policy to validate, not a claim that these rules alone guarantee good hierarchies. Do not infer source facts or computed accessibility properties absent from the saved capture.

## Recommended next implementation order

1. Fix structural losses that are cheap to avoid: record boundaries, native option-group labels, local-target relationships, inherited protection, and the pre-excerpt state check.
2. Add field/action and item/title inventories, then per-heading content context. Keep ordinary controls as well as exceptional states.
3. Use a light, structure-preserving input for the region currently being organized. Use aggressive budget outlines to locate regions and request further evidence. Do not rely on the outline alone for a complete reading view.
4. Implement bounded model-safe expansion by reapplying filtering and stable references to the requested source scope. `expandCompact` currently returns raw local-inspection HTML and must not be passed straight to the model. Include every additional request in latency and token totals.
5. Compare the current budget profile with the revised preservation policy on matched saved interfaces and the same organizer model. Measure correct reading-unit associations and essential-access failures, not merely retained nodes or validator success. Repeat local timing after the changes.

Our current GOV.UK regional run spent about **2 seconds processing input and 26 seconds generating output**. Further sacrificing essential input would target the smaller measured cost while making labels harder to ground. Adding evidence can still increase generated output and total time, so the next comparison must measure both. No latency or model-quality improvement from these proposed add-backs has been measured.

Keep removing scripts/styles, execution payloads, base64 assets, tracking noise, redundant edge arrays, and repeated aggregate text. Full CSS, complete URLs, and SVG geometry are not blanket add-backs; use small source-backed grouping or text features when those carry meaning.

## Evidence

- [Forms, actions, and navigation](compact-audit-forms.md)
- [Reading units, cards, and content](compact-audit-reading-units.md)
- [Rule and test blind spots](compact-audit-rules.md)
- [Measured profile totals](../../runs/compression/semantic-audit-20260912/summary.json)
- [Ten synthetic counterexamples](../../runs/compression/semantic-audit-20260912/counterexamples.json)
- [Counterexample reproduction script](../../runs/compression/semantic-audit-20260912/reproduce_cases.py)
- [Artifact hash manifest](../../runs/compression/semantic-audit-20260912/manifest.json)

Synthetic cases demonstrate deterministic transformation losses, not their frequency in real interfaces. Real captures here are static and can include inactive or duplicated elements. No assistive-technology user study or new organizer-model evaluation was performed in this audit.
