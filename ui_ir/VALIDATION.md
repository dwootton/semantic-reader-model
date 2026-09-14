# DOM / IR v0 implementation validation

Checked locally on 13 September 2026. These checks establish contract and preservation behavior, not model quality or assistive-navigation usefulness.

## Passed checks

- **60 Node core tests:** 22 adapter, 31 compactor, 7 contract/codec tests. Includes 100,000-node deep/wide/scoped fixtures, current/default states, native label order, partial legacy evidence, option exceptions, gap integrity, complete prompt budgets, expansion, context ownership and stable aliases.
- **9 offline browser tests:** full-document parsing/repair, script/resource isolation, real DOM→IR→view→codec output, schema validation, source ordering, namespaced documents, protected fields, defaults and legacy partial/destination markers.
- **26 legacy-compactor tests:** the existing regression suite, with all 29 source/profile invocations additionally run through the IR pipeline. Different representations/preservation policies are not asserted to yield identical bytes or node counts.
- **1 real audited-corpus integration check:** GOV.UK audited compact HTML → legacy-profile DOM adapter → IR → inspector comparison request → fake model → validated source-linked result. No real model call.
- **13 focused Python integration checks:** bridge metadata, source admission/hash checks, whole-request refusal, context ownership, packet/observation binding and ordered inspector source records.
- **Broader regressions:** repository suite 567 tests (8 skipped); inspector suite 115 tests (17 skipped); inspector JavaScript suite 25 passed (3 skipped). Skips are existing environment/local-corpus gates, not reported as passes.
- Ruff passed for changed Python files; Mypy passed for the five production Python integration modules; JavaScript syntax checks passed. JSON schemas were exercised against real adapter/view output.

## Same-source corpus comparison

All **45 runs** passed: three profiles × 15 local saved documents from 14 sites/captures. Original scripts and network requests were blocked. Source and producer hashes are stored in the local report. Partition planning was disabled for this whole-source size comparison; explicit oversize results are valid outcomes.

| Profile | Existing compact HTML bytes | IR model JSON bytes | IR view nodes | Under 200 KB whole-view budget |
|---|---:|---:|---:|---:|
| structure | 1,437,323 | 9,461,154 | 48,424 | 2 / 15 |
| excerpt | 1,419,334 | 9,450,883 | 48,398 | 2 / 15 |
| budget | 1,355,178 | 9,443,928 | 48,398 | 2 / 15 |

**The first JSON encoding is substantially larger than compact HTML.** It emits explicit text nodes, states, relations, membership and coverage; the preservation policy is also intentionally conservative. This is not a compression win, token benchmark, or fair model-quality comparison. The new architecture and omission semantics work, but codec optimization and measured model-budget tuning remain necessary before choosing it as the default training representation. Oversize inputs are rejected for whole-request dispatch and require a valid partition plan or a larger limit.

The corpus and reports are local-only. Detailed counters are in `runs/ui-ir-validation/corpus.json`; legacy input parity counters are in `runs/ui-ir-validation/legacy-input-parity.json`. No raw capture text is copied into this checked-in summary. The [README](README.md) has reproducible commands.

## Known scope limits

- The full DOM-first path is the CLI/collection module. The inspector opt-in is explicitly a migration path over existing audited compact HTML; it does not recreate omitted original source.
- Browser enrichment requires a caller-verified same-snapshot mapping. Full AccName/HTML-AAM conformance, implicit table-header derivation, arbitrary shadow/frame capture, native UIA/macOS importers and live action dispatch are not implemented.
- Partitioned parents may remain context-only. The result explicitly reports ownership coverage and context-only IDs; a later assembly/parent-label pass is needed to annotate every hierarchy level.
- Token counts remain unavailable without a supplied exact tokenizer. Byte budgets cover the configured complete prompt; dynamic model/schema overhead must also be bounded by the caller, as the comparison adapter does.
- No blind-user test or model-quality evaluation was run. No dependencies installed, cloud resource changes, or paid inference were required.

## Follow-up: lean navigation projection and Vertex pilot

The initial results above predate `ui-navigation/0.1`. The new projection retains the rich observation and compact view, uses a smaller model encoding, and enforces destination eligibility independently of the model. Explicitly hidden, inert, or dormant ancestry excludes a destination; referenced hidden labels/help remain context. Unknown exposure is not promoted to known visible.

Regression coverage now includes false-exposure wrapper preservation, original ancestry for detached scopes, missing metadata resets, inline whitespace, hidden relationship/gap closure, and rejection of a self-consistent forged packet against the bound view. CLI exports include hashed navigation artifacts; the inspector sends the lean projection and excludes inactive nodes from fallback.

A matched three-input Vertex pilot used the same eligible element IDs, instructions and output schema across HTML, rich IR and lean IR. All nine output trees passed structural and bound-reference checks:

| Input | HTML tokens | Rich IR tokens | Lean IR tokens | Lean reduction versus rich |
|---|---:|---:|---:|---:|
| Synthetic checkout | 1,493 | 4,108 | 2,541 | 38% |
| GOV.UK passport page | 9,914 | 47,204 | 24,112 | 49% |
| OpenStreetMap | 8,705 | 38,003 | 12,694 | 67% |

These are measured Gemini 3.8 Flash prompt tokens, including request overhead. One generation per condition is not a reliable latency or quality estimate. Lean remains larger than HTML. The two public-page inputs were already compacted HTML, not fresh raw captures.

OpenStreetMap's HTML outline explicitly assigned 19/24 eligible action-bearing nodes; both IR outlines assigned 24/24. Unassigned elements remain in raw eligible fallback. Some grouping choices remained worse or disputed, so this is not a demonstrated general usability improvement. In particular, richer coverage alone does not establish better navigation.

The updated judge rubric receives the authoritative eligible IDs and is told not to reward hidden dialogs, wrapper coverage or unnecessary zoom. Blinded pairwise judgments are exploratory and may disagree when presentation order changes. They are not accepted gold labels or a substitute for blind-reader testing.

Local reproducible inputs, usage logs, nine generated trees and judging details: `runs/ir-vertex-lean-pilot/REPORT.md`. Runner: `experiments/ir_vertex_pilot/lean.py`. No new dependencies or cloud infrastructure were added; inference used the approved lab Vertex configuration.

Follow-up verification: **77 Node core tests passed**, **125 inspector tests completed (17 skipped)**, **3 navigation CLI regressions passed**, and **3 collection IR tests passed**. CLI output byte counts and SHA-256 hashes were checked. Ruff, Mypy and JavaScript syntax checks passed for changed modules. All six order-swapped judgments completed after bounded retries: HTML won checkout in both orders, lean won GOV.UK in both, and OpenStreetMap split by presentation order.
