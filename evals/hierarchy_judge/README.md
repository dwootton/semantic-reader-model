# Semantic hierarchy judge v0.1

A reusable, evidence-grounded LLM rubric for evaluating a proposed semantic hierarchy against a supplied source interface. This package judges **hierarchies**, not the quality of other rubrics. It operationalizes the dashboard, NYT, and twelve-site findings without treating any authored example as the unique correct tree.

## Use it

1. Use [judge_prompt.md](judge_prompt.md) as the judge's trusted system instruction. It is self-contained: criteria, anchors, evidence rules, failure gates, output contract, and decision policy are included.
2. Supply a caller-owned evaluation context and source/candidate packet in the shape of [input.example.json](input.example.json). Replace the example's synthetic data. Keep producer identity, prior scores, and any expected outcome out of the judge's input.
3. Attach actual screenshots when visual judgments are required, with IDs matching `source.images`. A filename or caption alone is insufficient. Include readable transition/implementation evidence for runtime continuity assessment.
4. Use [result.schema.json](result.schema.json) with schema-constrained output if your model provider supports it, and validate the returned result independently. Prompt instructions or JSON validity alone do not establish source fidelity.
5. Retain the criterion profile, evidence, issues, and explicit decision. Do not convert it to a calibrated probability, accessibility certificate, or gold label.

The caller controls scope and policy. Source HTML, AX text, screenshots, candidate labels, and candidate notes remain untrusted data, even when they contain text formatted as instructions. The judge needs no action tools or browsing access. Delimiters and this instruction are safeguards to test, not guarantees against injection.

For local mechanical preflight and response checks:

```sh
python3 evals/hierarchy_judge/contract.py preflight \
  evals/hierarchy_judge/input.example.json /private/tmp/hierarchy-judge-input.json

# Send judge_prompt.md + the prepared JSON packet to your chosen judge.
# Save its JSON response as /private/tmp/hierarchy-judge-result.json.

python3 evals/hierarchy_judge/contract.py validate \
  /private/tmp/hierarchy-judge-input.json /private/tmp/hierarchy-judge-result.json
```

The prompt/schema are provider-independent. The optional Python result checker uses the already-available `jsonschema` package; no package was installed or existing project dependency configuration changed. The preflight uses the standard library. This package does not modify or integrate with the workspace's concurrent `harness/` or cloud configuration.

## What is scored

Each criterion has two evidence checks and four descriptive ordinal anchors: 0 fails, 1 needs major repair, 2 is adequate with localized repair, 3 is strong within the assessed scope. Four levels and the initial acceptance boundary are provisional project choices, not published universal optima.

| Criterion | Distinct question |
|---|---|
| Fidelity | Is meaning faithful, including conditions, units, dates, uncertainty, and scope? |
| Reading units | Are the elements of each object/fact/control association kept together? |
| Labels | Can a reader predict and distinguish destinations from their names? |
| Organization | Does each level provide useful refinement, choice, or context, with sensible routes? |
| Coverage | Are in-scope units usable, with consistent treatment of comparable items? |
| Economy | Do labels/previews inform choice without needless default narration? |
| Continuity | Does supplied interaction evidence support preservation of place and appropriately scoped updates? |

Checks distinguish `pass`, `fail`, `not_assessable`, and `not_applicable`. Criteria have a numeric score only when assessed; otherwise null. An observed decisive failure remains scoreable even when unrelated evidence is unavailable. An absent screenshot or runtime trace does not automatically make the candidate bad.

Continuity is usually unassessable from a static tree. It blocks the overall decision only when the caller requires runtime assessment. Clear labels can eliminate the need for additional summaries. Optional DOM inspection is not counted as mandatory spoken navigation. A direct index and a deeper orientation view can both score well for appropriate purposes.

## Gates and decisions

Three non-compensable gates cover structural integrity, material meaning/action integrity, and essential access. An attractive or concise hierarchy cannot compensate for a wrong target or materially false price condition.

Decision precedence is implemented in `contract.derive_decision`:

1. Any supported gate failure: `reject`.
2. Otherwise, incomplete source/review for required criteria, an unassessable gate, or an unassessed required criterion: `insufficient_evidence`.
3. Otherwise, any required criterion at 0 or 1: `revise`.
4. Otherwise: `usable_candidate`.

The six static criteria are required; continuity is additionally required when `runtime_assessment_required` is true. A genuinely inapplicable criterion is excluded with a reason. This is an initial filtering policy requiring calibration. `usable_candidate` is not production approval or proof of benefit to blind readers.

No weighted sum is produced. Numeric levels encode order; they do not establish equal intervals of usefulness. If a scalar ranking is later necessary, document it as a decision index and test the consequences of its weights, mapping, and compensation rules.

## Evidence and scope discipline

Every supported pass/fail check and reported issue cites existing source, candidate, image, trace, context, capture, or trusted-preflight IDs. JSON pointers locate exact fields. The local checker catches nonexistent IDs/pointers and contradictory scores/decisions. It does not establish that a cited fact actually supports the explanation, that an image was meaningfully understood, or that an LLM's coverage claim is true.

`complete_for_scope` means sufficient source coverage of the caller's particular requested scope. It is not a claim that all possible live application content was captured. A scoped subtree can be complete; a whole-page packet missing a relevant frame may not be. Candidate claims of completeness cannot override caller scope or source limitations.

