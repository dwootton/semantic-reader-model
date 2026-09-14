# Qwen3-8B semantic reader pilot

Train `Qwen/Qwen3-8B` with supervised LoRA, train a separate issue-critic adapter,
and export the reader to **Q4_K_M GGUF**. Q4_K_M is the deployment quantization;
the adapter is learned against native BF16 Hugging Face weights, then merged
before conversion. The base revision is
`b968826d9c46dd6066d109eabc6255188de91218`.

The first run tests whether the current labels teach the task. It does not
establish accessibility benefit or a reliable reinforcement-learning reward.
The rubric teacher scores source grounding, coverage, grouping and labels;
deterministic failures and insufficient evidence cannot earn a positive reward.
The issue-critic adapter learns the existing Pro criticism format, which differs
from the richer rubric teacher. Keep them separate when reporting results.

## Frozen data and experiment

The initial private snapshot combines completed Pro scale annotations and the
original twenty-page pilot. It freezes all 220 selected inputs before deriving
examples, groups domains, exact structural templates and duplicate documents,
and retains every consumed artifact hash. All original rights and review flags
remain unchanged: these are experimental silver labels with human review pending.

Student inputs contain the captured HTML and the same saved browser observations
available to the teacher. They exclude teacher inventories, output labels,
critiques and selection decisions. Targets use the existing outline contract.
No source or target is silently truncated. Whole overlength examples are excluded
and enumerated by tokenizer preflight.

Snapshot `runs/training-pilot-20260913/data-v2` contains 51 completed pages:
15 eligible student examples (11 train / 2 dev / 2 test), and 44 issue-critic
examples (33 / 6 / 5). At 32K tokens, six judge training examples are excluded;
27 train and 6 dev remain. Every student train/dev example fits. Original pilot
examples currently supply student holdouts, so labeler-cohort shift is an
additional limitation. The current sample is a bootstrap, not a broad benchmark.

Preregistered first comparison:

1. Evaluate the native base model's train and development completion NLL and
   deterministic development generations.
2. Run 32 optimizer steps of LoRA (rank 16, alpha 32, all linear layers,
   learning rate 0.0002, four accumulated examples, seed 42). Re-evaluate the
   same examples with the same decoding budget.
3. Train a separate issue-critic adapter from existing critiques. Its supervised
   loss is evidence about imitation of the teacher, not judge correctness.
4. Merge the student and export BF16 then Q4_K_M. Evaluate the quantized model
   against the same frozen prompts before interpreting a deployment gain.

Record source-reference validity, complete JSON generation, severe errors,
rubric profiles and per-domain results beside NLL. Falling training loss with
unchanged/worse development quality indicates overfitting or supervision mismatch.
Better NLL alone does not demonstrate useful hierarchies. Treat two held-out
pages as individual cases, not a statistically persuasive success rate.
Keep test prompts out of checkpoint selection, critique distillation and reward
calibration. Use dev for calibration and reserve test for final measurement.

Once this pipeline works, compare seeds and learning rates on the same split,
then freeze larger completed annotation snapshots with the saved split registry.
Use teacher corrections/rejection SFT or conservative preference pairs before
enabling online RL. `judge.py` provides a reward bridge that refuses uncalibrated
scores; it is not a GRPO trainer and no RL result is claimed.

## Local preparation

Run the offline suite without installing GPU dependencies:

```bash
python3 -m unittest discover -s tests -p 'test_training*.py' -q
python3 -m training.data \
  --source .asta/experiment/2026-09-13-pro-annotation-scale200/scale \
  --source .asta/experiment/2026-09-13-pro-gold-pilot20 \
  --output runs/NEW-SNAPSHOT
```

Snapshot output must be new. Preserve prior snapshots and their exclusion
ledgers. Install `training/requirements.txt` only in the dedicated GPU runtime.
Tokenizer-only preflight needs `transformers==5.8.1` and `jinja2==3.1.6`.

```bash
python -m training.train \
  --train runs/NEW-SNAPSHOT/student-train.jsonl \
  --dev runs/NEW-SNAPSHOT/student-dev.jsonl \
  --output runs/NEW-PREFLIGHT --model Qwen/Qwen3-8B \
  --revision b968826d9c46dd6066d109eabc6255188de91218 \
  --max-length 32768 --max-new-tokens 8192 --preflight-only
```

Omit `--preflight-only` on a CUDA GPU to train. Use `--purpose judge` and judge
train/dev files for the separate critic adapter. Every run writes manifests,
excluded rows, completion lengths, NLL, generations, stop reasons and summary.
Only a completed run with saved adapter qualifies for export.

## GCP and export

Only the approved lab account/project may submit jobs. The optional
`infra.prepare_training_vm` command prepares a twelve-hour A100 VM; Compute
Engine global/A100/RTX quota requests were denied on September 13. Vertex's
separate Spot A100 quota provides an alternative. Vertex job configuration and
the runtime entry point use one A100, a private mounted bucket, pinned code and
container, explicit process deadlines and durable result copies. No training
SDK discovers ADC or impersonates a user; the Vertex-managed project service
agent handles its standard bucket mount. No IAM expansion is part of this run.
Spot can be interrupted; queue time is not covered by the job execution timeout.

`training/quantize_runtime.sh` builds pinned llama.cpp in the training container,
uses a separate CPU conversion environment, and invokes `training.export`.
For an existing prepared converter toolchain:

```bash
python -m training.export --run RUN --output NEW_EXPORT \
  --llama-cpp /path/to/llama.cpp \
  --llama-cpp-revision 5f436dddb440a288ee5611d7d1eca564a6aca9f4
```

Default export is a read-only plan; `--apply` merges and quantizes. The exporter
checks adapter/base identity, tool revision, GGUF metadata/tensors and hashes.
Those checks do not measure quantized model quality. The generated Q4_K_M file
remains private and can later be loaded by llama.cpp or Ollama.

Sources: [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B),
[Qwen GGUF guide](https://qwen.readthedocs.io/en/v3.0/run_locally/llama.cpp.html),
[llama.cpp quantization](https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md),
[Vertex Spot training](https://docs.cloud.google.com/vertex-ai/docs/training/use-spot-vms),
[Vertex mounted storage](https://docs.cloud.google.com/vertex-ai/docs/training/cloud-storage-file-system).
