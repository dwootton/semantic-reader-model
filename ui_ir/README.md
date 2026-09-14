# Observation IR and deterministic compaction

Implemented DOM-first observation adapter, source-neutral compactor, model codec, expansion, validation, and local artifact transport. Existing compact HTML and AX harness inputs remain available; this is an opt-in path, not an automatic migration or native UIA adapter.

## Try it without a browser or model

From the repository root, Python standard library and Node are sufficient for parsed-record input:

```sh
python3 -m ui_ir \
  --records ui_ir/fixtures/shipping-records.json \
  --out runs/ir-shipping \
  --profile structure
```

For saved HTML, use a Python environment with the project's existing Playwright installation and a compatible installed Chromium:

```sh
python3 -m ui_ir \
  --html ui_ir/fixtures/shipping.html \
  --out runs/ir-shipping-html \
  --profile budget --max-bytes 16000
```

`SEMANTIC_IR_CHROMIUM_EXECUTABLE` optionally selects an already installed browser. No browser/package installation is performed automatically. Parsing runs in a fresh context with page-authored JavaScript disabled, service workers blocked, and every network request aborted. `parseDOM` itself is not a network sandbox; its explicit isolation flag is an assertion required of callers.

The output contains the observation, grounding/evidence, adapter audit, compact view, omission ledger/report, model input, bound alias packet, and any regional plans, with artifact hashes. All capture-derived artifacts remain local and inherit source-admission/publication restrictions. The examples are synthetic and contain no user credentials.

## JavaScript interface

```js
import {
  adaptDOM, compactIR, encodeModelView, modelPacket, expandIR,
  validateModelReferences
} from './ui_ir/index.mjs';

const bundle = adaptDOM({snapshotId: 'capture-001', documents: parsedDocuments});
const result = compactIR(bundle.observation, {
  profile: 'budget', maxBytes: 200000,
  promptPrefix: systemAndTaskPrefix,
  promptSuffix: responseContractSuffix
});

// Never dispatch an over-budget result merely because it has a usable preview.
if (result.report.status === 'ready') {
  const input = encodeModelView(result.view);
  const packet = modelPacket(result.view);
  // Validate model aliases against this exact packet and observation/view identity.
  const canonicalIds = validateModelReferences(packet, ['n0'], {
    snapshotId: bundle.observation.snapshotId,
    observationHash: result.view.observationHash,
    viewHash: packet.viewHash
  });
}

// Only local gaps can expand; upstream omissions/redactions cannot.
const expanded = expandIR(bundle.observation, result, requestedLocalGapIds);
```

The example alias `n0` is illustrative; callers must use an actually offered owned alias. Context nodes are never assignable. The CLI `references` operation additionally accepts the actual `view` and `observation` to bind all identities before dispatch/decoding.

## What is implemented

- **DOM adaptation:** full browser HTML parsing or pre-parsed records; ordered text nodes; scoped identities; native/ARIA role subset; current/default separation; explicit labels/help/errors/headers/captions/form/fragment relations; verified enrichment contract; source grounding and missing-reference diagnostics. Passwords are withheld; other freeform values are withheld by default.
- **Structure profile:** preserves branching/semantic boundaries, controls and complete short reading units, with source-order transparent-wrapper collapse. Formatting whitespace does not create a false record boundary, and remains in ordered content when wrappers are spliced.
- **Excerpt profile:** Unicode-safe explicitly partial prose and bounded native-choice previews. Selected/default-pinned/active/disabled/current/invalid option evidence survives. Protected instructions, alerts, code/math and dependency text do not become misleading prefixes.
- **Budget profile:** accepts only actual positive serialized-byte savings, with fixed work limits. Measures the complete configured prompt envelope, not node ratio. Exact token budgets are available only with an explicit synchronous tokenizer callback and tokenizer ID; absent measurements remain null.
- **Relations and scopes:** typed cycle-safe dependency closure, full external header/help text, read-only context, and explicit ownership. Partial inputs stay partial.
- **Recovery:** same-snapshot expansion with integrity-bound gap ledger and budget context. Expanding one gap does not expose unrelated dormant siblings. Fixed prompt overhead and tokenizer identity remain bound across expansions.
- **Partition plans:** byte-bounded regions with explicit unplanned scopes, context duplication, and `ownedCoverage`/`contextOnlySourceIds`. Parents used only as context need later hierarchy assembly; a `planned` result does not mean every level received an assignable annotation task.
- **Model codec:** compact deterministic JSON, stable short aliases, explicit gaps and text extracts, focus when in scope, and no raw selectors/native action bindings/full destination URLs in the ordinary prompt.

## Contracts and state

`schema/observation-v0.schema.json` and `schema/view-v0.schema.json` define wire shapes; `validateObservation` / `validateView` additionally enforce graph, identity, relationship and ownership constraints. `schema/build.mjs` regenerates the wire schema from the pinned registry. Canonical observation nodes have string text and ordered child IDs. Compact-view nodes have explicit owned/context membership, node/gap child entries and complete/extract text variants.

An omitted optional property is unknown, not false. Known empty browser names remain empty. Saved `checked`, `selected`, `open` and `value` attributes are local defaults rather than invented current state. Direct ARIA assertions retain their source basis. Coverage has independent children/names/actions/relations and optional text dimensions. Legacy compactor prefixes remain unavailable extracts, not complete source text or locally recoverable gaps.

