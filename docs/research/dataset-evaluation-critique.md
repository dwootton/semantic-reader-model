# Accessibility hierarchy dataset: assumptions, invariants, and falsification plan

This note is a first-principles design critique, not an empirical performance claim. All proposed sample sizes and thresholds are pilot design choices to revise after measurement.

## Main recommendation

Build a **reversible semantic view over an observed interface**, rather than train a model to rewrite the accessibility tree. Preserve the source representation and expose its original details on demand. Let the model propose groups, group labels, and presentation priorities tied to source node IDs. A deterministic validator should decide whether a proposal is admissible; invalid or uncertain proposals fall back to the source view.

The hard question is not whether a small model can output a tree. It is whether the input contains enough evidence to choose a useful organization while preserving meaning, controls, and state. Establish that before buying a large annotation run.

## There is no single gold hierarchy until the task is specified

“Simplified” needs an explicit policy: simplified for whom, doing what, through which interaction mode? A first-time reader, a screen-reader user completing a checkout, and an autonomous agent locating a delete button may need different views of the same source.

For a product card containing a title, price, rating, variant selector, and purchase button, at least these are defensible: one product group with all details; summary plus expandable details and controls; or controls grouped by action. Exact tree equality would penalize valid alternatives. Teacher agreement can instead reflect a shared stylistic bias.

The user has now specified **human assistive-technology navigation** as the primary audience. Use a declared policy such as **task-independent, keyboard-navigable overview for a person, with every source control and essential detail reachable through the view**. Keep user-task conditioning as a separate experimental variable. Success means better discovery, comprehension, and navigation for that person; an agent's ability to select a source ID is not an adequate substitute.

Define gold as adjudicated source-grounded constraints, acceptable groupings, and user outcomes. Retain alternative acceptable hierarchies when they exist. Do not encode one annotator's complete tree as the only correct answer.

## Separate four layers

1. **Capture:** What DOM, platform accessibility, UIA, and optionally pixels actually report at a specific state.
2. **Canonical observation:** Normalized roles, names, values, states, order, relationships, actions, geometry, and source identifiers. Preserve unknowns and source-specific extensions.
3. **Semantic projection:** Proposed groups, membership, optional summaries, presentation priority, and links back to source nodes.
4. **Renderer/navigation policy:** How groups expand, how focus moves, how source details are reached, and what action dispatch means.

This separation makes failures diagnosable. A missing control caused by capture is different from one dropped by the simplifier; a sensible grouping can still be rendered with unusable navigation. Capture/normalization should not silently invent missing semantics. Inferred semantics belong in the projection with an explicit evidence source.

A canonical representation does not make inputs equally informative. A DOM capture, a browser accessibility tree, and a platform UIA tree may expose different facts. Record capability/missingness explicitly; distinguish “not captured,” “unknown,” and “known absent.” Paired adapters must describe the same interface state, or disagreements are not meaningful evidence about normalization.

## Make the learned output a constrained edit or partition

For an initial implementation, predict grouping boundaries, node membership, and short group labels over stable source IDs. Avoid regenerating the source tree's text and actions. Names and values should ordinarily come from source references; a generated summary is additional presentation content, never a silent replacement for the only copy of a source fact.

A projection could express a group such as “Shipping address,” reference its member IDs, choose a source heading as its label, and nominate which details start collapsed. The validator resolves those IDs against the observed snapshot. Presentation parentage should not erase source parentage or cross-references.

Do not require every relationship to fit into a tree. Labels, descriptions, table relationships, ownership, and control relationships can cross group boundaries. A tree-shaped navigation view can sit over a graph of preserved relationships. The model should not gain permission to delete those edges simply because it emits one parent per node.

## Required invariants

