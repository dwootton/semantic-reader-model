# Semantic hierarchy pilot: results and provisional rubric

The twenty-episode smoke study is complete. All twenty saved episodes pass the harness's annotation schema, evidence-reference, and full-coverage checks. Official task evaluation records seventeen successes, two failures, and one unavailable verdict after the navigator exhausted its decision budget. Annotation validity does not establish that the annotation's interpretation is correct.

Four isolated workers passed the operational test after a VM process-lifetime fix. This supports using four workers on the existing VM for a subsequent bounded run. It does not establish an optimal concurrency setting or a causal speedup.

## Execution and concurrency

| Run G stage | New navigation episodes | Other work | Wall time | API attempts | HTTP 429 | Navigation episodes/minute |
|---|---:|---|---:|---:|---:|---:|
| Two workers | 2 | None | 6.56 min | 44 | 1 (2.3%) | 0.305 |
| Four workers | 5 | One annotation-only recovery | 11.20 min | 100 | 7 (7.0%) | 0.446 |

All seven new navigation episodes and the annotation recovery finished with valid annotations. Four distinct processes operated on independent website origins; overlapping trajectories were verified. The four-worker stage had no infrastructure errors. The observed navigation completion rate was about 46% higher, but tasks and models differed between stages, the initial two-worker gate intentionally waited for both jobs, and annotation-only work shared capacity. This is an operational observation, not a controlled concurrency comparison. A fair follow-up would replay the same balanced workload at each concurrency with repeated runs.

The ten-second minimum request spacing remains shared per model, so four workers do not multiply the allowed request rate. Requests still used standard on-demand service. Run G consumed 144 attempts, including eight 429s; cumulative pilot accounting is 529 attempts plus four separately recorded concurrency diagnostic requests, below the 650-attempt pilot ceiling.

The earlier run F finished its two-worker batch, then failed before making any four-worker API requests. The missing-semaphore traceback and VM configuration implicated login cleanup of the regular lab user's IPC objects. Installing `RemoveIPC=no` for the dedicated lab VM and restarting logind was followed by a passing detached two-to-four-process check across SSH logout, then the successful real run G. F's error-future completion rate is not throughput. G's raw four-stage job count includes one annotation-only job; the table above excludes that job from navigation throughput.

## What the trajectories reveal

**A small menu can still lead to an unproductive branch.** In the customer/descriptive/Pro episode, step 4 exposed an actionable `CUSTOMERS` link, but the navigator expanded an adjacent unnamed node. Steps 4–27 explored unnamed descendants and backtracked. The episode used 17 expansions and 10 upward moves, made no browser actions, and finished with an unsuccessful answer at step 28. Purpose and coarse Pro episodes activated `CUSTOMERS` at step 3 and reached `All Customers` at step 7 or 8. Those successful conditions also exposed unnamed siblings: the evidence concerns the interaction between representation and navigator behavior, not proof that descriptive labels caused failure. Failed trajectory (local evidence: `runs/pilot-20260912-g/episodes/t157-descriptive-gemini-3.1-pro-preview/episode.json`)

**Count useful disclosure, not just branching factor.** Invoice/source/Pro used all 28 decisions and ended while expanding generic containers on the invoice page. Its last two expansions each exposed another single generic container. One choice is a low branching factor but provides little information. By contrast, invoice/collections/Pro steps 12–15 used an invoice table group, an explicitly named invoice group, a source row, and its cells. The named group supported selecting an entity, although another unnamed-row expansion remained. Source trajectory (local evidence: `runs/pilot-20260912-g/episodes/t94-source-gemini-3.1-pro-preview/episode.json`), collection trajectory (local evidence: `runs/pilot-20260912-g/episodes/t94-collections-gemini-3.1-pro-preview/episode.json`)

**Relationships matter as much as reaching a value.** Successful invoice episodes exposed two identical `$36.39` cells without column headers in the same observation. Correct numeric output therefore does not prove that the reader preserved the relationship between the invoice identity, the requested total, and its column meaning. A rubric should require that those relationships be available without guessing from order or coincidentally identical values. Purpose/Flash step 14 (local evidence: `runs/pilot-20260912-g/episodes/t94-purpose-gemini-3.8-flash/episode.json`)

**UI changes have a reorientation cost.** Opening the Customers menu changed the snapshot on the same dashboard URL. The harness returned to the hierarchy overview and regenerated labels, after which successful navigators rediscovered the submenu. This motivates stable orientation and clear identification of newly opened content, but part of the measured cost comes from the harness's cursor-reset policy.

