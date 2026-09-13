---
title: Evidence for designing the semantic-hierarchy judging rubric
date: 2026-09-12
bibliography: rubric-design-references.bib
---

# Evidence for designing the semantic-hierarchy judging rubric

The defensible starting point is an **analytic rubric with observable criteria, descriptive performance anchors, and evidence attached to each judgment**. Its initial output should be a quality profile and explicit defects. It is not yet a validated measure of blind-reader navigation performance, and a sum of its ratings does not become one by being expressed out of 100.

This is a targeted evidence review, not a systematic review. Educational assessment and measurement research informs the design; applying it to accessibility hierarchies and LLM judges is an adaptation that needs its own validation. LLM-specific bias research is handled separately. All sources below are original publications, institutional guidance, or official measurement guidance.

## What the sources support

### 1. Separate criteria, descriptors, and rating levels

Carnegie Mellon's assessment guidance distinguishes the aspects of performance being assessed, descriptions of their characteristics, and levels of mastery. This supports a rubric organized around explicit dimensions, rather than a list of desirable adjectives followed by a global score. [CMU, Creating and Using Rubrics](https://www.cmu.edu/teaching/assessment/assesslearning/rubrics.html).

**Project application:** each criterion should have a stable ID, the question being answered, admissible evidence, exclusions, and concrete anchors. “Good semantic hierarchy” is the target construct, not a scorable criterion by itself.

### 2. Use substantive quality criteria and only useful, distinguishable levels

Brookhart's review distinguishes descriptive performance language from evaluative labels and meaningful quality from superficial requirement counts. It also argues that the number of levels should reflect useful distinctions that can reliably be made. The review did not establish that performance descriptors themselves caused better outcomes. [Brookhart 2018, original article](https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2018.00022/full). [@brookhart2018]

**Project application:** assess whether expansion adds context or useful choices; do not prescribe a universal tree depth or reward fewer nodes. Start with a small ordinal scale, such as four anchored categories, and retain that choice only if calibration supports the distinctions. Four is a design choice, not an evidence-established optimum.

### 3. Remove overlapping and unobservable criteria

