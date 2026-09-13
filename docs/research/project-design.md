# Semantic reader: proposed IR and 72-hour feasibility study

Research and design proposal, 12 September 2026. This document specifies experiments and an illustrative representation; it does not report an implemented pipeline, collected corpus, trained model, or measured runtime.

## Intended outcome

The user wants people using assistive technology to navigate and understand interfaces through a simplified semantic hierarchy. Inputs should include captured browser DOM/accessibility data and Windows UI Automation trees, with development initially on a Mac. The preferred end-to-end latency is under one second; up to ten seconds may be acceptable. A roughly 0.5B–3B local model is a candidate implementation, not a requirement that should displace a faster successful approach.

My assessment: a useful research prototype, portable capture representation, curated benchmark, and first distilled local model are plausible goals. A universal, independently validated gold standard and production-quality reader across operating systems are not credible guaranteed outcomes of a 72-hour sprint. The first sprint should establish whether useful, reproducible groupings can be learned from information available at deployment.

Unlimited temporary compute primarily helps with candidate generation, diversity, experiments, and distillation. It does not supply missing interface information, decide what users find useful, recruit adjudicators, or prove cross-platform generalization.

## First-principles decomposition

There are three separate problems:

1. **Observation:** What elements, content, relationships, and interactions does the source report?
2. **Interpretation:** Which elements belong together for a person's understanding and navigation?
3. **Presentation:** How should a reader expose those groups, expanded detail, focus, and updates?

Conflating these creates an uncontrolled target. “Simplify” could mean deleting wrappers, naming regions, associating repeated buttons with their content, changing reading order, summarizing prose, or repairing missing accessibility information. These require different evidence and evaluations.

For v0, learn group boundaries, group nesting, and short grounded group labels. Preserve original leaf content, names, states, and source identities. Support progressive expansion. Defer prose summarization, inferred action semantics, and general repair of inaccessible controls. A shorter tree that hides a form error or a product price is a failure even if it looks tidy.