Current limits: 100,000 normalized nodes; 250,000 relationship endpoints; at most 256 budget candidate evaluations, 512 partition trials, and 64 regions per request. These ceilings do not guarantee a particular latency. Smaller application-specific budgets are recommended for interactive use. Regions with indivisible protected evidence that cannot fit are explicitly unsatisfied.

## Integration

- `collection.ir_compress.compress_ir_capture(...)` validates an existing captured-document manifest and source hashes, then writes separate `ir-compression` artifacts. It does not replace `collection.compress` or dispatch model calls.
- The comparison server offers **IR v0 · audited compact source**. This migration mode adapts the already audited compact HTML, marks its upstream omissions, and sends IR JSON to the model. It is deliberately not claimed to recover the original page. Full DOM-first adaptation is available through the CLI/collection path.
- Inspector model references are checked against owned aliases, exact observation/view identities, and the complete request limit before a call. Unassigned eligible source remains in fallback; hidden sources remain available only through raw inspection. Context does not become model-owned membership. No automatic expansion or new model-spending run is triggered by installing this path.
- For this first IR comparison mode, regions follow compactor byte-budget partitions or whole-document scopes. The old node-count region-size selector is disabled for that mode.

## Verification

Dependency-free core checks:

```sh
node --test ui_ir/*.test.mjs
python3 -m unittest discover -s inspector -p 'test_ir*.py'
python3 -m unittest tests.test_collection_ir_compress
```

Offline browser checks, using an environment with existing Playwright and jsonschema:

```sh
SEMANTIC_BROWSER_INTEGRATION=1 python3 -m unittest ui_ir.test_browser -v
SEMANTIC_BROWSER_INTEGRATION=1 python3 -m unittest ui_ir.test_legacy_parity -v
python3 -m ui_ir.corpus_check
```

The legacy parity suite runs all 26 existing compactor tests and passes every source/profile invocation through the IR pipeline as well. Its original assertions still evaluate the legacy behavior; additional assertions validate IR contracts, byte accounting, and complete source ledgers. It does not assert identical encodings or semantic quality. The optional local corpus comparison runs the same 15 saved documents through both implementations; outputs and measurements live under ignored `runs/ui-ir-validation/`.

## Limits and interpretation

This version prioritizes evidence preservation over minimum prompt size. The initial explicit JSON codec can be substantially larger than the existing compact HTML; no token-size, speed, or model-quality improvement is claimed. Oversized whole-page inputs must use a validated region plan or a larger budget. Byte counts are not token counts.

V0 does not implement full AccName/HTML-AAM conformance, implicit table-header derivation, live UI actions, arbitrary shadow/frame capture, native UIA/macOS importers, or a blind-reader usability evaluation. It preserves explicit evidence and reports unavailable information. Snapshot alignment must be established by the collector before its enrichment assertions are trusted. The complete design and the implementation's specific limits should be read together.

Design: [DOM adapter and compactor](../docs/design/dom-ir-compaction-v0.md). These modules are a first concrete implementation of that design, not a universal lossless accessibility standard.

Measured results and test counts: [implementation validation](VALIDATION.md).

## Active navigation projection

`navigationPacket(view, observation)` provides a separate `ui-navigation/0.1` model input. The rich observation and compact view are unchanged. The projection uses ordered node tuples and a format legend, short property names, and compact inherited metadata. It retains roles, states, action evidence, relationships, values, and explicit gaps. Stable source aliases remain compatible with the rich codec.

Use `packet.eligibleIds` for destination enums, `packet.observedIds` for observed evidence/expansion requests, and `validateNavigationReferences(packet, refs, expected)` before accepting model membership. The packet is bound to the snapshot, observation, and view. Supply the observation so scoped roots inherit exclusion and verbatim context from their original ancestors; detached scopes without that evidence are refused. These IDs differ intentionally: hidden relationship evidence is observed but cannot be a destination.

Explicit `rendered:false`, `accessibilityIncluded:false`, `inert:true`, or `dormant:true` excludes a subtree from active destination eligibility. Relationship targets and their explanatory text can survive as context. Unknown exposure remains unknown and eligible; this policy does not establish actual screen visibility from a saved DOM. A raw inspector can still show all original evidence separately.

```js
import { navigationPacket, validateNavigationReferences } from './ui_ir/index.mjs';
const navigation = navigationPacket(result.view, bundle.observation);
const allowedDestinations = navigation.eligibleIds;
// Send navigation.text, with allowedDestinations in your output schema.
// Once output is validated structurally:
const ids = validateNavigationReferences(navigation, modelSourceIds, {
  snapshotId: bundle.observation.snapshotId,
  observationHash: result.view.observationHash,
  viewHash: navigation.viewHash
});
```

The JSON CLI operations `navigation` and `navigation-references` accept the actual `view` and `observation` to verify their binding. The Python artifact CLI additionally writes `navigation-input.json` and `navigation-packet.json`, with byte counts and hashes in its manifest. The original rich files remain available.

The inspector IR comparison now sends this projection, validates destination eligibility both in the schema and after generation, and limits fallback to eligible sources. An entirely excluded input makes no model call. Existing conservative rich-view partition limits still apply; the smaller projection does not silently override an unsatisfied compaction budget. Complete request limits still include the system prompt and output schema.

Node eligibility does not validate the meaning of a generated group label. A model could label eligible sources as an unrelated hidden dialog; structural reference checks cannot establish that label's truth. The evaluation rubric separately penalizes this and avoids rewarding wrapper coverage or hidden controls.
