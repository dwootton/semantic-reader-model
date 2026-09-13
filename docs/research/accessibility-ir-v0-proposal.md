# Accessibility observation IR: proposed v0 contract

Design proposal, 2026-09-12. This is a proposed contract, not an implemented adapter, a finalized standard, or a claim of lossless cross-platform conversion. It builds on [the existing landscape](accessibility-ir-landscape.md) and [project design](project-design.md).

The recommendation is an **ordered containment forest with typed cross-node relations**, using an AccessKit-inspired vocabulary. Keep native captures and provenance beside that graph. Generate a compact, versioned model projection from it. One specification can define all three contracts without requiring a model to consume every archival field.

## Existing work and what to reuse

- **AccessKit is the closest schema foundation reviewed.** It defines roles, optional properties, relations, actions, text, geometry, and updates for accessible UI. Its platform adapters expose application-provided AccessKit trees through operating-system APIs; they are not arbitrary-app UIA/AX importers. Reuse its vocabulary and design, while building capture adapters separately. [AccessKit project](https://github.com/AccessKit/accesskit#how-it-works)
- **Field mapping still requires care.** AccessKit 0.25 distinguishes `label` from `value`; label/text-run content uses `value`. A browser's computed accessible `name` must not simply be renamed to `label`. Preserve the computed name explicitly in the observation contract. [AccessKit Node 0.25](https://docs.rs/accesskit/0.25.0/accesskit/struct.Node.html)
- **ARIA supplies semantics and Core-AAM supplies platform mappings.** They are useful reference vocabularies, not an interchange file format. Platform roles and properties do not always map one-to-one, so reverse conversion needs unknown cases and mapping diagnostics. [Core-AAM comparison](https://www.w3.org/TR/core-aam-1.2/#comparing-accessibility-apis)
- **CDP supplies browser capture evidence.** AXNode has computed name, description, value, properties, children, and optional DOM grounding. Current tip-of-tree includes `actions` and `url` property names, but actual availability must be checked against the pinned browser. DOMSnapshot provides complementary DOM/layout data. [CDP Accessibility](https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/), [DOMSnapshot](https://chromedevtools.github.io/devtools-protocol/tot/DOMSnapshot/)
- **Playwright ARIA snapshots demonstrate a compact textual view.** Their documented role/name/state/indentation format is a useful serializer precedent. It is not a full cross-platform observation archive. [Playwright snapshots](https://playwright.dev/docs/aria-snapshots)

## Changes to the initial six-field node

| Initial field | Proposed treatment | Reason |
|---|---|---|
| `id` | Snapshot-local ID, resolved through a separate grounding map | Short prompt IDs and durable source identities have different lifetimes. |
| `role: string` | Versioned role vocabulary, including structural/content roles and `unknown` | Headings, tables, sections, and paragraphs matter for summarization even when they cannot be activated. |
| `name` | Separate `name`, `description`, `text`, and `placeholder` | A label is different from document content, help text, or an input hint. |
| `value` | Typed current value; separate states and destination | A numeric slider value, checked state, and link URL are different facts. |
| `interactive` | Reported/derived action descriptors, plus enabled state and evidence | Interaction has several forms. Missing capability evidence does not mean noninteractive. |
| `children` | Ordered ID references plus typed relations | Labels, popups, errors, and table headers can cross containment boundaries. |

These distinctions already occur in the local fixtures. In [the preflight AX capture](../../runs/preflight/raw-capture.json), tab `1136` controls a panel through backend DOM ID `1224`, while its only direct child is `1138`. Tab `1155` declares a controls IDREF with no resolved related node. In [the W3C DOM capture](../../examples/vision-study/captures/w3c-survey/capture.json), radio `e110` has submission value `"2"`; label `e111` says `"Central Park"`. [The AX view](../../examples/vision-study/captures/w3c-survey/ax.txt) supplies the computed name and unchecked state. A submission value belongs in native form metadata, while the checked state belongs in `states.checked`.

## Illustrative TypeScript shape

The following is a discussion sketch. Role, action, relation, extension, and evidence registries need machine-readable definitions before this becomes a wire specification.

```ts
type NodeId = string;
type Role = string; // Validated against a pinned registry; includes "unknown".
type Ref = string;  // Key into a capture/provenance/grounding sidecar.

type Value =
  | { kind: "text"; text: string }
  | {
      kind: "number";
      number?: number; // Unknown current value may still have known limits.
      text?: string;  // E.g. "medium" rather than just 50.
      min?: number;
      max?: number;
      step?: number;
    };

type ActionKind =
  | "invoke" | "focus" | "setValue" | "setSelection"
  | "toggle" | "select" | "expand" | "collapse"
  | "increment" | "decrement" | "scroll" | "scrollIntoView"
  | "custom";

interface Action {
  kind: ActionKind;
  name?: string; // Required for custom actions.
  basis: "reported" | "adapterDerived";
  enabled?: boolean;
  evidenceRef: Ref;
  bindingRef?: Ref; // Live adapter route, when available; not a replay guarantee.
}

interface States {
  disabled?: boolean;
  readonly?: boolean;
  required?: boolean;
  focusable?: boolean;
  selected?: boolean;
  checked?: boolean | "mixed";
  pressed?: boolean | "mixed";
  expanded?: boolean | "partial";
  invalid?: boolean | "grammar" | "spelling";
  busy?: boolean;
  modal?: boolean;
}

interface UINode {
  id: NodeId;
  role: Role;
  children: NodeId[];
  childCoverage: "complete" | "partial" | "unknown";
  referenceOnly?: boolean; // Retained relation evidence outside content traversal.

  name?: string;        // Computed/source accessible name.
  description?: string;
  text?: string;        // Owned document text, not descendant text concatenation.
  placeholder?: string;
  language?: string;
  value?: Value;
  destination?: { url: string };
  states?: States;
  actions?: Action[];
  actionCoverage: "complete" | "partial" | "unknown";
  hasPopup?: false | "menu" | "listbox" | "tree" | "grid" | "dialog";

  structure?: {
    level?: number;
    positionInSet?: number;
    setSize?: number;
    rowIndex?: number;
    columnIndex?: number;
    rowSpan?: number;
    columnSpan?: number;
    rowCount?: number;
    columnCount?: number;
  };
  exposure?: {
    accessibilityIncluded?: boolean;
    rendered?: boolean;
    intersectsViewport?: boolean;
  };
  bounds?: {
    x: number; y: number; width: number; height: number;
    space: Ref;
  };
  live?: { politeness?: "off" | "polite" | "assertive"; atomic?: boolean };
  richTextRef?: Ref; // Versioned text runs, range units, selection, embedded nodes.
  provenanceRef: Ref; // Original roles, field evidence, errors, native extensions.
  groundingRef: Ref;  // One-to-many source nodes, ranges, and action routes.
}

type RelationKind =
  | "labelledBy" | "describedBy" | "errorMessage" | "details"
  | "controls" | "owns" | "activeDescendant"
  | "rowHeader" | "columnHeader" | "memberOf"
  | "selectedItem" | "flowTo";

interface Relation {
  from: NodeId;
  kind: RelationKind;
  targets: Array<
    | { node: NodeId }
    | { unresolvedRef: Ref }
  >; // Preserve source order, especially for labels.
  basis: "reported" | "adapterDerived";
  evidenceRef: Ref;
}

interface UIObservation {
  schemaVersion: "ui-observation/0.1";
  snapshotId: string;
  captureRef: Ref;
  roots: NodeId[];
  nodes: Record<NodeId, UINode>;
  relations: Relation[];
  focusedNode?: NodeId;
  coverage: "complete" | "partial" | "unknown";
  relationCoverage: "complete" | "partial" | "unknown";
}
```

## Semantics the specification must fix

**Missing values.** An omitted optional property makes no assertion. `false` means observed false; an empty string means observed empty. A provenance status distinguishes unqueried, unsupported, not applicable, unavailable, and capture failure when known. An empty action list establishes no supported actions only with complete action coverage. Completeness is relative to the declared capture scope, source API, and normalized vocabulary, never all possible application behavior. Counts are nonnegative integers; unknown native sentinels become omitted values with retained source evidence. Normalized positions/indices are one-based and spans positive; adapters record conversions.

**Containment and relations.** Each content node has at most one containment parent; children are ordered and acyclic. Their order is source accessibility traversal order, or an explicitly identified deterministic DOM fallback. It is not asserted to equal visual or tab order. Document/frame/window identity and the chosen containment basis live in the capture manifest. Preserve native DOM and AX ancestry in their respective raw payloads. `owns` records source ownership evidence; do not apply it a second time if the source tree already incorporates ownership. Relation lists preserve order and cardinality constraints; `activeDescendant`, for example, has at most one target. All node targets resolve, while unresolved native references are explicit. Nodes outside the containment forest must be marked reference-only.

**Content.** Do not populate every container's `text` with recursive `textContent`. Keep text at owning leaves/runs and preserve mixed-content order, such as text–link–text. Names may duplicate content because they have different semantics; prompt serialization can omit proven redundant copies. Form value comes from live control state, not necessarily an HTML attribute. Preserve rich text, selection, and embedded objects through a versioned extension before claiming assistive-reader coverage. An input placeholder never silently becomes a label.

**Actions and intent.** UIA control patterns expose capabilities independently of control type, and their availability can change with state. [UIA control patterns](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview) Keep semantic operation, adapter route, and availability separate. The action registry must define request parameter types (e.g. scalar value vs text range vs scroll amount). A `role=button` attribute alone does not establish a working handler. `invoke` establishes an operation, not that it purchases something or permanently saves data. Such purpose claims belong in source-linked interpretations, and observed action effects belong in before/after transitions.

**Exposure and completeness.** Accessibility inclusion, rendering, viewport intersection, clipping, and occlusion are different observations. Do not map UIA `IsOffscreen` directly to a stronger claim of visual invisibility. In a virtualized collection, observed children can be a subset of logical items; record partial coverage and known counts. [UIA virtualization](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-workingwithvirtualizeditems) Coordinate-space definitions must identify units, origins, transforms, and scroll/scale information; retain native geometry where the common rectangle loses information.

**Grounding.** Grounding maps support multiple source nodes per IR node and multiple IR nodes per source node, including text ranges. Use source kind, capture ID, document/frame/tree namespace, and original ID. `e12` can be a prompt-local alias; resolve it through the projection and snapshot before reaching a live handle. Across captures, continuity is separately evidenced. Do not merge nodes from different modalities just because role/name/bounds match. Preserve disagreement and separate candidates when a join is uncertain.

**Observed and inferred facts.** Adapter-derived fields identify their deterministic rule/version and inputs. Model guesses about roles, labels, card membership, or intent live in a separate annotation/projection with evidence IDs. They never overwrite observation fields. Preserve original native values and references for source concepts outside the common registry.

## Capture contract

Use explicit source adapter names such as `chromium-cdp-ax`, `dom-snapshot`, `macos-ax`, and `windows-uia`. “AXDOM” needs the name/version of its actual producer; it is not assumed to be one portable format.

Store original API responses and a manifest recording capture scope, roots, adapter/browser/OS versions, source namespaces, locale, timing, tree view, limits, unavailable subtrees, and errors. Raw means the responses actually captured, not a complete replayable application or access to unmaterialized content.

For a first web adapter, capture browser-computed AX and join DOM/layout evidence through verified native IDs. AX and DOM calls are not automatically atomic; record timing and any detected drift. DOM-only input remains valid with explicit capability gaps. Accessible names can depend on hidden referenced content, so filtering hidden DOM before resolving names loses information. [Accessible name computation](https://www.w3.org/TR/accname-1.2/#computation-steps)

## Model projection and example

A model should receive role/content/state/order/relationship information in a deterministic compact format. Keep raw payloads, source IDs, property diagnostics, and live bindings outside its ordinary prompt. Keep a projection version, short-ID map, and omission accounting so input changes remain traceable in training data.

Illustrative combobox excerpt; referenced nodes appear elsewhere in the same snapshot:

```text
e4 combobox name="Shipping country" value="Canada" expanded=true
  actions=[setValue,expand,collapse]
  labelledBy=[e2] controls=[e9] activeDescendant=[e11]
e9 listbox children=[e10,e11]
e10 option name="United States" selected=false
e11 option name="Canada" selected=true
```

This records three distinct facts that `children` cannot establish alone: what labels the input, which popup it controls, and which option is active. The example's action list is illustrative and must be backed by captured capability evidence in a real record.

For summarization, model outputs should link claims to input IDs. For grouping, predict memberships and label-source references. A “product card” group is a semantic annotation over title/price/action nodes; it is not a new observed native role. Summaries can omit detail while the observation preserves access to it.

Downsampling rules must retain endpoints/context of important relations, or mark explicit omitted references. Never truncate and leave IDs silently dangling. Training and inference use the same serializer contract; full archival richness need not increase prompt length. Record feature availability so a DOM-only example and a richer UIA/browser capture do not teach conflicting meanings for absence.

## Smallest useful validation milestone

Before freezing v0, create field-level adapter mappings and replay fixtures for:

1. An input with an external label, help text, and validation error.
2. A combobox with a popup outside its source container and a changing active option.
3. A table with spanning cells, headers, and offscreen rows.
4. Mixed text with an inline link, plus repeated cards whose buttons share names.
5. A modal/focus transition, nested frame identities, and a partially realized list.

Check ID/reference integrity, containment order, relation direction, critical states and text, action grounding, unknown-vs-false behavior, and declared coverage. Compare semantic facts across equivalent captures rather than demanding identical native tree shapes. Real Windows fixtures are required to claim UIA interoperability; synthetic JSON only validates the contract.

No adapters or executable schema were added by this proposal. Remaining design work is the pinned registries, complete parameterized action/rich-text contracts, source mapping tables, and validation against genuine traces.
