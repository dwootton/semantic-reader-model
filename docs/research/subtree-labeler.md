# Subtree labeling as the first learning task

Design refinement, 12 September 2026. The user proposes annotating existing DOM-like trees at multiple levels by applying a small model to subtrees. This is a proposed experiment, not an implemented or benchmarked model.

## Assessment

This is a promising narrower target for a pretrained small model: identify which existing nodes enclose meaningful regions, classify those regions, and select source text that names them. Preserve the original hierarchy, native roles, content, state, and action targets. A reader can select among nested annotated regions without asking the model to generate a replacement tree.

Closed-set semantic classification, source-title selection, and open-ended title generation are distinct tasks. Begin with the first two. Short generated titles remain an optional later capability when no suitable source text exists. Model size alone does not establish accuracy or learning speed.

There is a direct narrower precedent: Google's Reading Mode classifies accessibility-tree content using a graph model with role, text, and geometry features. Its report gives a 241k-parameter Chrome model and 378ms median latency. These measurements concern its long-form content-distillation task, not this proposed navigation labeler. [Google Research](https://research.google/blog/on-device-content-distillation-with-graph-neural-networks/).

## Proposed contract

Input: a normalized observed subtree with original IDs, bounded ancestor/sibling context, relevant heading/label relationship endpoints, and explicit feature availability. Geometry is optional. An arbitrary tree shape is acceptable; arbitrary missing semantic evidence cannot guarantee a useful classification.

Output annotations reference existing nodes:

```json
{
  "target_id": "n23",
  "kind": "form_section",
  "title_source_id": "n24"
}
```

The example assumes n24 is a suitable observed heading within the provided evidence. Validate IDs and title source suitability. Include `none` for a node that is not a meaningful semantic region and `unknown` for insufficient evidence. Do not treat these as equivalent. Keep labels in a namespace separate from source accessibility roles.

Start with a small vocabulary such as navigation, toolbar, form, form_section, collection, item, content_section, and dialog, plus none/unknown. These are proposed categories to test for annotator agreement, not a settled taxonomy. Reader expansion defaults, urgency, and focus behavior belong to a separate presentation policy.

## Multi-level use

A collection, its items, and meaningful regions within an item can all receive labels. The caller chooses a target region; model execution may annotate several candidate nodes in one pass. This avoids requiring a separate inference for every wrapper and repeatedly encoding the same descendants.

A subtree alone may not identify its purpose: similar title/price/button clusters occur in search results, a cart, and order history. Train on exactly the context packet supplied at inference. Use original observations as the initial context; dependence on predicted ancestor labels adds error propagation and should be an explicit experiment.

Define ownership and reconciliation when calls overlap. Avoid noisy repetition from three nested wrappers describing the same region. Cache observations/features and recompute affected regions with their dependencies after changes. Context-sensitive annotations must not be cached solely by subtree text. Keep pending/stale predictions from moving the reader's position.

## Expressiveness limit

An existing-node annotation identifies a rooted subtree. It cannot directly identify an arbitrary subset of siblings, combine different branches, or repair a hierarchy whose desired semantic region has no corresponding node. First measure the proportion of human-desired groups representable by existing subtrees. Annotations may still provide useful broader regions, but that is a coverage tradeoff.

Add virtual candidate groups, sibling boundaries, or relation prediction only if the missing-group cases justify it. Retain native source relationships in the common IR throughout.

## First experiment

1. Select roughly 50–100 varied interfaces, including genuine browser and UIA traces where available. Split by site/app/template before extracting subtrees.
2. Annotate candidate nodes at several depths using the exact student-visible context. Record semantic type, title evidence, none/unknown, disagreements, and desired groups absent from the source tree.
3. Generate a modest training pool of subtree examples, with ordinary wrappers and ambiguous cases included. Thousands of overlapping crops are correlated examples, not thousands of independent interfaces.
4. Compare role/heading heuristics, a compact classifier, and a small pretrained language-model fine-tune. Use short tag/ID outputs and evaluate the exported model on the actual Mac.
5. Measure per-class quality, meaningful-region detection, grounded title selection, consistency across overlapping calls, robustness to harmless wrapper changes, representable-group coverage, and full-page latency. Validate human navigation benefit separately from label accuracy.

If annotation agreement is strong, source subtrees cover enough useful regions, and a student generalizes to held-out apps/sites, this is a sound foundation for the larger dataset project. If those assumptions fail, larger-scale teacher labeling will not resolve the formulation by itself.
