# DOM observation adapter and IR compaction, v0

Design status: proposed, 13 September 2026. This document defines the first implementation slice. It adds no runtime adapter and makes no claim of existing DOM/AX/UIA interoperability. It narrows the [earlier observation proposal](../research/accessibility-ir-v0-proposal.md) into a DOM-first plan.

## Decision

Build two modules with a shared validated observation format:

1. **DOM adapter:** interpret admitted source evidence once, resolving HTML-specific meaning and identities into a source-neutral observation graph.
2. **IR compactor:** select a smaller, explicitly partial view of that graph, using portable roles, states, relations, content, and structural hints. It must not inspect HTML tags, CSS selectors, or raw native payloads.

The model annotates the compact view. It does not decide what native facts the adapter recorded, and it does not modify the canonical observation.

```text
Admitted DOM capture + optional aligned AX/state/layout evidence
               │
               ▼
        adaptDOM(input)
               │
               ├── UIObservation ── compactIR(...) ── CompactView ── encodeModelView(...) ── model
               │                         │                 │
               └── grounding/evidence    └── local ledger  └── explicit gaps / expansion handles
                          ▲                                  │
                          └──── same-snapshot expansion ──────┘
```

**Keep the existing DOM compactor as a baseline during migration.** Port its semantic preservation policy and its regression fixtures, not its HTML mutation machinery. No new dependencies or cloud operations are part of this design.

## Evidence from the current implementation

| Existing implementation | Reuse or change |
|---|---|
| [`compactDOM` setup and source inventory](../../experiments/dom-downsampling/compact.js:37) | Reuse early identity assignment, versioned policy, and source accounting. Canonical IR IDs must not be regenerated for each compaction. |
| [HTML attribute/destination interpretation](../../experiments/dom-downsampling/compact.js:95) | Moves into the DOM adapter. Keep distinct destination identities even when descriptive display paths coincide. |
| [SVG textual evidence](../../experiments/dom-downsampling/compact.js:136) | DOM adapter emits image/vector text and description evidence; drawing payload stays out of the model view. |
| [Generic-wrapper collapse](../../experiments/dom-downsampling/compact.js:151) | Port as a source-neutral transparent-container predicate with stronger relation/focus/geometry guards. |
| [Evidence floor and pre-excerpt expectations](../../experiments/dom-downsampling/compact.js:170) | Preserve the policy, explicitly separate complete content from shell/boundary protection, and compute relation closure before destructive stages. |
| [Budget folding](../../experiments/dom-downsampling/compact.js:249) | Replace element-count scoring with serialized-cost reduction. Preserve the current refusal to sacrifice the evidence floor merely to hit a ratio. |
| [Validation and ledger](../../experiments/dom-downsampling/compact.js:338) | Compare the compact view against immutable adapter output and pre-compaction expectations, not against already-shortened output. |
| [`load_compact`](../../inspector/compact_input.py:277) | Reuse hash verification, document namespaces, explicit partial evidence, and the separation of local provenance from model input. Its strict emitted-HTML parser is not an arbitrary-HTML parser. |
| [Collection compression](../../collection/compress.py:91) | Reuse per-document artifact manifests, aggregate input-limit checks, and `deferred_oversize` behavior. Add the new path behind an explicit format setting. |
| [State capture and verified joins](../../collection/state_capture.py:108) | Reuse observed marker → backend-node → AX correspondences and alignment checks; do not join by matching names or rectangles. |

The older [semantic audit](../research/compact-semantic-audit.md) documents failure cases that motivated fixes. The [current compactor documentation](../../experiments/dom-downsampling/COMPACT.md) describes the later `semantic-floor/1` policy. Do not characterize every historical counterexample as a current bug.

## Scope and exclusions

V0 accepts saved HTML and the existing admitted rendered-capture format. It produces one common contract with different evidence-availability flags. It does not execute page scripts, fetch missing resources, infer missing current values, repair inaccessible controls, or implement UIA/macOS importers. Existing collectors remain responsible for source admission and redaction.

Browser AX is optional enrichment of DOM-backed nodes. AX nodes without a verified DOM match are not silently inserted into DOM containment; record that unmapped coverage and preserve their admitted evidence separately. A future AX adapter can represent those nodes natively.

A capture already missing values, media text, or frame content remains incomplete. No later adapter or compactor may restore deliberately withheld content from an unrelated or unredacted artifact. The collection currently omits freeform values and some media/shadow/frame evidence; see [`state_capture.js`](../../collection/state_capture.js:1) and [`sanitize_ax`](../../collection/state_capture.py:161).