| Invariant | Why it matters | How to check |
| --- | --- | --- |
| Every actionable source node remains reachable | A shorter view that loses a control cannot replace the source view | Compare source action IDs with reachable action references |
| Original name, value, role, and relevant state remain inspectable | Rewriting “Delete account” as “Delete” changes usable meaning | Resolve source references and exercise detail expansion |
| Action target and contextual scope are unchanged | “Delete” in one row must not target another row | Dispatch only through preserved source handles; test repeated controls |
| Important noninteractive information remains reachable | Errors, instructions, totals, and headings may be essential without being actionable | Annotated information-retention checks, including negative cases |
| Labels, descriptions, and other relationship endpoints survive | Flat text retention does not preserve which field an error describes | Validate references and annotated relationship assertions |
| Declared reading/navigation order has a deterministic policy | Grouping can create confusing jumps even if every node remains | Compare source-relative order under the declared policy and test traversal |
| Focus, selection, expanded/checked/disabled/invalid state is current | A correct static snapshot can become misleading after one action | Evaluate capture–project–interact–recapture sequences |
| Synthetic groups do not invent controls or assert unsupported facts | Plausible-looking semantic output can hallucinate UI capability | Ground actions in source; mark inferred labels and summaries |
| Invalid, stale, or ambiguous projections have an accessible fallback | Structural constraints cannot prove every semantic claim | Deliberately inject invalid IDs, stale snapshots, and ambiguous inputs |

“All nodes are reachable” is necessary but insufficient. Hiding the required action under several vague groups can preserve formal reachability while making the UI worse. Evaluate the actual renderer and navigation path.

Expansion/focus behavior of synthetic groups must be distinguished from actions on the underlying application. Projected order should not silently change the application's native tab order. Preserve a navigable, expandable overlay and a direct route back to source details. An action handle also needs a freshness strategy: an ID in an old snapshot is not proof that the current UI still contains the same target. Essential updates such as validation errors or live-region notifications must remain available while a new grouping is being computed.

## Teacher annotations are silver unless independently validated

An expensive model judge is a labeler, not a source of ground truth. Multiple teachers and judges can share training priors or fail on the same missing evidence. Rubric compliance and mutual agreement do not establish accessibility utility.

Use three layers of supervision:

- **Mechanical facts:** Source IDs, actions, explicit labels/relations, and state. Validate these deterministically.
- **Semantic judgments:** Group membership, useful label, initial visibility, and importance. Collect proposals, disagreements, and independently adjudicated constraints.
- **User utility:** Discovery, comprehension, correct task completion, and navigation effort in the intended rendering mode. Validate with representative users; if unavailable within 72 hours, explicitly leave this claim unvalidated.

Blind human adjudication to teacher identity and randomize candidate order. Keep an untouched evaluation set out of prompt, judge-rubric, and model-development loops. Audit agreement cases as well as disagreements, because common-mode errors survive consensus. Judge source-grounding and usability separately from fluency.

A small, carefully audited evaluation corpus is more valuable early than a huge teacher-labeled corpus. Large-scale labels can follow after the rubric and coverage checks stabilize.

## Screenshot use creates an identifiability test

If a teacher sees a screenshot but the deployed student receives only a tree, the target may depend on information the student never gets. Distillation cannot recover facts absent from its input. For example, visual columns or card boundaries may be clear in pixels yet absent from a flattened source tree.

Run a matched ablation with the same interface states and policy:

1. Teacher receives canonical tree only.
2. Teacher receives the tree plus recorded geometry.
3. Teacher receives tree, geometry, and screenshot.

For improvements in case 3, ask what specific evidence changed the grouping and whether it can be represented cheaply at inference. Geometry may recover some gains; other cases may require images or a conservative fallback. Train the text-only student on labels supportable from its actual input, or tag such labels as ambiguous. Keep modality and capture completeness in dataset metadata.

## Dataset variation and splits

The unit of data should be an **interface state**, and the unit of generalization should usually be a **site/app or template family**, not a random URL or screenshot. Thousands of pages from one repeated template can make a large dataset with little semantic diversity.

Build a coverage matrix: forms, tables/grids, navigation, search/filtering, cards/feeds, editors, dialogs, menus, composite widgets, errors/empty/loading states, long virtualized views, repeated ambiguous labels, multiple languages, and changing state. Include sparse or misleading source semantics, since perfectly authored pages do not test the proposed model's main challenge.

Hold out source applications/domains and near-duplicate templates. Keep all states from an interaction trajectory together in one split. Record framework/template families where known and audit structural duplicates across splits. Report separately on unseen domains, unseen interaction structures, alternate capture adapters, and missing metadata. Because AXDOM traces and UIA trees are definite requirements, include small samples of both in the first pilot and test each adapter's contract. A browser-trained result does not validate a native-app result merely because both adapters emit the same schema.

Include both natural samples and intentionally difficult cases. Report the difficult-case slice independently; do not let common easy buttons overwhelm rare but important errors. Keep capture bugs separate from simplification failures while reporting end-to-end performance as well.