**Internal model judging needs factual checks.** The evidence-only judge produced 48 segments: 44 marked helpful, three costly, and one uncertain. In invoice/source/Flash, the navigator returned `50.0`; the official evaluator expected `36.39`. Nevertheless, the judge described the value as successfully retrieved, despite acknowledging that it was not explicitly shown before finishing. In another annotation it described opening a submenu as loading a new page. Valid references and complete coverage did not prevent these errors. Incorrect success interpretation (local evidence: `runs/pilot-20260912-g/episodes/t94-source-gemini-3.8-flash/annotation.json`), official verdict (local evidence: `runs/pilot-20260912-g/episodes/t94-source-gemini-3.8-flash/episode.json`)

## Provisional rubric for the next iteration

Use the following as separate dimensions, initially scored 0–2. A zero means the property is absent or contradicted by an observed example; one means partial support with material extra traversal or ambiguity; two means clear support in the tested states. Keep untested properties explicitly untested. Avoid a single weighted score until the dimensions have been validated.

| Dimension | What a good hierarchy provides | Evidence to collect |
|---|---|---|
| Grounding and reachability | Summary labels and links match real nodes; relevant content and controls remain reachable | Invalid/stale targets, omitted content, verified fallback paths |
| Action clarity | Users can distinguish activating a control from expanding structural content | Visible action opportunities bypassed, structural detours, action type preservation |
| Useful disclosure | Each level reveals meaningful distinctions or content rather than wrapper chains | Wrapper-only expansions, informative choices revealed per move, repeated exposure |
| Entity and relationship fidelity | Rows, fields, values, headings, and actions retain their identifying context | Unnamed rows, detached value/header pairs, ambiguous repeated controls |
| Orientation and recovery | Location is recognizable after state changes, and unproductive paths are escapable | Reorientation moves, revisits, failed expectations, escape-route availability and use |
| Exposure cost | Abstraction reduces unnecessary material without obscuring needed distinctions | Words and choices exposed, navigation moves, browser actions, duplicate exposure |

Annotate short navigation episodes with the observed cue, chosen action, resulting disclosure, candidate hierarchy mechanism, plausible alternative explanation, and uncertainty. Record the navigator's brief purpose and expectation separately as self-reports. Their agreement with a judge is not independent corroboration.

Internal validation should first check target IDs, action types, page-state changes, answer evidence, and consistency with official outcomes. Then use blinded model judging to propose explanations. Keep counterfactual claims provisional until tested with controlled hierarchy changes; retain human adjudication and screen-reader user validation as necessary next steps for accessibility claims.

## Scope, artifacts, and reproducibility

Raw trajectories and captures are retained locally and are not distributed with this repository. Paths below identify evidence for the original study; published aggregate counters are under `docs/results/`.

This was WebArena Verified Shopping Admin, two tasks, five conditions, two navigator models, one repetition per cell. The fixture does not represent website diversity or screen-reader users. Raw AX fallback and native shortcuts were available in every condition, but availability did not guarantee effective use. Words count serialized reader observations and repeated exposure; they are not measured spoken duration. Success is contextual evidence, not the primary optimization target.

The final source-baseline customer/Flash episode succeeded in six decisions while some semantic conditions used eight or nine; the data do not support assuming that extra hierarchy always helps. Likewise, one model's behavior in one cell does not establish a model ranking.

All 101 deployment tests passed on the VM before the parallel run. The subsequent process-lifetime fix passed a real detached process test and the real four-worker stage. Local final validation accepted all twenty complete annotations with no coverage truncation. The final archive was retrieved and SHA256-verified (`730b1f74eee4839361ebb0fb54351789bf43c436ab5a093fb0cb00a807770e8b`), and the VM was stopped while retaining its disk.

- Audited episode counters (local evidence: `runs/pilot-20260912-g/audited-episodes.csv`)
- Audited execution summary (local evidence: `runs/pilot-20260912-g/audited-summary.json`)
- Full generated trace report (local evidence: `runs/pilot-20260912-g/results.md`) — includes model interpretations that require the qualifications above
- Raw run and per-episode artifacts (local evidence: `runs/pilot-20260912-g/run.json`)
- Earlier concurrency failure audit (local evidence: `runs/pilot-20260912-f/concurrency-audit.md`)