## Small module interfaces

The canonical implementation should be dependency-free JavaScript ESM for graph transforms, with JSON wire contracts for Python collectors and future platform adapters. Browser DOM parsing is confined to the DOM adapter's parsing helper, using the existing isolated Chromium execution path when parsing saved HTML. This keeps browser globals out of the compactor and makes its tests runnable with Node alone.

```ts
adaptDOM(input: DOMEvidence, policy: AdapterPolicy): ObservationBundle
compactIR(observation: UIObservation, request: CompactRequest): CompactResult
encodeModelView(view: CompactView): string
```

`ObservationBundle` contains `{observation, grounding, evidence, audit}`. Only `observation` crosses the compactor interface. `CompactResult` contains `{view, ledger, report}`. Only the encoded `view` and necessary task instructions enter the model request. Helpers for artifact loading and model dispatch stay outside these pure modules.

Errors are typed and fail closed: malformed IDs/graphs, conflicting joins, unsupported wire versions, source-hash mismatch, input-size limit, and failed preservation validation. A valid result exceeding the model budget is a **budget outcome**, not a corrupt observation: return `requires_partition`, never silently truncate or send it anyway.

## Canonical observation contract

### Required skeleton

```ts
type Coverage = "complete" | "partial" | "unknown";
type NodeId = string;

interface UIObservation {
  version: "ui-observation/0.1";
  snapshotId: string;
  documents: DocumentScope[];
  roots: NodeId[];
  nodes: Record<NodeId, UINode>;
  relations: Relation[];
  focusedNode?: NodeId;
  coverage: {
    children: Coverage;
    names: Coverage;
    actions: Coverage;
    relations: Coverage;
  };
}

interface UINode {
  role: Role;
  children: NodeId[];
  text?: string;
  name?: { text: string; basis: "browser" | "explicit" };
  description?: { text: string; basis: "browser" | "explicit" };
  value?: Value;
  states?: States;
  actions?: Action[];
  destination?: { id: string; label?: string };
  labelHints?: Array<{ text: string; basis: "title" | "placeholder" | "source-label" }>;
  language?: string;
  direction?: "ltr" | "rtl" | "auto";
  structure?: Structure;
  exposure?: Exposure;
  bounds?: { x: number; y: number; width: number; height: number; space: string };
  coverage?: Partial<UIObservation["coverage"]>;
}
```

Defaults come from `DocumentScope` and the observation; node coverage overrides them. `complete` always means complete relative to the captured document/scope and the versioned vocabulary, never complete knowledge of the original application. Child absence and missing native behavior cannot become assertions through default values.

The wire schema will expand the following finite registries, rather than leaving arbitrary dictionaries in the implementation:

| Type | V0 content |
|---|---|
| `Role` | A pinned registry covering generic, document, text, lineBreak, paragraph, heading, link, button, textField, checkbox, radio, switch, comboBox, listBox, option, group, form, list, listItem, table, row, cell, rowHeader, columnHeader, definitionList, term, definition, image, figure, caption, code, math, dialog, alert, status, navigation, main, banner, contentInfo, complementary, search, tab, tabList, tabPanel, separator, slider, spinButton, progress, tree, treeItem, grid, gridCell, menu, menuItem, frame and unknown. Original unmatched roles stay in local evidence. |
| `Value` | `{kind:"text", text}` or `{kind:"number", current?, min?, max?, step?, displayText?}`. Units/formatting may remain attached source text. Checkbox/radio submission values do not belong here. |
| `States` | Optional typed disabled, readOnly, required, focusable, selected, expanded, busy, modal, multiSelectable; checked/pressed boolean or `mixed`; invalid boolean or grammar/spelling; current false/page/step/location/date/time/true. No absent→false conversion. |
| `Action` | `{kind, basis:"reported"|"native-semantics"}` with a pinned operation registry: invoke, focus, setValue, select, toggle, expand, collapse, increment, decrement, scroll, scrollIntoView. Live bindings/parameters stay in grounding; v0 does not execute them. A role attribute alone creates no action. |
| `Structure` | level, position/setSize, row/column index/span/count; `boundary:"semantic"|"branching"`; `preserveScope?:true` for a supplied transform/clipping/language/rendering scope that cannot safely be removed; `textMode:"normal"|"verbatim"`; `contentKind:"prose"|"code"|"math"`; optional opaqueContent frame/shadow/media. Fields are deterministic evidence, not inferred product/story classes. |
| `Exposure` | Separate optional accessibilityIncluded, rendered, intersectsViewport, inert, and dormant. `aria-hidden` does not imply visually absent; offscreen does not imply inaccessible. Clipping/occlusion remain unknown unless actually observed. |
| `DocumentScope` | ID, source/parser/capture versions, root IDs, `containmentBasis:"dom"`, content/namespace coverage, coordinate-space definitions, optional relation-scope IDs. Grounding associates every node with its document. |