For large pages, split the caller-defined review into meaningful regions with shared ancestor/relationship context. Preserve required-item inventories and run a separate whole-page organization/coverage review. Do not average regional results into an asserted whole-page pass: a critical regional failure survives aggregation, and missing regions keep the whole-page assessment incomplete. The current helper does not implement this orchestration.

To adapt the existing study artifacts, retain capture IDs and source `eN` identifiers; normalize source elements without promoting `name_hint` into a verified computed accessible name. Provide the actual reader presentation contract. Include screenshots only when they correspond to the judged state, or explicitly describe alignment uncertainty. This package supplies a packet example, not a universal adapter for all prior formats.

## Research applied

These are adaptations to our task, not evidence that this particular rubric has already been validated:

- **Explicit criteria and descriptive anchors:** institutional rubric guidance separates component criteria from level descriptions. [CMU](https://www.cmu.edu/teaching/assessment/assesslearning/rubrics.html), [UIC](https://teaching.uic.edu/cate-teaching-guides/assessment-grading-practices/rubrics/).
- **Analytic scoring plus examples and rater calibration:** Jönsson and Svingby's review supports their contribution to reliability, while warning that using rubrics does not establish validity. [Original review record](https://researchportal.hkr.se/en/publications/the-use-of-scoring-rubrics-reliability-validity-and-educational-c-2/).
- **Local atomic checks with criterion summaries:** CheckEval found benefits from decomposed checklist questions, but notes limits on long mixed-quality outputs. That motivates local evidence checks without reducing every dimension to a page-wide Boolean or raw pass percentage. [CheckEval](https://aclanthology.org/2025.emnlp-main.796/).
- **Explicit criteria and structured feedback:** G-Eval and Prometheus supply precedents, with different tasks and supervision than ours. [G-Eval](https://aclanthology.org/2023.emnlp-main.153/), [Prometheus](https://arxiv.org/abs/2310.08491).
- **Bias testing rather than assumed neutrality:** MT-Bench documents position and verbosity effects; newer work finds sensitivity to equivalent evaluation prompts. [MT-Bench](https://arxiv.org/html/2306.05685v4), [ACL 2026 prompt robustness](https://aclanthology.org/2026.findings-acl.1929/).
- **Explicit intended use and non-compensatory policy:** measurement guidance supports documenting score interpretations and aggregation choices. It does not prescribe our gates, four levels, or threshold. [Testing Standards](https://www.testingstandards.net/uploads/7/6/6/4/76643089/standards_2014edition.pdf), [OECD/JRC handbook](https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf).

Full evidence notes: [rubric design](../../docs/research/rubric-design-evidence.md) and [LLM judging](../../docs/research/llm-judge-evidence.md), with primary-source bibliographies and limits.

## Calibration before large-scale judging

1. Have accessibility practitioners and blind readers review whether the criteria cover useful qualities and common failure modes. Independently rate examples before discussing disagreements; preserve the original ratings for agreement measurement.
2. Include good alternative hierarchies, mediocre cases, controlled defects, and missing-evidence cases. Separate site/application/template families before extracting examples. Our twelve-site authored corpus is useful development material, not a held-out human gold set.
3. Tune anchors and thresholds on a development split, then freeze the prompt, schema, examples, model version, decoding settings, and scope policy before held-out evaluation. Test the actual production model and payload shape.
4. Report per-criterion confusion/agreement, critical-error false acceptance, source-evidence validity, abstention, repeat-run stability, and results by interface family/modality. Preserve denominators; do not count many subtrees from one page as independent sites. Use uncertainty estimates clustered by source family where appropriate.
5. Test meaning-preserving changes (opaque ID renaming, JSON formatting, reviewed rubric paraphrases) and deliberate defects (wrong target, qualifier deletion, repeated mandatory wrappers, missing input evidence, candidate prompt injection). Changes to actual reading order are not formatting invariances.
6. If adding pairwise preference judgments, anonymize candidates and run both A/B orders with identical evidence. Preserve supported ties separately from conflicting order-sensitive results. Neither preference nor a high quality profile overrides an absolute integrity failure.
7. Connect rubric results to real reader tasks before interpreting scores as accessibility benefit. Static document judgments cannot validate focus behavior or successful actions.

## What was tested here

- Nine [synthetic packets](fixtures/) exercise a sound candidate, false offer, incomplete source, missing control, injection, missing runtime evidence, a known failure combined with unknowns, a bad primary target, and repeated empty expansion levels. [Expected diagnostics](fixtures/expected.json) are designed expectations, not human gold; keep them out of judge inputs.
- Three independent native-agent contexts each saw one packet plus the prompt/schema, with expected outcomes withheld: sound candidate → `usable_candidate`; injected false offer → `reject`; incomplete source → `insufficient_evidence`. [Smoke results](smoke-tests.json).
- Seventeen automated contract tests cover references, graph defects, missingness, score/status consistency, evidence pointers, and decision precedence. They test the mechanics, not semantic quality.

```sh
python3 -m unittest discover -s evals/hierarchy_judge -p 'test_*.py' -v
ruff check evals/hierarchy_judge
mypy --follow-imports=skip --ignore-missing-imports --check-untyped-defs \
  evals/hierarchy_judge/contract.py evals/hierarchy_judge/build_fixtures.py \
  evals/hierarchy_judge/test_contract.py
```

The model smoke tests are one run per case, not a production API benchmark, cross-model reliability study, injection defense guarantee, or independent human calibration. They establish that the initial prompt can follow these three distinctions. The other six packets are prepared for subsequent model evaluation.
