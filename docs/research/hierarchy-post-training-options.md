---
title: Post-training options for regional semantic hierarchies
date: 2026-09-12
---

# Post-training options for regional semantic hierarchies

**Recommendation: begin with supervised distillation, then try preference training; use online RL only after the judge is calibrated.** This is a project hypothesis, not a measured result. Existing zero-shot compact GOV.UK results do not establish the ceiling of a trained 2B model, and no available evidence supports a numerical forecast for matching Flash on this task.

## What each training method changes

Fine-tuning means updating an already trained model. Supervised fine-tuning (SFT), preference optimization, and reinforcement learning can all be forms of post-training; they differ principally in the feedback and objective.

| Method | Data for this project | Learning signal |
|---|---|---|
| SFT | Compact region + context → reviewed target groups, boundaries, title references | Increase the probability of the target tokens. The trainer learns from input/output examples using token-level likelihood. [TRL SFT](https://huggingface.co/docs/trl/sft_trainer) |
| DPO | Same input + preferred tree + rejected tree | Learn a preference between completions relative to a reference model. Standard offline DPO needs no separate reward model or fresh generation during each training step. [TRL DPO](https://huggingface.co/docs/trl/dpo_trainer) |
| Online RL, such as GRPO | Region prompts + reward evaluator | Sample several trees from the current student, score them, and update the student using their relative rewards; repeat with new student outputs. [TRL GRPO](https://huggingface.co/docs/trl/grpo_trainer) |

Using an LLM judge as the reward source is reinforcement learning from AI feedback. Asking a judge to choose a tree at inference time does **not** train the model. Training on accepted teacher trees is supervised distillation, even when a judge filters the examples.

## Practical sequence for this project

These steps are proposed experiments, not established sample-size or performance requirements.

1. Freeze the compact regional input and minimal output contract. Keep IDs, preserved source content, and deterministic composition in code. Every training target must be inferable from the student's exposed evidence. Teacher access to omitted controls, screenshots, or extra context creates an evidence mismatch unless that information also reaches the student.
2. Collect reviewed teacher examples across interface families. Preserve full captures, regional slices, targets, corrections, and provenance. Split by site/template family before deriving regions. Keep multiple defensible trees where applicable; exact teacher JSON equality is an unsuitable success criterion.
3. Train SFT first, comparing learning curves as reviewed data increases. Review grouping mistakes rather than only serialization errors. Retain separate evaluation of local groups and assembled pages.
4. Sample multiple student trees per region. Have the calibrated judge and human spot checks identify clear preferences; preserve ties, insufficient evidence, and severe failures. Compare DPO against another SFT round using corrected/accepted samples.
5. Consider GRPO only if student candidates contain meaningful quality variation and the evaluator reliably recognizes it. Otherwise RL may optimize format or judge artifacts without learning better navigation. Online generation and judging also add training cost that offline SFT does not require.

## Turning this rubric into an RL reward

The current rubric is a profile of ordinal dimensions with hard gates, not an already validated scalar reward. Contract tests and synthetic smoke cases establish software behavior; they do not establish agreement with human judgments. See the project's [judge evidence and calibration plan](llm-judge-evidence.md).

A proposed reward pipeline would first apply deterministic integrity and source-reference checks, then assess grounded semantic quality on the declared scope. Hard failures must not be canceled by attractive labels or extra groups. Unknown evidence must not count as success. Any scalar mapping or preference rule needs explicit calibration; blindly averaging 0–3 dimensions would assume unsupported comparability between criteria.

Keep an independent human-reviewed evaluation set and test candidate mutations: unnecessary groups, omitted qualifiers, false memberships, redundant labels, and unsupported expansion claims. Prefer grounded content over free-form explanations. Reward length savings only after sufficient semantic quality, or omission becomes an easy shortcut. A recent controlled rubric-RL study reproduces policies exploiting injected judge biases; it establishes the failure mechanism, not its rate in this project. [CHERRL, 2026](https://arxiv.org/abs/2606.04923)

## Can 2B match the teacher?

It is plausible that a student can approach teacher usefulness on bounded, recurring region types. That is weaker than matching a large model on arbitrary unseen interfaces or complete pages, and remains unmeasured here. DeepSeek-R1 distilled teacher-generated examples into models down to 1.5B using SFT alone; its separate 32B experiment favored distillation over its RL-only recipe. Those reasoning results support the possibility of substantial specialization, not an expected hierarchy success rate or a claim that 2B will reproduce Flash. [DeepSeek-R1, §§2.4, 3.2, 4.1](https://arxiv.org/html/2501.12948v1)

Define success before forecasting it: blind preference versus Flash on identical evidence, semantic acceptance without substantial correction, severe-error frequency, and end-to-end task navigation. Report held-out site/template performance and uncertainty; regions from one page are correlated. A high local pass rate does not imply that a page with many regions is error-free. Evaluate the 10–15-second target on final quantized inference separately: training can teach concise outputs, but does not inherently make each generated token faster.

## Full fine-tuning versus LoRA

Full fine-tuning changes the base weights; LoRA freezes them and trains added low-rank updates. More trainable parameters give full fine-tuning more freedom, but do not establish a predictable quality gain on this task.

Thinking Machines' experiments found LoRA could match full fine-tuning under suitable conditions. They used Llama 3/Qwen3 models, Tulu3/OpenThoughts3 supervision, ranks 1–512, and separate learning-rate sweeps; supervised results chiefly measured log loss. Their conditions included enough adapter capacity, targeting MLP/all layers rather than attention alone, and suitable batch sizes. Larger datasets could exhaust adapter capacity, and large batches produced additional gaps. Their low-rank RL results used mathematical answer rewards. These findings do not prove equal semantic hierarchy quality for Qwen3.5 2B, and the authors explicitly leave precise performance forecasts open. [LoRA Without Regret](https://thinkingmachines.ai/blog/lora/)

**Project hypothesis:** first establish a tuned LoRA baseline, then run a controlled full-fine-tuning comparison on the same 2B checkpoint, data split, and output contract. Tune each method's learning rate rather than copying one setting between them. Report both semantic quality and compute cost; match training exposure while recording any hyperparameter-search advantage. If additional LoRA capacity stops helping and full fine-tuning gives a repeatable held-out gain worth its cost, choose full fine-tuning. A 2B model is small enough that this comparison is a practical experiment rather than a permanent architectural commitment.

Our rough untuned labels do not distinguish a parameter-update limitation from missing supervision. Neither method can reliably reconstruct facts that the intentionally partial compact input does not expose. Preserve that evidence boundary when interpreting any improvement.

## What survives a model refresh

PEFT checkpoints normally contain adapter parameters rather than the base weights; configuration identifies the base model and revision, and loading an adapter requires a base model. [PEFT checkpoint format](https://huggingface.co/docs/peft/main/en/developer_guides/checkpoint), [PEFT loading API](https://huggingface.co/docs/peft/main/en/package_reference/peft_model). Consequently, treat an adapter as tied to its trained base checkpoint. A new model may use different layers or shapes; even a compatible shape does not establish that the old update produces useful behavior. A fully fine-tuned checkpoint is likewise its own model, not an automatic improvement that transfers to the next release.

The durable project assets are source captures, reviewed source-backed annotations, acceptable alternatives, correction histories, rubric definitions, held-out evaluations, the compactor, and deterministic assembly. Reuse those to evaluate and, if needed, retrain a newer base. Revalidate token budgets, evidence coverage, chat templates, output serialization, judge calibration, and deployment quality when components change; model-neutral data is more reusable than saved token IDs or model-specific prompts.

Preserving the old base/checkpoint, tokenizer, adapter configuration, and compatible runtime keeps the existing trained system usable. A new release does not invalidate it. Compare the new untuned model against that working baseline, and migrate only when quality, latency, or maintenance benefits justify the retraining and validation cost. These are engineering recommendations, not guarantees that every annotation or adapter can transfer unchanged.