`name.basis="explicit"` represents admitted direct author naming evidence such as a usable `aria-label`; it is not a claim of a standards-complete computed accessible name. Labelled-by relations remain visible to the model even when offline name computation cannot be established. Native name-from-content may be left as source text rather than guessed into `name`. Browser-supplied empty strings remain known empty; absent names remain unknown.

`value` and current selection/checked/expanded states contain admitted current evidence only. In a saved-HTML profile, serialized `value`, `checked`, `selected`, and `open` are retained as typed local `defaultValue` / `defaultStates` evidence and are not silently promoted to current state. Explicit ARIA state attributes remain author-reported assertions with their basis recorded. A known saved-DOM current-state overlay or verified captured IDL value may populate current fields. Uncertain fieldset-disabled inheritance must not be guessed from absent attributes. Required, type, and explicit read-only semantics can still be mapped from the source under the pinned native rules.

`structure.preserveScope=true` is a portable conservative signal that an adapter observed a semantically significant context transition, not a DOM selector or an inferred semantic group. Its evidence sidecar records the source property. Future adapters may set the same signal for equivalent native scopes. If the source omitted style/layout evidence entirely, geometry-specific fidelity is unknown and must remain a declared limitation rather than an invented guard result.

### Text and containment

Use ordered children as the sole containment authority; derive parent indexes. Emit text nodes for DOM text, so `Pay <a>invoice</a> now` becomes ordered text/link/text nodes. Element aggregates such as recursive `textContent` are never stored as `text` at every ancestor. An image's source alternative can use an explicit name, with its origin retained; captions remain separate related text.

Text-node IDs represent owning DOM text nodes or explicitly mapped ranges. Adjacent source text runs may be coalesced only with a many-to-one grounding record. Use UTF-16 offsets into the exact admitted string snapshot; verify hashes and reject mid-surrogate cuts. Normalization is an explicit view transform, not an unrecorded source edit. Preserve whitespace in code/math/verbatim text; unknown text mode is preserved conservatively.

Frames are opaque frame nodes with missing-content coverage unless their separately admitted documents exist. Captured child documents are separate roots with an `embeds` relation to their host; do not give one node two parents. V0 does not flatten shadow/slot trees and call the result native reading order. Known shadow hosts are opaque when descendants were not captured; absence of a detectable root does not prove there is no closed root.

### Identity, evidence and relationships

Canonical IDs are scoped to `(snapshotId, documentId)`, assigned before interpretation or pruning. Prefer verified capture IDs. For offline HTML, assign deterministic preorder IDs after a pinned browser parse; parser repair is recorded. Identical HTML IDs in separate documents never collide. Duplicate HTML IDs in the same relation scope create an ambiguous reference, not a guessed match. Compaction keeps canonical IDs; serializer aliases are separate and reversible.

Grounding maps canonical node/field/range references to admitted source IDs, exact text ranges, and verified backend/native links. Source IDs and original selectors do not enter ordinary model prompts. A collapsed wrapper's ID does not become an alias for its child: the ledger says where it was represented, while requests for that wrapper still resolve to the wrapper's original observation.

```ts
interface Relation {
  from: NodeId;
  kind: "labelledBy" | "describedBy" | "errorMessage" | "details"
      | "controls" | "owns" | "activeDescendant" | "headers"
      | "labelFor" | "formOwner" | "choices" | "fragmentTarget"
      | "captionedBy" | "embeds";
  targets: Array<{ node: NodeId } | { unresolved: string }>;
  basis: "reported" | "native-semantics";
}
```

The local evidence sidecar explains unresolved keys as missing, ambiguous, unavailable, or redacted. Preserve target order and partial resolution: one broken IDREF must not delete other valid endpoints. Do not apply `aria-owns` as a DOM tree rewrite; record it as a relation. Field-specific missing reasons, original attributes/roles, mapping rule IDs, and conflicts live in evidence keyed by canonical node and field.

## DOM adapter algorithm

### Input profiles

