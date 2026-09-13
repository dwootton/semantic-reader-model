# Accessibility IR precedents: reuse boundaries

Primary sources checked 2026-09-12. This supplements [the existing landscape](accessibility-ir-landscape.md), focusing on schema details and compact model-facing formats. AccessKit references are pinned to 0.25.0; Chromium, CDP, Playwright, and BrowserGym sources below describe their reviewed development heads, not a promise about installed releases.

**Recommendation:** reuse AccessKit's vocabulary and design lessons for a rich normalized observation graph; build the capture adapters, evidence envelope, and deterministic training projection. Treat compact agent snapshots as projection baselines. None of the reviewed projects documents an already complete DOM + browser AX + arbitrary native UIA import pipeline with archival provenance and a universal model-training contract.

## AccessKit is the closest schema precedent

AccessKit defines cross-platform UI nodes and actions, largely based on Chromium's accessibility abstraction. Rust is canonical; Serde supports serialization, and other language/schema representations can be generated. Its documented flow is application/toolkit → AccessKit → platform accessibility API. The platform adapters expose UIA, NSAccessibility, AT-SPI, and other APIs; these are provider adapters, not documented arbitrary-app tree importers. The consumer library consumes AccessKit trees. The README also explicitly limits adapter property/element coverage. [AccessKit architecture and scope](https://github.com/AccessKit/accesskit#how-it-works)

The 0.25.0 `Node` includes ordered children, actions, bounds/transforms, text/selection, table/list metadata, and cross-references including `labelled_by`, `described_by`, `controls`, `owns`, `flow_to`, and `active_descendant`. A consequential detail: `label` is ARIA-label-like, while text content of Label/TextRun nodes uses `value`; a linked label need not also populate `label`. `url` is separate. Therefore CDP's computed accessible name is not simply AccessKit's `label` under another spelling. Preserve computed name and its origin explicitly in an observation-oriented envelope. [Pinned Node schema](https://docs.rs/accesskit/0.25.0/accesskit/struct.Node.html)

`TreeUpdate` separates node IDs from node contents and carries tree identity and focus. Updates replace complete node records; omitted unchanged properties within a replacement are not automatically retained. Tree initialization and subtree grafting have explicit invariants. This is a useful incremental-state precedent, but importing partial observations requires additional completeness/error semantics. [Pinned TreeUpdate contract](https://docs.rs/accesskit/0.25.0/accesskit/struct.TreeUpdate.html)

**Reuse decision:** adopt a pinned semantic subset or wrap an actual AccessKit payload where the consumer stack benefits. Do not fork or reproduce the full schema before testing source mappings. An observation import layer still needs source-native extensions and explicit unknown/unsupported states.

## Chromium offers the mature internal design and practical web source

Chromium `AXNodeData` stores ID, role, state, actions, typed sparse attributes, child IDs, and relative bounds. It demonstrates that a universal node record can remain sparse while carrying richer information than role/name/value. It is internal C++ infrastructure, not a lightweight cross-platform capture API. [AXNodeData declaration](https://chromium.googlesource.com/chromium/src/+/HEAD/ui/accessibility/ax_node_data.h)

CDP's `AXNode` exposes computed name/description/value, ignored reasons, parent/children, frame identity, and an optional DOM backend ID. `AXValue` can retain computation sources and related nodes. Relations are not limited to containment. Current tip-of-tree property vocabulary includes both `actions` and `url`; capture support must be checked against the actual browser/protocol version. Availability of a property name alone does not demonstrate a working action executor. [CDP Accessibility types](https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/#type-AXNode)

**Reuse decision:** use CDP as an initial browser source and preserve its original payload. Retain provenance when translating its computed semantic properties into a common vocabulary.

## Playwright already implements a close compact projection

Public ARIA snapshots use YAML with role, accessible name, selected states, nested text, and link URL. They are designed for structural tests; whitespace is normalized and comparison is order-sensitive. This is a concrete precedent for a compact serialization similar to the proposed `DownsampledNode`. [Playwright snapshot documentation](https://playwright.dev/docs/aria-snapshots)

The reviewed implementation constructs this representation from DOM and role/name utilities. Its internal `ai` mode adds element refs, visible generic elements, active state, pointer hints, and optional boxes. It keeps element/ref maps and name-contributor refs. Ref assignment can change when the same element's role or name changes. Rendering selectively omits false states, and duplicate name/text content may be removed. Consequently this is a derived projection with its own semantics, not an archival dump of the browser's native AX tree or a durable cross-session identity scheme. The internal mode should not be treated as a stable public API. [Playwright snapshot implementation](https://github.com/microsoft/playwright/blob/main/packages/injected/src/ariaSnapshot.ts)

**Reuse decision:** benchmark its compactness and readability; specify training projection and grounding-ID semantics independently of transient tool handles.

## BrowserGym separates capture from agent text

BrowserGym retrieves CDP AX trees per frame, joins frame roots, and attaches `browsergym_id` values. Its collection code explicitly handles frames that cannot be joined, illustrating why capture completeness belongs in the record. [Observation extraction](https://github.com/ServiceNow/BrowserGym/blob/main/browsergym/core/src/browsergym/core/observation.py)

`flatten_axtree_to_str` independently controls generic-node removal, redundant static-text removal, visibility filters, identifier display, clickability, and coordinates. It formats role/name/value/properties with indentation and can omit nodes without omitting descendants. This is useful evidence for configurable downsampling as a separate function. It does not establish a native-app interoperability schema. [Flattening implementation](https://github.com/ServiceNow/BrowserGym/blob/main/browsergym/core/src/browsergym/utils/obs.py)

**Reuse decision:** use its filtering choices as deterministic baselines; archive before filtering and record the projection version/options.

## Boundaries still requiring validation

This review did not execute adapters or measure model performance. A shared vocabulary alone does not establish invertibility, completeness, correct native actions, or equivalent tree shape. Before committing to an IR, validate a labelled form/error, controlled popup, table, rich text, nested frames, and virtualized collection across real captures. Compare preservation of relationships and user meaning, then measure projection token counts and task quality. Keep full capture, normalized observation, and learned summary/grouping outputs independently inspectable.
