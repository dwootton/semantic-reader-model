---
title: Data and compute budget for a 2B regional hierarchy pilot
date: 2026-09-12
---

# Data and compute budget for a 2B regional hierarchy pilot

**Planning recommendation: start with 1,000 reviewed regional examples and one L4 GPU using LoRA; move toward 5,000 examples if held-out quality improves.** These are staged experiment sizes, not known requirements for success. None of the training runtimes below has been measured for this project.

## Hardware and published cost

The following are public **US-central1 (Iowa), USD on-demand prices checked September 12, 2026**. These prices cover the complete predefined VM, including its GPU, CPU, RAM, and bundled Local SSD where applicable. Boot/persistent disks, network charges, premium OS licenses, and external model APIs are separate. They are not GPU-only rates or Spot prices. [Google pricing](https://cloud.google.com/products/compute/pricing/accelerator-optimized)

| VM | GPU memory | Host resources | Total VM/hour |
|---|---|---|---:|
| `g2-standard-4` | 1 × L4, 24 GB | 4 vCPU, 16 GiB RAM | $0.706832276 ≈ **$0.71** |
| `g2-standard-8` | 1 × L4, 24 GB | 8 vCPU, 32 GiB RAM | $0.853624312 ≈ **$0.85** |
| `a2-highgpu-1g` | 1 × A100, 40 GB | 12 vCPU, 85 GiB RAM | $3.673385 ≈ **$3.67** |
| `a2-ultragpu-1g` | 1 × A100, 80 GB | 12 vCPU, 170 GiB RAM | $5.06879789 ≈ **$5.07** |

GPU counts/memory come from [Google's machine specifications](https://docs.cloud.google.com/compute/docs/gpus). The larger G2 gives more CPU/RAM, **not** a faster or larger GPU. A2 is a fallback for more memory or a measured throughput advantage; a higher hourly price alone does not determine total job cost. Quota, regional stock, actual account discounts, and deployment availability have not been checked. No cloud resources were created.

For BF16 LoRA, approximately 2 billion frozen parameters occupy approximately **4 GB for base weights alone**. LoRA trains small added matrices while freezing the base weights. This makes a 24 GB L4 a plausible starting point with short sequences, small microbatches, and activation checkpointing; the remaining memory must cover activations, adapters, gradients, optimizer state, and runtime buffers. This is an estimate, not a demonstrated fit for our exact model/kernel stack. [Hugging Face LoRA](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)

For full fine-tuning, a conventional mixed-precision Adam accounting is roughly **18 bytes/parameter**, or **36 GB before activations** for 2B parameters. A100 40 GB can therefore be tight; A100 80 GB is a more comfortable planning choice. Native BF16, optimizer precision, checkpointing, and other implementations change this estimate. [Hugging Face memory accounting](https://huggingface.co/docs/transformers/main/model_memory_anatomy)

## Data volume and runtime arithmetic

For collection planning, aim at 5,000–20,000 accepted regional training examples, but train on the first 1,000 before committing to the rest. These are learning-curve checkpoints, not thresholds that guarantee the capability. The eventual collection should cover thousands of distinct interface states and hundreds of site/template families, including forms, tables, repeated cards, menus, dialogs, and error/empty/selected states. Repeated pages or alternative compressions of one capture are correlated augmentations, not independent layouts.

Reserve an additional 500–1,000 independently reviewed regional examples for development and final evaluation, with sites/template families separated before extracting crops. Include assembled-page checks. Teacher labels can supply most training targets; use human review to calibrate the judge, audit a stratified sample, and correct recurrent failures. Automated acceptance produces silver training labels, not human gold.

Store the compact region and exact model-visible context, target grouping/title references, expansion decisions, compression settings, source hashes and site/template lineage. Preserve full captures locally, but do not supervise unobserved facts. Freeze the short output format before bulk labeling so training does not lock in the verbose generation that currently dominates local latency.

Assume **1,500 total sequence tokens/example and 3 epochs**. This rounds above the observed compact regional inputs plus short targets to allow context and example variation. Prompt tokens still incur compute when training loss is restricted to the answer.

| Reviewed training regions | Unique sequence tokens | Tokens processed over 3 epochs |
|---|---:|---:|
| 1,000 | 1.5 million | 4.5 million |
| 5,000 | 7.5 million | 22.5 million |
| 20,000 | 30 million | 90 million |

Hold out additional sites/templates for development and final evaluation. Regional slices from one page are correlated; 5,000 slices from a few templates do not provide 5,000 independent layout examples. Dataset diversity and annotation consistency are likely to matter more than reaching an arbitrary count.

Measure a representative training segment before extrapolating:

`training hours = processed sequence tokens / measured non-padding tokens per second / 3600`

Then add initialization, evaluation, checkpointing, and unsuccessful runs. For illustration only, **if** measured throughput were 500 tokens/second, the table's runs would require 2.5, 12.5, and 50 training hours. At 1,500 tokens/second they would require 0.83, 4.17, and 16.67 hours. Neither rate is a prediction or hardware benchmark.

As a spending allowance rather than a runtime promise, 24 hours of `g2-standard-8` costs about **$20.49**; 100 hours costs **$85.36**. A100 80 GB costs about **$121.65 for 24 hours**. Repeated experiments and evaluation multiply these amounts.

## Keep the other budgets separate

- **Teacher generation and judge API usage:** budget input/output tokens per exact model, rubric length, candidate count, and retry rate. This note does not assume a price for an unverified Flash model name.
- **Human review:** measure minutes per reviewed/corrected region; multiply by the number actually reviewed and the reviewer's rate. Annotation effort may dominate an inexpensive LoRA run.
- **Preference training and RL:** DPO processes preferred/rejected outputs and reference scores; online RL repeatedly generates candidates and obtains rewards. Do not reuse an SFT token budget as their cost estimate. Establish SFT quality and judge calibration first.
- **Deployment:** export and quantize the trained model, then measure local page latency and held-out quality. Cheap cloud training does not establish the 10–15-second inference target.