University of Illinois Chicago guidance recommends tangible qualities, checking for duplicate criteria, and distinct language across criteria and performance descriptions. It also recommends examples to communicate what descriptors mean to multiple graders. [UIC, Rubrics, especially “Guiding Questions”](https://teaching.uic.edu/cate-teaching-guides/assessment-grading-practices/rubrics/).

**Project application:** “clear and concise and complete and actionable” is too bundled for one rating. Separate title predictability, coherent reading units, semantic refinement, and action reachability. Give related criteria explicit boundaries: detached price conditions concern contextual completeness; invented price conditions concern fidelity. One defect may have several consequences, but record one defect with related criteria rather than silently counting it repeatedly.

### 4. Rubrics and agreement do not establish validity

Jönsson and Svingby's review covered 75 studies. It found that rubrics can improve scoring reliability, particularly analytic, topic-specific rubrics accompanied by exemplars or rater training. It did not find that using a rubric automatically makes performance judgments valid. [Authors' institutional record and abstract](https://researchportal.hkr.se/en/publications/the-use-of-scoring-rubrics-reliability-validity-and-educational-c-2/). [@jonsson2007]

The AERA/APA/NCME Standards require support for specified score interpretations and uses, identify the intended population and construct, and require documentation of cut-score rationale. See Standards 1.0–1.1 and 5.21–5.23. [Official 2014 Standards, printed pp. 23 and 107–108](https://www.testingstandards.net/uploads/7/6/6/4/76643089/standards_2014edition.pdf). [@aera2014]

**Project application:** state that the judge evaluates evidence-visible properties of a proposed navigation representation. Do not interpret an LLM rating as proof of usability, screen-reader compatibility, WCAG conformance, or reduced task time. A “ready for human review” disposition is more defensible than “accessible.” Version any selection thresholds and later test their false acceptance and false rejection rates.

### 5. Content review needs domain and intended-user perspectives

Boateng and colleagues' scale-development primer recommends defining the domain, reviewing its coverage with qualified experts, and involving members of the intended population through pretesting and cognitive interviews. Their guidance addresses measurement instruments in health and behavioral research; it is not a direct trial of accessibility-tree rubrics. [Boateng et al. 2018, content-validity and pretesting sections](https://www.frontiersin.org/journals/public-health/articles/10.3389/fpubh.2018.00149/full). [@boateng2018]

**Project application:** ask blind participants and accessibility practitioners to review the rubric's missing, misleading, or overemphasized qualities. Use concrete hierarchy examples in those discussions. Include exploration, known-item retrieval, form completion, interpretation of qualifiers, and return-to-place tasks; ask whether any criterion rewards an attractive tree that makes those tasks worse.

### 6. Treat numeric categories and aggregation honestly

The OECD/JRC handbook distinguishes ordinal order from equal-interval measurement, explains that additive aggregation permits compensation, and warns that overlapping indicators can double count a dimension. It recommends explicit theoretical choices and sensitivity analysis rather than treating weighting as neutral. See printed pp. 32–33 and 53–54. [Official handbook](https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf). [@oecd2008]

**Project application:** preserve the per-criterion ratings. A 0–3 code expresses order, not an established equal interval of usefulness. If an aggregate is later needed for ranking, call it a provisional decision index, document the numeric mapping and weights, and test whether reasonable alternative mappings reverse rankings. An excellent title must not compensate for a wrong action target. Treat such defects through explicit rules whose rationale is reviewed, rather than burying them in an average. Missing evidence must not receive an average or zero score.

### 7. Calibrate and evaluate agreement at the criterion level

UC Davis describes norming as aligning assessors on criteria meaning and application, followed by agreement checks and renewed calibration where needed. [UC Davis assessment glossary, “Norming”](https://assessment.ucdavis.edu/glossary).

Krippendorff's methods note supports agreement analysis with multiple raters, missing data, and an ordinal distance function; it evaluates one variable at a time. [Krippendorff, Computing Alpha-Reliability, pp. 1 and 5–6](https://www.asc.upenn.edu/sites/default/files/2021-03/Computing%20Krippendorff%27s%20Alpha-Reliability.pdf). [@krippendorff2011]

**Project application:** report exact agreement, confusion tables, and ordinal alpha per criterion, together with uncertainty and case counts. Inspect disagreements, not merely a pooled headline statistic. Agreement does not establish correctness; different model runs can share the same errors. Separate missingness from applicability and inspect disagreement about both before treating ratings as comparable.

## Operational design recommendations for this project

The following choices are proposed engineering policy, not standards prescribed by the sources.

1. **Freeze the evaluation contract.** Identify the capture, candidate, covered region, available modalities, reading/presentation policy, and whether transitions or executed actions are supplied. A static tree cannot demonstrate focus restoration.
2. **Use criterion-specific evidence requirements.** A source reference proves traceability, not narration quality. A screenshot can support visual association, not a control's actual behavior. A missing screenshot need not block structural judgments; missing action traces should block claims of successful activation.
3. **Separate outcomes.** A criterion can be scored, not applicable, or not assessable from supplied evidence. For example, continuity is applicable but not assessable for a dynamic application with no transition evidence; a noninteractive static excerpt may put it outside the evaluation scope.
4. **Anchor by consequences and scope.** Prefer “the product's membership condition is absent from its standalone reading unit” over “somewhat incomplete.” Distinguish local friction, repeated/task-relevant friction, and a material misinterpretation or blocked destination. Do not set severity from raw defect counts alone.
5. **Allow valid alternatives.** Several trees can provide equivalent useful choices. Judge adherence to properties and the stated presentation contract, not edit distance to one authored reference tree.
6. **Make abstention informative.** Record precisely which evidence is absent or inconsistent and which judgments remain possible. Candidate claims that it is complete are not completeness evidence.
7. **Keep deterministic checks outside the LLM where possible.** Parseability, cycles, ID existence, duplicate identifiers, and resolved source targets should be provided as validator evidence. The LLM can interpret what failures mean but should not invent validator results.
8. **Require locatable findings.** Every material defect should identify candidate nodes, supporting source nodes or screenshot region, observable mismatch, expected effect, and a minimal corrective operation. An evidence ID alone is insufficient if the judgment does not explain its relevance.
9. **Do not collapse evidence limits into quality.** Report capture limitations and candidate defects separately. Omitted content may be a candidate defect, an incomplete source capture, or genuinely absent; the judge needs evidence to distinguish them.

## Proposed calibration sequence

Begin with a deliberately varied calibration set containing good alternatives and controlled defects: redundant wrappers, detached qualifiers, duplicate narration, misleading titles, wrong native targets, inconsistent peer treatment, and visual/structural capture disagreement. Include cases where the correct answer is not assessable.

Have at least two human reviewers independently score the same cases before discussion. Where possible, include blind users with relevant navigation experience and accessibility practitioners. Preserve initial scores; adjudication should not replace the original ratings when measuring agreement. Revise unclear anchors and save reasons for changes.

Freeze rubric and examples before scoring a separate validation set. Distinguish human–human agreement, model–human agreement, and repeated-model consistency. Stratify results by criterion, site/application family, interface type, modality availability, and failure severity. Examine whether controlled defects cause the expected criterion changes while unrelated criteria remain stable. Also test meaning-preserving rewording and equivalent alternative groupings.

For operational filtering, choose provisional thresholds against adjudicated cases, inspect the mistakes near each boundary, and report critical-error miss rates separately. Human navigation studies remain necessary for the stronger claim that higher rubric ratings predict better real navigation. A calibration exercise supports clearer judgments; it does not establish that stronger claim.

## Retrieval and verification notes

- Consulted source pages and relevant passages on 2026-09-12. These are targeted sources, not an exhaustive evidence base.
- No existing Asta literature-result directory was available. The Asta CLI existed, but its authentication/DNS refresh failed; a targeted DOI metadata call was attempted with a 20-second bound. Bibliographic details were taken from publisher or institutional records instead. No Corpus IDs were invented.
- Citation keys are local to `rubric-design-references.bib`. The Preview skill, Pandoc, and Quarto were unavailable in this execution environment; citation-key existence was checked statically. No rendered bibliography or rubric reliability experiment is claimed.
