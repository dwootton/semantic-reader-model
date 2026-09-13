# Accessibility IR landscape and a proposed boundary

Research checked 2026-09-12 against primary sources. This is a design recommendation, not an implemented schema or a claim of lossless interoperability. The reviewed AccessKit documentation reports version 0.25.0; CDP links below are tip-of-tree and must be pinned to the capture browser in an implementation.

## Main conclusion

Use an **AccessKit-shaped observation model**, preserve every original capture alongside it, and make the learned semantic hierarchy a **separate overlay referencing observed node IDs**. AccessKit is the closest reusable schema investigated here. It does not remove the need to build capture/import adapters, and its existing platform adapters should not be mistaken for arbitrary-app UIA/macOS tree importers.

The important boundary is between “what the application exposes” and “how we propose presenting it.” Combining both into one rewritten accessibility tree makes it difficult to audit hallucinations, compare alternate groupings, or retain the original action targets.

**Terminology:** `AXDOM` is not treated here as one universal format. A browser-computed AX tree (possibly joined with DOM), a macOS AXUIElement trace, and a Windows UIA trace are distinct source kinds. Give adapters explicit names such as `chromium-cdp-ax`, `dom-snapshot`, `macos-ax`, and `windows-uia`; accept an existing “AXDOM” trace only through a versioned adapter for its actual producer.

## Existing representations

