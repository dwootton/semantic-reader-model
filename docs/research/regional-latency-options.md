# Preserved compact input: local regional latency

Measured 2026-09-13 with local Ollama Qwen3.5:2b, not Gemma. The saved GOV.UK passport capture uses the current semantic-preserving compactor, 316 exposed references and five partitions at region size 160. Compression was prepared offline. No fine-tuning or cloud inference was used.

## Result

Full candidate-selection run `ebf07ec9da0245c9804f25641a875b79` completed in **8.513 seconds**: five calls, 9,234 input tokens, 153 output tokens, 14 groups. It assigned 279/316 exposed references; 37 remain in fallback. All 107 controls in the audited source remain exposed. Coverage is assignment coverage, not semantic accuracy or original-page completeness.

This is one warmed-model run on one capture, not a general 10–15 second guarantee. Loading, other hardware, larger pages and cold prompts can change latency. The full standard run failed its first section on duplicate membership, so there is no successful full-page baseline for this exact input.

## Independent section probes

| Method | Section 1 | Section 2 | Section 3 | Valid outputs |
| --- | ---: | ---: | ---: | ---: |
| Standard explicit groups/membership | 6.78 s | 9.35 s | 18.26 s | 2/3 |
| Numeric aliases and ranges | 8.09 s | 10.72 s | 6.95 s | 0/3 |
| Model chooses root/title pairs | 7.59 s | 5.90 s | 4.78 s | 0/3 |
| Select prebound candidates | 1.18 s | 3.16 s | 2.95 s | 3/3 |

The selection probes generated 21–45 output tokens versus 357–871 for standard prediction. Input HTML and partition evidence were preserved; deterministic candidate hints were added. The narrower task and shorter outputs are the intervention, not further content removal. Numeric output failed duplicate/context-range validation; independent root/title prediction selected incompatible pairs. These failed alternatives remain experiment-only, outside the UI.

Each section has one sample. Standard and numeric probes alternated; later alternatives ran in subsequent batches, so cache/order effects are not controlled. Records and source evidence hashes are in `runs/latency/semantic-{regions,anchors,selection}-20260913/report.json`.

## What selection can and cannot do

Code proposes source containers named by explicit labels or their first eligible heading, including ARIA headings. The model selects candidate IDs. Code derives titles, retained owned membership and nesting, reusing existing validation and assembly. Up to 24 candidates are offered per call; overflow is warned about and does not remove HTML. Unselected sources remain available in fallback.

The result includes sensible passport, navigation and support groups, but also two distinct groups named “Help us improve GOV.UK.” A container can encompass several topics while inheriting only its first heading. The model cannot invent cross-branch groups or better custom names. Mechanical validity and speed therefore do not establish Flash-quality semantic hierarchies.

## Try it and next experiments

In the comparison UI, choose **Compact · select proposed groups**, then **Compose regions**. Standard compact and original DOM modes remain available. Review titles, useful boundaries, control associations and fallback, not just coverage.

Reproduce independent probes:

```sh
python3 experiments/regional-speed/benchmark.py --output runs/latency/my-comparison --regions 3 --methods standard selection
```

Next, compare against a deterministic select-all-candidates baseline to establish whether the model's selection adds value. Evaluate repeated warm/cold timings and the existing semantic rubric on held-out forms, articles, navigation and large repetitive pages. Report invalid-output rate and median/p95 latency separately from semantic quality.

For further latency improvements, cache unchanged regions using hashes of their evidence, context, proposals, model and prompt version; prioritize the currently opened region and progressively organize others. These are proposed next steps, not implemented here. Richer heading-delimited candidates and a small optional label/boundary correction task could recover expressiveness while keeping output short, but need separate quality testing before training targets are fixed.