W3C guidance supports meaningful sections, headings, and relationships as navigation aids; it does not establish one ideal generated hierarchy for every user. [W3C page structure tutorial](https://www.w3.org/WAI/tutorials/page-structure/) and [cognitive accessibility page-structure pattern](https://www.w3.org/WAI/WCAG2/supplemental/patterns/o2p03-page-structure/).

## Three representations, one pipeline

```text
Native evidence bundle
    DOM + browser AX + layout + image; or native AX/UIA capture
                      |
               source adapter
                      v
Observed UI graph + source-specific evidence
                      |
          deterministic baseline / learned grouping
                      v
Semantic projection referencing original node IDs
                      |
        validation + deterministic presentation
                      v
Expandable navigation view, with original detail available
```

### 1. Native evidence bundle

Archive the source capture before lossy transformation. A web capture should represent an actual rendered state, not only saved HTML. Record computed browser accessibility data, DOM/layout evidence, a synchronized screenshot when feasible, viewport/scroll/scale, frame identities, locale, browser/capture versions, and capture completeness. Record timing and detect mismatches: multiple capture calls are not automatically atomic.

DOM attributes alone do not fully determine the computed accessibility tree or accessible name. Off-screen content can remain accessible, and hidden text can contribute to a name. [W3C accessible name practices](https://www.w3.org/WAI/ARIA/apg/practices/names-and-descriptions/).

Native capture adapters record what their APIs actually expose. Store native role/property values and relationships in sidecars when the common representation is incomplete. Unknown, unrequested, unsupported, and known absent are different states. For large virtualized lists, distinguish the observed items from reported total size and unmaterialized content.

### 2. Observed UI graph: the reusable IR

Use an AccessKit-inspired vocabulary for ordinary accessibility facts. AccessKit already models element IDs, roles, optional properties, actions, updates, and subtrees. Its documented role is enabling applications/toolkits to expose accessibility through platform adapters, not importing arbitrary external application trees. [AccessKit architecture](https://github.com/AccessKit/accesskit/blob/main/ARCHITECTURE.md).

Use a graph with an ordered containment tree and typed relationships. Parent/child alone cannot represent labels, descriptions, controls, ownership, active descendants, table headers, or alternative navigation relationships. One field called `parent` should not ambiguously combine DOM ancestry, source accessibility ancestry, and inferred semantic membership.

Suggested v0 concepts:

| Area | Common fields / meaning |
|---|---|
| Capture identity | Schema version, capture/session ID, source platform/API/version, time or sequence, roots, capabilities and completeness |
| Node identity | Snapshot-local canonical ID; native tree/frame/node references; optional continuity match across captures |
| Meaning | Normalized role, original role, computed accessible name, description, text runs, value, language |
| State | Focus, selection, enabled/disabled, expanded, checked including mixed, editable, required, invalid, modal and live-region metadata, as observed |
| Exposure | Accessibility inclusion, rendered visibility, viewport intersection, capture coverage; each independently represented |
| Behavior | Reported supported actions and source routing references; never inferred solely from a role |
| Geometry | Bounds, coordinate system, units, scale, scroll/transform provenance; absent when unavailable |
| Structure | Ordered source containment; explicit sibling/reading/focus information only when actually available |
| Relations | Labelled-by, described-by, controls, ownership, active descendant, headers, membership, source evidence |
| Rich content | Text selection/ranges and attributes, table row/column/header information, or explicit links to native evidence when not yet normalized |
| Provenance | Which source supplied a property, missing-data status, disagreements, transformation version |

Do not promise globally permanent IDs. Native/browser identifiers have their own lifetimes. Namespace them by session, tree/frame, and capture generation; represent cross-capture identity as an explicit best-effort match. Serialized captures can preserve source action references, but executing an action still requires a live adapter and a check that the target belongs to the current interface state.

The canonical graph is intentionally useful rather than claimed universally lossless. The graph plus retained native evidence should let future adapters or schema versions recover facts not represented in v0. Do not quietly convert an unfamiliar control to a generic element and discard its original semantics.

### 3. Semantic projection: what the learner predicts

The output should reference the observed graph instead of regenerating it. For example, these source nodes:

```text
n41 heading "Summer shoes"
n42 text "$79"
n43 button "Add to cart"
```

can become an expandable product group. Its display label can borrow the heading, while its descendants still resolve to the exact three original nodes.

```json
{
  "schema_version": "semantic-projection/0.1",
  "capture_id": "capture-001",
  "policy_id": "assistive-navigation/0.1",
  "roots": [{"group": "g1"}],
  "groups": [{
    "id": "g1",
    "kind": "item",
    "label": {"source_node": "n41", "source_field": "name"},
    "children": [{"node": "n41"}, {"node": "n42"}, {"node": "n43"}],
    "default_expanded": false,
    "evidence_nodes": ["n41", "n42", "n43"]
  }]
}
```

This is an illustrative output for a three-node capture, not an existing AccessKit format or a complete interchange standard. A production schema also needs validation rules, coverage accounting, update behavior, and an uncertainty/fallback mechanism.

Keep inferred group kinds in a separate namespace from native roles: “product entry” is an interpretation, whereas “button” is an observed accessibility role. Prefer source-derived labels first. If inferred labels are allowed, require evidence references, mark their origin, and evaluate unsupported claims. Do not rewrite the original control name to make the output more elegant.

The full source graph may support multiple projections. A table has both row and column structure; a person may navigate either way. A single tree is a presentation choice, not proof that all underlying relationships are hierarchical. Semantic groups can also span source containers, as with a control and a popup rendered elsewhere; start with source-subtree candidates for simplicity but retain a benchmark slice that tests this limitation.

## Correctness rules for the projection

- Every referenced source node exists in the referenced capture. Group membership and presentation nesting are acyclic and deterministic.
- Every source node selected by the presentation policy remains available as a leaf, an expandable member, or explicit fallback detail. Report coverage separately for interactive controls, text/content, and critical state.
- Original labels, values, checked/selected state, errors, and supported action targets remain source-backed. Copy these in renderer code instead of asking a language model to regenerate them.
- Collapsing a group changes its presentation, not the native element's accessibility inclusion or enabled state. The reader's virtual navigation cursor and the application's keyboard focus remain distinct.
- An active dialog, newly focused element, relevant form error, or live update must not become silently unreachable inside a collapsed group. Define and test exposure/update rules.
- Unsupported or uncertain grouping falls back to original source structure. Unassigned nodes must not disappear.
- Small unrelated changes should not reorganize stable regions. Track group identity and update only affected portions when possible.

These rules prevent several structural failures but do not establish usability. Incorrect source trees remain incorrect observations; preserving them is not accessibility repair.

## Dataset design

The fundamental example is an interface **state**, with optional before/after transitions. Capture open menus, dialogs, validation errors, selected tabs, search results, loading/empty states, scrolling, virtualized lists, and responsive changes. A collection of homepages will mostly teach site chrome.

Store native evidence, normalized observations, deployment-visible features, candidate projections, checks, human annotations or adjudications, and lineage/version information. Keep alternative valid groupings and disagreement reasons. Do not use opaque scalar judge scores as the only annotation record.

Use three separate collections:

1. A small independently adjudicated benchmark, including blind or low-vision assistive-technology users when available. Document the detailed policy and annotate acceptable alternatives.
2. A much larger silver training pool produced by teachers and machine checks. Model agreement does not upgrade it to gold.
3. A stress set covering missing names, repetitive controls, dense tables, unusual layout, multilingual content, inconsistent native data, dynamic changes, and source-platform differences.

Deduplicate and split by site/app family, shared templates, and capture trajectories before expanding or labeling. All states, screenshots, and modalities from the same trajectory belong to the same split. Include source-held-out evaluation if making a cross-platform generalization claim. A web-only trained student accepting UIA-shaped JSON has not thereby demonstrated Windows competence.

Owned or reproducible synthetic interfaces can provide exact membership supervision and states that public crawling misses. Their component-tree structure is a useful weak label, not automatic proof of the ideal human-facing hierarchy. Hold out template families to avoid measuring memorization.

Record collection permission/licensing and distribution status, and use reproducible accounts without personal information for authenticated examples. Separate private experimental evidence from material eligible for a public corpus. Decide this before paying to label large volumes.

## Teacher harness and evaluation

First write a rubric and test it on a small diverse seed. Use a generator to propose grounded groups, independent candidates for uncertain cases, deterministic validity/coverage checks, and a rubric-based judge. Route disagreement, suspicious certainty, unusual structures, and failure slices to humans. Blind candidate identity and vary ordering in comparative judging. Page content is data; embedded instructions must not control the annotation harness.

Judge what is useful: preserved access to content and controls, correct control-to-content association, sensible region boundaries, discoverable errors and dialogs, navigation effort, and stable updates. Generic “cleaner tree” preference rewards deletion and attractive labels without verifying access.

Measure:

| Dimension | Evidence |
|---|---|
| Structural integrity | Invalid IDs/cycles; missing or duplicate coverage; incorrect action associations |
| Group quality | Membership/relationship precision and recall at defined granularities; acceptable alternatives; label grounding |
| Human utility | Task completion, errors, navigation actions, time, orientation and preference against existing navigation |
| State handling | Dialog/error/live-region visibility; focus continuity; stable unaffected groups across transitions |
| Generalization | Held-out site/app/template/source slices and per-slice error reports |
| Deployment | Capture + normalization + inference + validation + rendering latency; warm/cold p50/p95, memory, quantization effects, input/output size |

Use tree-edit distance only as one diagnostic, not the sole success metric. Global pairwise accuracy can be dominated by unrelated node pairs. A few hundred good cases give valuable evidence but cannot justify universal reliability claims; report denominators and uncertainty.

## Model and latency strategy

Try a deterministic grouping baseline before training: native sections/landmarks/headings/lists/tables, wrapper collapse, repeated-item structure, and reliable label relationships. Then compare a compact group/edge scorer or encoder with a small generative student. The learner should spend its capacity on ambiguous group membership and labels, not copying source facts.

Recommended first student behavior: consume compact role/name/state/order/relationship/geometry features and predict group boundaries, parent links among candidates, and short labels or label-source IDs. Geometry can be encoded numerically without a vision encoder. Source-specific fields can be retained for training ablations, but the baseline should work with explicit missing-feature masks.

For huge trees, preserve a cheap global outline, process candidate regions, and combine locally predicted groups. Avoid blind token truncation. Independent region processing can break cross-region relations, so test those explicitly and preserve relation endpoints/context.

Parameter count does not determine latency. Long input prefill, serial output tokens, image resolution, normalization and capture overhead, and runtime implementation all contribute. Illustratively, emitting 1,000 tokens at 50 tokens/second costs 20 seconds in decoding alone; this is arithmetic, not a laptop measurement. Short source-ID outputs and incremental updates make the target more credible. A single-pass scorer is particularly worth testing for the under-one-second ambition.

At four bits per parameter, 0.5B–3B parameters imply roughly 0.25–1.5 GB of raw weight bits, excluding quantization metadata, runtime buffers, activations, KV cache, and any separate vision components. Measure actual resident memory and accuracy after quantization.

Capture images from the start if practical, but compare these conditions before choosing deployment inputs:

1. Text/accessibility graph only.
2. The same graph plus layout features.
3. The same graph plus screenshot.

An image-informed teacher can propose better labels, but a text-only student cannot reliably reconstruct evidence absent from its inputs. Separate the effects of better supervision from privileged information. Record whether each important labeling decision was supported by the features that the student will actually see. If screenshots improve only special cases, consider selective visual processing; its detection and latency costs also need evaluation.

Current model cards and adjacent papers are covered in [semantic-model-feasibility.md](semantic-model-feasibility.md). Model recommendations there are candidates for measurement, not evidence of this task's accuracy or a guaranteed local runtime.

## Proposed 72-hour sequence

The ranges below are allocation targets, not a throughput forecast. Begin arranging reviewers and Windows traces immediately if they are available; compute cannot substitute for their absence.

| Hours | Work and tangible evidence |
|---|---|
| 0–6 | Define v0 presentation policy and preservation rules. Hand-work 30–50 diverse examples. Specify capture/IR/projection format. Obtain browser and UIA fixture examples. Benchmark inference shape on the actual Mac. |
| 6–18 | Build one robust browser capture path, import available UIA/AX fixtures, implement baseline and projection validator, curate several hundred states, freeze held-out sites/templates. Run teacher agreement and modality pilots. |
| 18–36 | If seed quality passes, expand a silver pool toward 10k–50k useful states, subject to actual throughput and deduplication. Begin annotation/adjudication of approximately 100–300 benchmark states if reviewers are available. Launch student training as validated batches arrive. |
| 36–60 | Compare at least two small-model sizes and the non-generative baseline; test geometry and visual inputs; quantify cross-site/source failures; quantize and measure the actual deployment path. Feed new training failures into the training pool, not the sealed test set. |
| 60–72 | Freeze data/model versions. Run the untouched benchmark, small human navigation evaluations when available, state-transition tests, and warm/cold latency/memory measurement. Package reproducible captures, dataset manifests, model, baseline, metrics, and failures. |

The sprint should stop bulk labeling if humans cannot agree on a usable policy, the teacher violates preservation rules, or the deployment inputs lack the evidence needed for the proposed labels. Those are decisions to revise scope or features, not reasons to buy more judgments.

Useful positive evidence is that the teacher beats deterministic navigation on held-out examples under a human-relevant rubric, the student retains enough of that improvement, and the final pipeline fits the latency allowance. Keep the under-one-second result as a measured stretch goal; ten seconds still needs p95 checks on large inputs and a usable initial view while inference completes.

Define an explicit deadline with source-view fallback for the accepted latency window. While inference runs, focus, errors, and live-state announcements use the immediate deterministic path. When a projection finishes, validate its capture generation and source identities before adoption; discard obsolete results. Adoption must preserve the reader's virtual cursor and must not unexpectedly replace or reorganize the region being read. A low p95 does not eliminate the need to handle slow and stale results.

Mac development can validate the schema and replay captured Windows UIA trees. It cannot by itself establish that a live Windows UIA adapter works correctly. Obtain Windows-generated fixtures early and reserve live capture/action validation for an actual Windows environment. Browser AX, macOS AX, and UIA should be separate source types; “AXDOM” is not assumed to name a universal standard in this design.

## Deliverables and open decisions

The high-value deliverable is a versioned representation and benchmark that reveal which semantic groupings help people and can be learned reliably. The model checkpoint is one artifact built on that evidence.

Decisions still needing concrete examples or measurements: preferred grouping granularity, exact reader interaction/expansion behavior, acceptable treatment of repetitive content, target Mac hardware and tree sizes, the precise AXDOM trace format, live Windows access, and reviewer availability. These do not prevent the observation/projection separation or the seed experiment.

Related notes: [IR landscape](accessibility-ir-landscape.md), [dataset/evaluation critique](dataset-evaluation-critique.md), and [model/related-work evidence](semantic-model-feasibility.md).