**Saved DOM:** admitted HTML bytes, hash, document/base-URL metadata, parser version, and capture omissions. Parse inertly using the browser parser already used by [`_offline_page`](../../collection/compress.py:44); no navigation, resource fetching, or captured-script execution. Current value, CSS exposure, focus, and full computed names are unavailable unless separately recorded.

**Rendered DOM:** admitted ordered DOM snapshot/HTML plus optional captured IDL state, geometry, focus, and sanitized AX correspondence. Enrichment is accepted only under matching document/snapshot identities and a declared alignment check. An unstable or conflicting join yields `enrichment_rejected` and a DOM-only result, or an error if the caller requires enriched evidence. It must not silently pick one source.

**Legacy compact DOM (migration-only):** already-audited emitted HTML plus its current input manifest. Treat it as a distinct partial input profile. Its omissions are upstream unobserved evidence for this adapter; the new adapter must not join the old local recovery ledger to recreate unseen model evidence. Existing original-HTML and compact-HTML IDs are not interchangeable.

Current [`state_capture.js`](../../collection/state_capture.js:80) stores element IDs but not independent text-node IDs and intentionally withholds some values/media. The new capture-to-adapter parser must recover text order from the admitted HTML only, and mark removed values/media as unavailable. A future collector improvement can add text-run mappings without changing the compactor.

### Ordered passes

1. **Validate and index.** Verify source hashes and sizes; validate document scopes; parse once; assign canonical element/text IDs and index HTML-ID references. Capture raw accounting before excluding nodes. No arbitrary recursive nesting on the call stack for untrusted deep trees; use bounded iterative traversals.
2. **Admit content and account exclusions.** Remove scripts/styles/execution metadata from observation, not by evaluating them. Keep title/language/document context. Preserve SVG title/desc/text nodes while representing omitted vector/media payload explicitly. Dormant template/noscript content is identified according to the known capture environment; if executable/no-script mode is unknown, label the uncertainty rather than asserting rendered absence. Suppressed upstream evidence stays suppressed.
3. **Map roles and local structure.** Use a pinned table of native HTML conditions and valid explicit ARIA roles; invalid/conflicting overrides get diagnostics. Unnamed section/div/span is generic unless valid semantics establish something stronger. Derive heading level, fieldset/list/table/definition/figure structure and a branching-container hint; do not infer product cards. Native disabled inheritance and select semantics require explicit mapping tests.
4. **Resolve relations before filtering.** Record explicit and native label, description, error, ownership, choice-list, fragment, header, and caption relationships. Native label wrapping/`for`, legend/fieldset, caption/table, figcaption/figure, form-owner and datalist relations have dedicated deterministic rules. Account for scope and duplicate IDs. Resolve actual references before deciding which visually hidden nodes can be omitted from a model view.
5. **Attach content, value and state.** Use admitted live IDL state when available; otherwise distinguish default attributes from current value/state. Attribute `value="2"` on a radio remains submission metadata; its human label and checked state are separate. A placeholder stays a hint. Browser AX names enrich only verified matches; preserve declared label sources and conflicts locally. Do not implement an ad hoc full accessible-name algorithm.
6. **Attach capabilities, exposure and layout.** Native affordances may be marked `native-semantics`; verified reported capabilities use `reported`. JS event presence and `role=button` alone do not prove working behavior. Keep action bindings separate. Geometry requires a declared coordinate system and alignment; never normalize offscreen, hidden, and occluded into one boolean.
7. **Validate and freeze.** Check references, acyclic containment, roots, content order, finite values/geometry, role/property constraints, and coverage. Output immutable observation plus audit/grounding. No token budget or model grouping logic runs here.