## Evaluation should test outcomes and conservation

Use at least four baselines: source tree; deterministic pruning of redundant containers; rule-based grouping from explicit landmarks/headings/roles; and the teacher projection. If simple rules obtain most of the utility gain, learn only the remaining decisions.

Measure:

- **Conservation:** Reachable action coverage; preservation of state, source facts, and relationships; hallucinated references/actions; failures per whole interface as well as per node.
- **Grouping:** Human preference under the declared policy, supported group-label quality, and acceptable membership/boundary constraints. Use structural similarity as a diagnostic, not the definition of correctness.
- **Utility:** Correct task completion, first-target discovery, navigation steps/time, comprehension mistakes, and cost of returning to source details. Compression ratio alone rewards dangerous deletion.
- **Runtime:** End-to-end latency distribution on the intended laptop, peak memory, input/output lengths, failure/fallback rate, and quality under quantization. Include preprocessing, validation, and rendering costs.
- **Dynamics:** Correct target after state changes, focused-item continuity, and stability of unaffected groups. Avoid making temporal invariance so strict that necessary state changes are suppressed.

The user prefers **under one second**, with **up to ten seconds acceptable**, and develops on a Mac while requiring a portable representation. Benchmark end-to-end on that actual Mac: typical and long trees, cold and warm execution, quantized weights, and measured percentile latency. Report separately against the one-second aspiration and ten-second tolerance. “0.5B–3B” is a size range to benchmark, not proof of acceptable interactive performance. Long input trees and autoregressive output length may dominate even when parameters fit comfortably in memory. Constrained grouping output gives a much shorter decoding problem than reproducing an entire canonical tree.

For multi-second inference, keep the source interface usable while a proposal is computed. When the proposal arrives, do not move the user's current navigation position or silently replace the region they are reading. Test a stable adoption policy and incremental updates. Faster inference alone will not solve unexpected focus or reading-order changes.

## A 72-hour falsification sprint

The goal is to retire the biggest uncertainties, not claim a universal gold standard in three days. The following quantities are illustrative pilot budgets, not promises of statistical sufficiency.

| Window | Work | Decision evidence |
| --- | --- | --- |
| 0–6 hours | Fix primary audience, projection policy, action/detail invariants, and a minimal renderer. Manually inspect roughly 30–50 heterogeneous states. | Can two competent reviewers explain what a good output is and identify unacceptable transformations? |
| 6–18 hours | Capture a few hundred states across distinct template families. Build deterministic baselines, validators, and the held-out split. | Is source information sufficient? Are capture failures distinguishable? Do simple rules already solve most cases? |
| 18–36 hours | Run independent teacher proposals and the modality ablation. Adjudicate a small evaluation core, including agreement cases and difficult states. | Are improvements reproducible and source-supported? Is the remaining ambiguity tolerable under one policy? |
| 36–60 hours | Train the smallest feasible constrained-output student pilot and compare with a larger candidate. Benchmark on the target laptop with representative tree lengths. | Does the student improve utility over rules on held-out families while preserving invariants? |
| 60–72 hours | Run untouched evaluation, interaction-sequence checks, error analysis, and a representative user pilot if practical. | Expand data, revise the task/output, add inference inputs, or stop this formulation based on identified failures. |

Do not wait until hour 60 to test the renderer or target laptop. Start both early; the later window is the final evaluation. Dataset collection, teacher annotation, and a small training smoke test can overlap after their contracts stabilize.

**Go:** A meaningful gain over deterministic baselines on unseen families; no accepted invariant violations in the audited evaluation; independently judged helpful grouping; tolerable laptop runtime; errors that additional training data plausibly addresses.

**Change the formulation:** Teacher gains require unavailable visual evidence; reviewers disagree because the policy is underspecified; arbitrary output trees drift in text/action meaning; or long sequences dominate latency. Responses include a richer input, task-specific views, constrained prediction, or localized grouping over deterministic structure.

**Stop scaling labels:** Improvements are only prettier summaries, random-split scores collapse under template holdout, judges disagree with representative users, or the student consistently loses essential information. More synthetic data would amplify these problems.

Zero observed failures in a pilot does not establish production reliability. A successful 72-hour result is an audited pilot dataset, a defensible evaluation contract, an end-to-end prototype, and measured evidence for whether a larger labeling/training run is justified.
