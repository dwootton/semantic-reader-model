# Conservative DOM downsampling research

## Paper findings

Primary source: Schiepanski, [Beyond Pixels: Exploring DOM Downsampling for LLM-Based Web Agents, v4](https://arxiv.org/html/2508.04412v4), sections 2–3 and Appendix D; inspected 2026-09-12.

D2Snap uses post-order traversal with frozen original depths and three independent parameters in `[0,1]` (larger means more removal):

- Elements: unwrap at depth `d > 1` when `floor(d*r_e) > floor((d-1)*r_e)`. The nominal height target is `max(1, ceil(h*(1-r_e)))`; protected actionable nodes make this approximate.
- Attributes: discard when heuristic relevance `A(name) < r_a`.
- Text: TextRank selects `max(ceil((1-r_t)*sentenceCount),1)` sentences per text node, restoring original order.

Actionable elements bypass element consolidation; formatting elements become Markdown. Attribute/text processing still precedes element classification. Therefore actionability protection does not mean full subtree or attribute preservation.

Reference `(r_e,r_a,r_t)=(0.9,0.3,0.6)` achieved 73.1% snapshot-target success with 21.13k mean tokens; grounded GUI achieved 67.3%. Evidence is limited to 52 snapshots, 18 trajectories, and GPT-4o; this is not proof of general content preservation. The attribute heuristic is model-elicited, and the HTML appendix omits its actual table. [Source](https://arxiv.org/html/2508.04412v4)

## Proposed adaptations for this project

These are design recommendations, not claims established by the paper:

1. Produce ordinary HTML, retaining native semantic tags instead of replacing formatting with Markdown. Keep document structure, headings, paragraphs, lists, tables, forms, labels, figures/captions, and inline emphasis/code.
2. Start with text reduction disabled. Preserve all meaningful body text in order, including repeated text; duplication can carry distinct context. Preserve whitespace exactly in `pre`, `code`, and `textarea`.
3. Apply the depth gate only to demonstrably redundant generic wrappers. A wrapper with an ID, role, ARIA relationship, state, language/direction, hidden/inert semantics, or an interaction must survive. Do not move attributes onto parents or children.
4. Keep source IDs and all relationship targets (`for`, `headers`, ARIA ID references). Preserve links, image descriptions/sources, form identity/state/constraints, and machine-readable semantic attributes. Remove only an explicit list of presentation/execution noise; keep unknown attributes by default.
5. Remove script/style payloads and comments explicitly, recording their contribution separately from content removal. Do not prune hidden subtrees by default: collapsed panels and offscreen content may be needed later.
6. Treat token/byte targets as soft. If reaching a target violates content or structure checks, return the larger verified snapshot with a clear report.

## Output acceptance checks

Compare original and serialized/reparsed output, not merely the intermediate tree:

- Exact meaningful text sequence retention, with separate whitespace-sensitive checks.
- All actionable elements, native semantic elements, source IDs, links, form states, and existing ID-reference relationships retained.
- No newly broken table/list/form parent-child structure or browser parser repairs that relocate content.
- No new duplicate IDs, dangling relationships, or lost accessible labels.
- Counts and byte sizes before/after, categorized removals, text retention ratio, protected-node retention ratio, and explicit validation failures.

Use fixtures containing malformed input, mixed inline text, nested generic wrappers, tables, nested lists, custom controls, collapsed content, SVG/MathML, and long attributes. Inspect before/after HTML from representative real pages as well as tests. Conservative acceptance should prioritize 100% protected content retention over a promised compression percentage.