Native states and roles are more than string substitutions. The implementation should use the pinned [HTML/ARIA mapping guidance](https://html.spec.whatwg.org/multipage/semantics-other.html#concept-html-strong-native-semantics) and [input value semantics](https://html.spec.whatwg.org/multipage/input.html#dom-input-value). Accessible naming can depend on referenced hidden content; [AccName 1.2](https://www.w3.org/TR/2026/WD-accname-1.2-20260827/#computation-steps) is a working draft, not a deployed implementation guarantee. Browser-computed names are preferred when their provenance is valid.

## Source-neutral compaction contract

The full observation never changes. A compact view reuses retained node IDs and source-neutral fields but has a distinct `ui-view/0.1` envelope:

```ts
interface CompactView {
  version: "ui-view/0.1";
  snapshotId: string;
  observationHash: string;
  policy: "organizer-floor/0.1";
  profile: "structure" | "excerpt" | "budget";
  scope: { roots: NodeId[]; context: NodeId[] };
  roots: NodeId[];
  contextRoots: NodeId[];
  nodes: Record<NodeId, ViewNode>;
  relations: ViewRelation[];
  gaps: Gap[];
  coverage: Coverage;
}

type ViewChild = { node: NodeId } | { gap: string };
type ViewEndpoint = { node: NodeId } | { gap: string } | { unresolved: string };
type ViewText =
  | { kind: "complete"; value: string }
  | { kind: "extract"; parts: Array<{ text: string } | { gap: string }> };

interface ViewNode extends Omit<UINode, "children" | "text"> {
  membership: "owned" | "context";
  children: ViewChild[];
  text?: ViewText;
}

interface ViewRelation extends Omit<Relation, "targets"> {
  targets: ViewEndpoint[];
}
```

Every retained node/field is observed or a labelled extract; compaction does not manufacture semantic summaries. Ordered child-gap entries mark the exact position of omitted runs: `[node A, gap G, node C]` cannot be mistaken for originally adjacent A/C. Extract text parts likewise preserve where missing text precedes, follows, or separates supplied text. Original offsets/text hashes stay in the ledger. A source node and an omission ID have disjoint namespaces. A view relation endpoint either resolves in `nodes` (including reference-only context) or refers to an explicit unresolved/gap handle; the type unions forbid confusing them.

Every node explicitly declares owned/context membership; context status applies to all included dependency descendants, not just their roots. Context nodes are read-only evidence and cannot become model-owned group members. `contextRoots` identifies disconnected reference-only evidence trees; every node is reachable once from either `roots` or `contextRoots`. Owned nodes are never duplicated under context trees: trim overlapping context containment and preserve original ancestry in local lineage. `scope.context` enumerates all context IDs and must agree with node membership. Regional slicing is a view operation, not a change to observed containment. Do not let a region silently appear to be an independent whole page.

### Gap and local ledger

A gap identifies `{id, owner, field, reason, omittedNodes?, omittedItems?, omittedCharacters?, expansion}`. `field` distinguishes text, children, relation, media and upstream evidence. Counts refer to the captured observation, not total unseen application content. `expansion` is `local` only when the omitted material exists in this admitted snapshot; upstream redaction/unavailable frames are `unavailable`. Text gaps retain original range offsets locally. A prefix preview is marked extract/partial and never counted as complete content.

One ledger entry per canonical node records `retained`, `collapsed`, `deferred`, `excluded`, or `reference-only`, with reason and representing view node/gap. Field-level changes have their own entries. Source-exclusion accounting remains in the adapter audit; view exclusions cannot erase it. Keep all ledger/original range text outside the model request.

## Compaction algorithm

### Pass A — index and protect

Build parent, preorder, subtree-span, reverse-relation, and structural indexes once. Derive an immutable evidence floor before any shortening. Store fingerprints of protected content/states/relations against this pre-compaction observation.

Use protection strengths instead of a single boolean:

- **Shell:** node identity, role, states, capabilities, relation endpoints, ordered retained child positions and coverage remain. This protects form/collection/record boundaries without forcing every long body to be included.
- **Complete field/content:** the named field and its supporting source runs cannot be excerpted or folded.
- **Path:** required ancestor chain retained until it can be safely collapsed by the transparent-wrapper rule.

Start from all in-scope controls/fields, focus/current/selected/invalid/expanded exceptions, alerts/status, heading/label/title evidence, figure descriptions, table headers, math/code, and explicit required refs from a caller. Preserve ordinary controls, not just exceptional states. Use the current 360-character short-content threshold to protect complete short paragraphs/list items/cells; protect first-paragraph-after-heading context and form instructions conservatively. This threshold is an explicit versioned policy, not semantic importance detection.

"In scope" here includes accessible/rendered evidence and nodes whose exposure is unknown; it excludes known dormant/inert content from ordinary traversal unless it supplies required relations or the caller explicitly requests that scope. Visual `aria-hidden` content can still be in scope as visual evidence. A focus record that conflicts with dormancy is retained with a conflict diagnostic, not discarded.

Retain shells for all observed record/collection/table/form/fieldset/definition boundaries, and branching generic containers. Do not sample recipes, form questions, filter categories, short lists, or table rows in v0. Preserve local qualifier text as complete short units; no heuristic claims that an arbitrary long disclaimer's prefix is sufficient.

Compute relation closure with a work queue until fixed point. Label/help/error/caption/header dependencies require complete textual evidence, including descendant text when no computed name exists. `details` used as help receives the same protection. Controls/ownership/active-descendant/choices dependencies preserve target shells and necessary identity/state, with named option text protected for exposed choices. Preserve all known endpoints and unresolved diagnostics. Relation cycles terminate by visited `(node, protection-level)` pairs. If closure protects a large part of a page, accept a budget miss rather than weakening it. References outside the active region become reference-only context with the same dependency rules.

### Pass B — structure-only reductions

Remove only adapter-classified execution/nonreading payload or dormant content from normal traversal, with explicit evidence availability; relation-required nodes remain as reference-only context. Keep raw source evidence local.

Collapse a generic container only when all are true:

- zero or one meaningful child, no own meaningful text;
- no name/value/description/hint, state, action, or destination;
- not a root, record/collection/field/table/figure boundary, relation endpoint, focus target or requested expansion target;
- no distinct supplied geometry/transform, clipping, language/direction or text-mode scope that would be lost.

Splice its child into the same position. Retain original identity in the ledger. Do not collapse branching generic containers or globally deduplicate repeated names/URLs. Repeated content may represent different records or editorial occurrences.

Whitespace normalization is allowed only in explicitly normal text, preserving word separators around inline elements. Names remain separate from text. Exact duplicated scalar strings may share serializer storage internally, but dropping one semantic field because its text equals another is not a v0 transform.

`structure` finishes here with no budget-driven evidence deferral. It can still be partial because the original capture was partial or its explicitly dormant/media content is omitted from normal traversal.

### Pass C — bounded prose and native choice previews

`excerpt` and `budget` may shorten only unprotected long text. Initial defaults match the existing compactor: 360 characters for excerpt prose, 180 for budget prose. Use Unicode-safe source-range cuts and explicit partial markers; preserve verbatim formatting. Do not excerpt names, short qualifiers, label/help/error dependencies, code/math, or protected heading context in v0. Long protected content can force partitioning. This deliberately tightens the existing permission to excerpt some long headings/code.

Choice sampling is restricted to an actual option collection whose adapter established choice semantics. Keep field/optgroup shells, first two and last choices, selected/active/disabled choices, and any required relation endpoints; preserve sampled choice identities through every later pass. Display exact omitted-choice counts and an expansion handle. Do not generalize this to recipes or distinct content lists. If every option is protected, keep every option.

Ordinary unselected option nodes inside those collections are not independently seeded as mandatory controls merely because selecting an option is a possible action. Their collection shell is mandatory; the listed representatives/exceptions are mandatory. A direct `owns`, `activeDescendant`, label/header relation, or caller-required ref to an individual option still protects that endpoint. A `choices` relation to a list shell does not imply that all child options are individual endpoints. If the captured relation enumerates all options as endpoints, keep all of them in v0. Thus sampling never converts a required known relation endpoint into an invented replacement.

### Pass D — cost-aware budget planning

`CompactRequest` declares scope roots, optional required refs, policy/profile, and an **absolute UTF-8 byte limit** for `encodeModelView(view)`. An optional exact tokenizer callback identifies its tokenizer/version and counts the exact encoded request including fixed prompt overhead and reserved output capacity. The result reports bytes and tokens separately; bytes must not be relabelled tokens.

Node ratio remains a diagnostic only. The default migration budget comes from the existing `max_input_bytes`, with the encoding/overhead scope stated explicitly. No 10% target may override the evidence floor.

Candidate folds are source-backed subtrees or owned text bodies outside the floor. Retain their boundary shell plus a gap. V0 pins retention weight to 4 for a named or semantic-boundary candidate, 2 for other candidates within two containment edges of supplied focus, and 1 otherwise; use the larger applicable weight. These are explicit heuristic policy constants, not fitted importance scores. Scores use estimated encoded byte savings divided by that weight; compare rational scores without rounding, then tie-break by source preorder and canonical ID. No site-specific class names, visual-importance guesses, or model calls are allowed.

For v0, use batch size 1: try the highest-ranked candidate in a provisional view and serialize the full result. **Reject zero/negative actual savings**, restore that candidate, and mark it exhausted for the current view revision. Accepting a fold removes descendant candidates; affected ancestor candidates are recomputed. Candidates with overlapping descendants cannot be applied simultaneously. Never loop on a fold whose metadata is larger than its savings. Pin a maximum of 256 full candidate evaluations per view; an accepted mutation may invalidate previous estimates, but does not reset the total evaluation count. This policy limit is reported and versioned.

Indexing is O(N + E), candidate scheduling can use a priority queue, and full verification/serialization costs at most 256 passes over a view for this first implementation. Do not advertise O(N log N) end-to-end complexity while exact serialization/tokenization remains in that loop. A future optimization must preserve the decisions on frozen fixtures or use a new planner version. Reaching the evaluation limit returns the best valid view with `requires_partition` if still oversize; wall-clock timing must not change output selection in deterministic runs.

When optional token counting is provided, final exact token budget must also pass. If the byte-sized candidate still exceeds tokens, continue positive-byte-saving candidates in the same fixed order while checking final token cost; no feasible guarantee is made. The dispatcher sends only results with a validated budget for its actual model request. A bytes-only report does not promise a particular tokenizer fit.

If the floor still exceeds budget, return `requires_partition` with a deterministic plan over record/section/row boundaries. Preserve needed ancestor/heading/relation context in each region, identify owned versus context IDs, and report total duplicated context and total requests. A single oversized indivisible protected unit remains `unrepresentable_under_budget`; require a larger budget or a different explicitly approved projection policy. Do not break it by hidden truncation.

Partition planning is deterministic depth-first splitting: attempt the requested root with required dependency closure; if too large, recurse through its source-ordered children while respecting indivisible mixed-content reading units, table rows, options, and protected field/help bundles. Prefer an existing semantic/record boundary when it fits; otherwise recurse, rather than invent a region label. Pack consecutive fitting units greedily under their same source parent, recomputing closure and exact serialized cost for each addition. A unit that cannot be separated from an oversized dependency component returns an unsatisfied result. Limit the plan to 64 regions and 512 candidate-region closure/serialization trials per request in v0, separately from the 256 fold-evaluation limit. Cache identical trial scopes; cache hits do not consume trials, and the logical sequence is fixed regardless of cache presence. Hitting either partition limit reports remaining unplanned source scopes and `limit_reached`. No omitted region is silently declared processed.

### Pass E — validate and encode

Validate graph/references, complete protected fields, all control states, record separation, mixed text order, sampled representatives, omission accounting, positive achieved savings, and budget status against the immutable observation. Recompacting the same observation/options is byte-deterministic; do not promise `compact(compact(view))` equivalence because a compact view is not an observation.

The initial model encoding is compact JSON with one representation of containment: ordered roots and ordered child IDs, no duplicate parent arrays. Roles/field names come from the pinned registry. Short node aliases, omission aliases, and destination aliases are assigned in deterministic view preorder; relation-only context follows a canonical order. The local alias map binds them back to canonical IDs and snapshot hash. Source provenance, original selectors, full destination URLs, removed text, and the full omission ledger never enter the ordinary model request. Model input includes enough inline gap/partial metadata to avoid claiming complete evidence.

Do not optimize into an opaque tuple/token code before measuring. The first experiment should compare ordinary compact JSON with current compact HTML at equal preservation and equal request budgets. A later encoding change gets a separate codec version and tokenization test.

Model instructions treat all encoded source strings as untrusted data. Source text cannot request new tools, alter the protection policy, grant collection authority, or change the output contract. Proper JSON encoding prevents structural injection; the instruction/data trust rule is still necessary because a valid string can contain adversarial instructions. Test hostile text containing fake IDs, markup, or requests to expose omitted source without executing any of it.

## Worked behavior

Given admitted source:

```html
<div><div>
  <fieldset><legend>Shipping address</legend>
    <label for="zip">Postal code</label>
    <input id="zip" aria-describedby="help" aria-errormessage="error" aria-invalid="true">
    <p id="help">Enter the postal code for the delivery address.</p>
    <p id="error">Postal code is required.</p>
  </fieldset>
</div></div>
```

The adapter emits generic wrappers, a named/evidenced field group, label and text nodes, an input, help/error text, and explicit label/help/error relationships. It does not assume an empty current input value from the missing `value` attribute. If browser AX supplies a verified name, it can attach that reported name.

The compactor can remove the two transparent wrappers. It retains the field, legend/name evidence, complete label/help/error, invalid state, and relationships. A 300-byte limit may be impossible: the correct outcome is a valid over-budget result marked `requires_partition` or `unrepresentable_under_budget`, never an apparently complete “Shipping address” heading with the input deleted.

For `Pay <a href="/invoice/7">invoice</a> now`, text/link/text ordering survives. For two cards that both say “Buy,” record boundaries and separate destination/action identities survive. For a long option list, a preview explicitly declares omitted options and can be expanded from the same admitted observation. For a canvas/map, native controls and supplied alt/description survive, but pixels do not turn into new DOM action targets.

## Expansion and model-output grounding

Expansion requests refer only to gap/IR IDs from the current view and snapshot. The local controller resolves them against the immutable admitted observation, re-runs `compactIR` for that scope with required refs, and revalidates the actual request budget. It returns another view with the same canonical identities and a newly versioned alias map. Never return raw `outerHTML` to the model: [`expandCompact`](../../experiments/dom-downsampling/compact.js) is currently a local-inspection capability, not a safe model expansion path.

An unavailable/redacted gap cannot be satisfied by expansion. Expired live state needs a new capture; do not reuse an old action handle or merge new state into old snapshot IDs.

Model annotations must state whether a source reference denotes one node or a source subtree. Existing [harness grouping](../../harness/projections.py:98) and [inspector membership](../../inspector/comparison.py:293) use different conventions. The new input cannot silently unify their output meanings. V0 caller integration must select an explicit output contract, preserving the existing `compact-anchors`/`compact-selection` behavior as separate experiments until migrated.

## Implementation placement and migration

Proposed new directory (not yet created):

```text
ui_ir/
  schema/observation-v0.schema.json, view-v0.schema.json, registries-v0.json
  validate.mjs            # Contract, graph, field, relation checks
  dom/parse.mjs           # Inert browser DOM -> deterministic source records
  dom/adapter.mjs         # Records + admitted enrichment -> ObservationBundle
  compact.mjs             # Source-neutral planner; no document/DOM APIs
  codec.mjs               # Deterministic model JSON + aliases
  fixtures/              # Small synthetic portable cases
```

Use plain data and small pure functions. Do not introduce a plugin registry, abstract superclass hierarchy, or dependency container for hypothetical future adapters. The DOM adapter has two concrete source profiles now. A future UIA adapter satisfies the same wire contract and reuses the compactor without adding HTML knowledge to it.

Integrate through `input_mode="ir-v0"` only after parity tests. Preserve current compact HTML and AX harness paths; do not replace them during initial development. [`collection/compress.py`](../../collection/compress.py:91), [`inspector/compact_input.py`](../../inspector/compact_input.py:277), and [`inspector/compact_comparison.py`](../../inspector/compact_comparison.py:220) are the first integration points. The inspector should show full IR versus compact IR with the existing grounding/cross-highlight mechanisms; it must not render omitted source as though the model saw it.

Persist `observation.json`, `grounding.json`, `adapter-audit.json`, `view.json`, `compaction-ledger.json`, `compaction-report.json`, `model-input.json`, and the local alias map, each hash-bound to its producer version/source. These files contain admitted capture-derived data and inherit the project's local-only publication restrictions.

## Acceptance and measurement

The implementation plan and fixture matrix are in [.omx/plans/dom-ir-compaction-v0.md](../../.omx/plans/dom-ir-compaction-v0.md). Acceptance requires deterministic bytes, no dangling references, complete protected-field preservation, disjoint control/record identity, exact omission accounting, model-budget refusal, and no extra network or original-script execution. Real capture parity is measured only on identical admitted source evidence; do not compare a richer new browser capture against an older redacted HTML artifact and attribute the gain to compaction.

Report adapter/compactor/serialization latency separately, exact bytes, tokens when actually measured, peak memory, protected evidence retained, omitted bodies/items/relations, budget misses, region counts, and total context duplication. Include the full 14-capture local corpus when present, plus synthetic regressions that run in a clean checkout. Improvements in token cost or node count do not establish reader utility; model quality and blind-reader testing remain later evaluation stages.

## Alternatives and tradeoffs

- **Keep compact HTML as the only IR:** fastest integration, but UIA/AX would need HTML-shaped semantics and inherit DOM-specific rules. Retain as baseline, not the shared contract.
- **Use the full AccessKit schema directly:** useful if native accessibility export becomes a requirement, but the capture/partial-evidence model still needs additions and import mappings. Reuse vocabulary; avoid claiming a source-role/name rename is lossless conversion.
- **Normalize first into the small observation/view split:** chosen. More upfront typing and mapping work, but one preservation/omission/budget implementation can serve future adapters, and capture errors stay distinguishable from compaction/model errors.

The main cost is larger honest inputs: preserving ordinary controls, short item identity, labels, and relations may exceed an aggressive size target. The deliberate response is scoped processing or larger budgets, not a weaker undocumented evidence floor.