| Representation | Verified scope | Recommended use and limitation |
|---|---|---|
| **AccessKit** | Cross-platform accessible UI schema, based largely on Chromium's abstraction; Rust is canonical, with serialization and generated language representations. Its platform adapters accept application/toolkit tree updates and implement platform APIs. [Project documentation](https://github.com/AccessKit/accesskit#how-it-works) | Best starting vocabulary and potential serialization dependency. The documented adapter direction is provider → AccessKit → OS accessibility, not OS accessibility → normalized capture. The project also warns that platform adapters do not cover every schema property. |
| **Chromium internal AXTree / AXNodeData** | Sparse typed node attributes, incremental tree updates, events, and action dispatch. Each frame has its own tree, composed into a virtual tree for consumers; node IDs are frame-local. Internal inline text boxes are not directly exposed by native APIs. [Chromium overview](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md) | A mature reference design. Depending on Chromium internals is heavier than using a public capture protocol. Do not equate an internal AX tree, a CDP response, and an OS-exposed tree. |
| **CDP Accessibility** | Exposes computed role/name/description/value, properties, ignored state/reasons, ancestry, optional backend DOM IDs, and frame IDs. Enabling the domain keeps AX IDs consistent across calls. Full-tree retrieval is scoped to a document/frame; the domain is experimental. [Accessibility domain](https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/) | Best practical initial browser accessibility capture. Preserve its source information. It is not itself a screenshot/layout bundle or a cross-platform input schema. |
| **CDP DOMSnapshot** | Captures DOM, selected computed styles, layout, text boxes, optional paint order and rectangles. It includes documents/iframes and flattens shadow DOM; backend IDs connect DOM nodes with other CDP data. [DOMSnapshot domain](https://chromedevtools.github.io/devtools-protocol/tot/DOMSnapshot/) | Complement AX capture with geometry and DOM evidence. Preserve the protocol payload: flattening and selected style capture mean this is not a complete replayable browser state. |
| **WAI-ARIA + Core-AAM** | ARIA provides roles, properties, and states. Core-AAM defines their exposure through platform APIs and explicitly notes that mappings are not consistently one-to-one. [ARIA](https://www.w3.org/TR/wai-aria-1.2/), [Core-AAM](https://www.w3.org/TR/core-aam-1.2/) | Reuse definitions and mapping tables. These are semantic and mapping specifications, rather than a universal serialized observation format. A reverse mapping can remain ambiguous. |
| **Accessibility Object Model (AOM)** | A web JavaScript API effort to modify and eventually inspect accessibility trees. Its own repository labels the linked spec as out of date. [AOM repository](https://github.com/WICG/aom) | Relevant API research, but do not make the project depend on the assumption of a universally deployed whole-tree AOM export. Check each specific feature separately. |
| **Windows UI Automation** | A dynamic, provider-backed tree with raw, control, and content views. Supported control patterns expose behaviors such as Invoke, Scroll, Grid, and ExpandCollapse; patterns can change with state. [Tree views](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-treeoverview), [Control patterns](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview) | Capture the tree view used, exposed properties, supported patterns, and completeness. Raw/control/content views are valuable deterministic simplification baselines. Control type alone is insufficient to describe capabilities. |
| **macOS AX / NSAccessibility** | Accessibility represents a hierarchy of elements with properties, actions, and notifications. Apps can omit implementation details from the exposed hierarchy. Client attribute retrieval can distinguish unsupported attributes, absent values, stale elements, and messaging failure. [Apple model guide](https://developer.apple.com/library/archive/documentation/Accessibility/Conceptual/AccessibilityMacOSX/OSXAXmodel.html), [Client attribute retrieval](https://developer.apple.com/documentation/applicationservices/1462085-axuielementcopyattributevalue?changes=_5) | Native capture requires an AX client adapter and explicit handling of missing/error states. The conceptual guide is archived; use current API availability for implementation. |

## What to reuse from AccessKit

AccessKit already supplies much more than `{role, name, children}`: ordered children; actions; bounds/transforms; text values and selection; states; table/list metadata; and relations such as labelled-by, described-by, controls, owns, and active descendant. Its `hidden` semantics additionally affect hit testing, which differs from ARIA hiding. These details argue for adopting vocabulary carefully, without silently assuming that similarly named native fields are identical. [Node schema](https://docs.rs/accesskit/latest/accesskit/struct.Node.html)

`TreeUpdate` models an atomic change against a particular previous state. It carries tree identity and focus; node replacement requires unchanged properties to remain present. It also supports separate subtrees. A dataset can reuse these concepts, but should store complete initial snapshots and ordered updates so it can reproduce each state. [TreeUpdate documentation](https://docs.rs/accesskit/latest/accesskit/struct.TreeUpdate.html)

**Recommendation:** first write a thin, versioned JSON observation envelope whose normalized properties align with a pinned AccessKit release. Keep the full AccessKit payload only if it is convenient for the capture/consumer stack. Do not begin by forking AccessKit or implementing its full schema. A small stable training projection can be generated from the richer archival representation.

## Proposed three-part record

The following fields are a project design proposal, not an existing standard.

### 1. Capture evidence

Store immutable source payloads and a manifest:

- `capture_id`, `session_id`, sequence/time, source adapter/version, browser/OS/app version, document/window/frame identity, locale and viewport.
- References to original AX/UIA/DOM payloads and optional screenshot; capture times for each modality and a synchronization/completeness result.
- Original source IDs, root IDs, capture tree view, truncation limits, errors, and missing capabilities.
- Coordinate conventions, scroll offsets, device pixel ratio, and the transform into screenshot pixels.

Snapshots obtained by separate calls should not be represented as guaranteed atomic. Reject or flag captures with detected state drift. Browser accessibility caches can lag rendering, and frames have distinct trees. [Chromium architecture](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md)

### 2. Normalized observed graph

Represent one primary ordered containment forest plus typed relation edges. “Tree” remains a useful traversal interface; the complete semantics are a graph because labels, controls, ownership, and references cross containment boundaries.

Use:

- `id`: canonical identity scoped to a capture; optional session identity when the adapter can substantiate continuity.
- `source_refs`: source namespace, tree/frame ID, native ID, optional DOM ID. A node may have several refs; some AX nodes have no DOM ref.
- `role` plus `source_role`/`source_subrole`: normalized vocabulary with an explicit unknown/other case, not forced incorrect classification.
- Separate `name`, `description`, `value`, and textual content. Keep source text/properties available even when a compact model projection deduplicates strings.
- `states`, `capabilities`, `children`, and typed `relations`; table coordinates/spans and list position/count when available.
- Optional bounds, clipping, coordinate-space identifier, and layout evidence.
- Sparse `property_evidence` and `normalization_issues`: exact mapping, approximate mapping, conflicting evidence, unsupported field, unobserved field, or capture failure.

Do not collapse “not observed,” “unsupported,” “false,” and “not applicable.” Likewise keep AX-excluded, offscreen, clipped, and visually hidden separate. The original native payload is the escape hatch for properties the common vocabulary cannot express.

Capabilities require evidence: a role named button is not proof of a successfully captured native invoke method. Keep an execution target linked to the original source; the model should not invent actions.

### 3. Predicted presentation overlay

Keep machine-created groups separate from native roles and preserve observed leaves. For example:

```json
{
  "schema_version": "semantic-overlay/0.1",
  "capture_id": "capture-42",
  "groups": [
    {
      "id": "g1",
      "kind": "form_section",
      "label": "Delivery address",
      "children": ["n17", "n19", "n24"],
      "label_evidence": ["n15"],
      "origin": "model"
    }
  ],
  "presentation_root": ["g1", "n30"],
  "collapsed_nodes": ["n15"],
  "fallback": "original_tree"
}
```

Here `n*` IDs reference the observation and `g*` IDs reference synthetic groups. `collapsed_nodes` records presentation omission, never evidence deletion. A production schema should specify whether each observed node may appear once, which nodes must remain reachable, and how cross-links are rendered. Store alternate acceptable overlays and annotator disagreement separately from the chosen target.

Do not automatically map all synthetic groups to ARIA `group`. ARIA distinguishes a widget collection from a landmark/region intended for page summaries. A presentation category such as `product_card`, `form_section`, or `result_cluster` belongs in its own vocabulary. [ARIA grouping semantics](https://www.w3.org/TR/wai-aria-1.2/#group)

## Important implications for capture and evaluation

1. **Start with browser-computed AX, not an offline recreation from HTML.** Names can depend on referenced elements and hidden content; simply filtering hidden DOM nodes first is incorrect. [Accessible Name computation](https://www.w3.org/TR/accname-1.2/)
2. **Treat cross-platform normalization as explicitly lossy.** Core-AAM is a mapping resource, not evidence that every platform representation is invertible. Keep native extensions and mapping diagnostics. [API comparison](https://www.w3.org/TR/core-aam-1.2/#comparing-accessibility-apis)
3. **Make the first output a conservative grouping task.** Select boundaries, group related nodes, collapse redundant wrappers, and provide extractive labels. Generating a replacement tree's complete roles, values, states, and actions adds avoidable failure modes.
4. **Compare against existing simplification first.** UIA control/content views already remove layout-only elements; macOS similarly permits an exposed hierarchy that skips implementation details. Measure additional navigation benefit beyond these baselines. [UIA views](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-treeoverview), [Apple hierarchy](https://developer.apple.com/library/archive/documentation/Accessibility/Conceptual/AccessibilityMacOSX/OSXAXmodel.html)
5. **Preserve dynamic examples.** Capture menu closed/open, dialog presence, validation error, selection change, and scrolled/virtualized states as related captures. Use structural validity, retained action targets, retained errors/focus/state, grouping consistency across transitions, and user task performance as checks. A shorter tree alone is not evidence of better accessibility.
6. **Add images as optional evidence now, test their value later.** Keep coordinate joins and timestamps, then compare AX-only, AX+layout, and AX+layout+image input. This avoids committing the local model to visual inference before demonstrating that it improves grouping.

## Work that remains before claiming interoperability

No adapter or round-trip test was implemented in this research task. The unresolved implementation questions are a field-level mapping table for each source, how capture tools expose capabilities and text ranges, how complete frame/native subtree traversal is, and how action target identity survives changes. The smallest useful validation corpus should include repeated cards, a form with external labels/errors, a table, a modal, nested frames, custom controls, and a virtualized list.

## Human assistive technology requirements

With people as the primary consumers, text and interaction semantics need more protection than an agent-only compact screen description:

- **Rich text:** preserve separate document text, formatting runs, selection/caret state, embedded objects, and text-range query capability. UIA Text/TextRange exposes text streams, spans, formatting, and traversal; support varies and live ranges may be invalidated by edits. Do not claim that one concatenated string faithfully substitutes for it. [Microsoft Text/TextRange](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-about-text-and-textrange-patterns)
- **Native range access:** retain the native query path and capture explicit query results needed by fixtures. macOS exposes parameterized-attribute enumeration and retrieval; a flat property dump cannot demonstrate that this query behavior has been preserved. [Apple parameterized attributes](https://developer.apple.com/documentation/applicationservices/1461203-axuielementcopyparameterizedattr)
- **Tables and collections:** preserve row/column identity, headers, spans, selection, logical counts, and realization state. UIA virtualized items may be absent from the current tree; realizing one can change the UI, including scrolling. Mark a partial observation honestly and capture transitions explicitly. [Microsoft virtualization](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-workingwithvirtualizeditems)
- **Focus and live updates:** keep source focus, caret, live-region, alert, and error events on a deterministic path. Recommendation: a model grouping pass may update the overview, but should not delay urgent state announcements or move the user's current reading/focus location. Maintain access to the original tree while the overlay is computed.
- **Latency:** measure capture, normalization, model inference, validation, and presentation separately, plus end-to-end p50/p95 on the target laptop. An under-one-second refresh is a target to test, not something inferable from parameter count; ten-second initial grouping must not imply ten-second delayed focus/error feedback. Incremental recomputation and cached unchanged groups should be part of the prototype boundary.

## Portable fixtures achievable in a 72-hour exploration

Recommendation: build the portable decoder/normalizer immediately and target a small cross-source contract corpus, not comprehensive native platform parity. A tractable fixture matrix is 6–10 UI patterns with at least two state snapshots each: labelled form/error, menu or combobox open/closed, table with headers, rich-text selection, modal focus, repeated cards, and virtualized collection.

On the Mac, obtain real browser AX+DOM traces and real macOS AX traces. A Windows machine/VM or existing Windows capture files are required for genuine UIA fixtures. Mac-based tests can validate importing prerecorded UIA data; they cannot establish live UIA traversal, notifications, range lifetime, or action execution on Windows. Handwritten UIA-shaped JSON tests schema behavior only and should be labelled synthetic.

For comparable browser fixtures, render the same controlled page on both operating systems and capture browser AX, Mac AX, and Windows UIA projections. Check retained user meaning and source coverage rather than expecting equal tree shape. Keep a small genuine native-app fixture set as a separate domain-transfer check. The first milestone is real trace import plus explicit loss reporting for all required source kinds; full screen-reader replacement is a substantially larger goal.
