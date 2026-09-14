# DOM adapter v0

`parseDOM` runs only in an isolated browser and `adaptDOM` is a pure Node ESM transform. Neither executes captured page scripts. Parsing requires a browser context whose requests are blocked by the caller: `DOMParser` creates an inert document but is not itself a network sandbox. Passing `networkIsolated: true` acknowledges that external isolation; it does not install it. Never attach the parsed document to a live document.

```js
// Inside the request-blocked browser:
const parsed = parseDOM(admittedHTML, {
  documentId: 'main', profile: 'saved-dom', networkIsolated: true,
  baseURL: 'https://example.test/'
});
// Inside Node:
const bundle = adaptDOM({snapshotId: 'capture-001', documents: [parsed]});
```

The parser uses full-document HTML parsing, includes repaired html/head/body structure and exact ordered text nodes, and records that browser repair is possible. It includes template content as explicitly dormant source content. IDs are deterministic preorder IDs, including a synthetic `#document` record. Comments and the doctype are not reading nodes. Node callers can provide equivalent records without a browser. The parser never reconstructs redacted content or fetches original pages.

Records have `{id,parent,children,kind,attributes,tag? ,text?}`. `kind` is `element` or `text`; `parent` is null for roots. Text records have no children. Tags must be lowercase. Each document declares `documentId`, `profile`, `roots`, and `records`. Optional `recordsHash` is SHA-256 over `stableStringify(records)` and is verified. Source HTML hashes belong to capture/artifact admission; the records adapter cannot verify a hash of HTML that it never receives. Optional `host:{documentId,recordId}` connects separately admitted frame documents through `embeds`, without adding a second parent. `coordinateSpaces` uses the observation contract.

`metadata.partial: true` and the `legacy-compact-dom` profile declare upstream partial children. Metadata is local evidence, never a model field. Source node IDs become `${documentId}:${recordId}` and retain their document/record grounding. Destinations are opaque stable IDs with URLs stored only in local grounding. Explicit unresolved/ambiguous HTML-ID references retain opaque endpoint IDs and local reasons; identical HTML IDs in different documents are independent.

## Current-state enrichment

An enrichment packet must explicitly verify its same-snapshot mapping:

```js
input.enrichment = {
  snapshotId: input.snapshotId,
  verified: true,
  records: [{
    documentId: 'main', recordId: '42', verified: true,
    name: '', states: {checked: false}, focused: true
  }]
};
```

Supported optional fields are string `name`/`description`, typed IR `value`/`states`/`exposure`/`bounds`, boolean `focused`, and `actions` as action-kind strings or `{kind}` records. Actions become `reported`. This is an adapter contract for an upstream verified join, not a claim that a boolean alone proves alignment. Callers must perform capture marker/backend ID alignment and stability checks first. Duplicate, stale, unverified, or missing target mappings throw. A `saved-dom` packet additionally requires `currentStateOverlay: true` on every enriched record. A rendered profile alone never promotes saved attributes into current state.

Saved `value`, `checked`, `selected`, and `open` attributes remain local default evidence. ARIA states are explicit source assertions. Empty supplied browser names and values remain known empty. No full accessible-name algorithm is approximated: labels, legends, captions, help, errors, headers, and SVG title/description are represented as source relationships. Native roles/actions are conservative mapping evidence; role attributes alone do not invent actions.

Password values are always withheld. Other text-field values and textarea text are withheld by default; an admitted source policy may use `allowFreeformValues: true`. This option is not permission to recover values omitted by upstream capture. Execution/drawing payload exclusions and private-value omissions are audited. Known frames and media mark partial child coverage.

Limits default to 200,000 aggregate records and 20,000,000 characters per document; traversal and graph checks are iterative. The parser also checks its character and node limits before/during traversal. Outputs are validated and deeply frozen without freezing caller metadata.

## Deliberate limits

V0 does not compute CSS visibility, infer closed shadow trees, implement the full HTML accessible-name algorithm, or derive implicit table-header associations. It preserves explicit `headers` relationships. ARIA role overrides are accepted from the pinned vocabulary, with diagnostics when they override native roles; this is not a full ARIA-in-HTML conformance checker. Unknown or invalid structural numbers remain local evidence, including unknown `aria-setsize=-1` and special native rowspan values. SVG drawing geometry is omitted while title/description/text survives. Browser-computed state and geometry require verified enrichment.

Run `node --test ui_ir/adapter.test.mjs` for pure-record tests. Actual HTML parsing and resource isolation require the browser integration check.

## Admitted legacy compact HTML

Only the explicit `legacy-compact-dom` profile interprets compactor marker attributes as trustworthy upstream evidence. Excerpt/preview markers set partial text coverage on their owning region and surviving descendant text runs. Fold/defer/item markers set partial children; deferred-relation markers set partial relations. Exact marker values, including omitted-item counts, remain in `evidence.nodes[id].upstreamMarkers`; they do not grant local expansion access. An original saved page containing similarly named author attributes receives no such interpretation.

An anchor's `data-destination-id` retains a distinct document-scoped opaque destination and `link` role when the original href was removed. Its descriptive `data-destination` is a label, never an executable URL; no invoke action is invented. `data-target-ref` resolves through the admitted marker index selected by `metadata.referenceAttribute` (parser option `referenceAttribute`), falling back to `data-r` only in the legacy profile. Ambiguous or missing compact markers become unresolved endpoints rather than HTML-ID guesses.
