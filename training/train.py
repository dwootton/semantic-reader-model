"""Bounded, completion-only LoRA SFT for student or rubric-judge JSONL records.

Install training/requirements.txt in a separate Python 3.11+ environment.
Train native Hugging Face weights; GGUF Q4_K_M is a later deployment export.
No model weights are loaded by --preflight-only. --max-seconds bounds the
whole process with a Unix alarm; an outer VM deadline must also bound native
GPU calls and artifact upload, which Python cannot forcibly interrupt.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import sys
import time


def read_records(path: Path, split: str) -> list[dict]:
    records = []
    identifiers = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        where = f"{path}:{number}"
        if not isinstance(row, dict):
            raise ValueError(f"{where}: expected an object")
        for key in ("id", "domain"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"{where}: nonempty {key} required")
        if row["id"] in identifiers:
            raise ValueError(f"{where}: duplicate id {row['id']}")
        if row.get("split") != split:
            raise ValueError(f"{where}: expected split {split}")
        for field in ("prompt", "completion"):
            messages = row.get(field)
            if not isinstance(messages, list) or not messages:
                raise ValueError(f"{where}: nonempty {field} messages required")
            for message in messages:
                if (not isinstance(message, dict)
                        or message.get("role") not in {"system", "user", "assistant"}
                        or not isinstance(message.get("content"), str)
                        or not message["content"].strip()):
                    raise ValueError(f"{where}: text-only chat messages required")
        if row["prompt"][-1]["role"] != "user":
            raise ValueError(f"{where}: prompt must end with a user message")
        if len(row["completion"]) != 1 or row["completion"][0]["role"] != "assistant":
            raise ValueError(f"{where}: one assistant completion required")
        identifiers.add(row["id"])
        records.append(row)
    if not records:
        raise ValueError(f"{path}: {split} must not be empty")
    return records


def assert_disjoint(train: list[dict], dev: list[dict]) -> None:
    for field in ("id", "domain"):
        normalize = (lambda value: value.strip().lower().rstrip(".")) if field == "domain" else str
        overlap = {normalize(row[field]) for row in train} & {normalize(row[field]) for row in dev}
        if overlap:
            raise ValueError(f"train/dev {field} overlap: {sorted(overlap)[:10]}")


def chat_token_ids(tokenizer, messages: list[dict], *, add_generation_prompt: bool) -> list[int]:
    result = tokenizer.apply_chat_template(
        messages, add_generation_prompt=add_generation_prompt, tokenize=True,
        enable_thinking=False, truncation=False, return_dict=False,
    )
    # Some tokenizer versions/wrappers return BatchEncoding even for a single chat.
    if isinstance(result, Mapping):
        result = result.get("input_ids")
    if not isinstance(result, (list, tuple)) or any(type(token) is not int or token < 0 for token in result):
        raise ValueError("Chat template must return one flat sequence of integer token IDs")
    return list(result)


def encode_record(row: dict, tokenizer) -> dict:
    """Fail closed if the training template differs from the generation prefix."""
    prompt = chat_token_ids(tokenizer, row["prompt"], add_generation_prompt=True)
    full = chat_token_ids(tokenizer, row["prompt"] + row["completion"], add_generation_prompt=False)
    if not prompt or full[:len(prompt)] != prompt:
        raise ValueError(f"{row['id']}: chat template prompt is not an exact token prefix")
    if len(full) <= len(prompt):
        raise ValueError(f"{row['id']}: no completion tokens")
    return {**row, "input_ids": full, "prompt_ids": prompt,
            "labels": [-100] * len(prompt) + full[len(prompt):],
            "completion_tokens": len(full) - len(prompt)}


def prepare_records(records: list[dict], tokenizer, max_length: int) -> tuple[list[dict], list[dict]]:
    accepted, excluded = [], []
    for row in records:
        encoded = encode_record(row, tokenizer)
        if len(encoded["input_ids"]) > max_length:
            excluded.append({"id": row["id"], "domain": row["domain"], "split": row["split"],
                             "reason": "overlength", "tokens": len(encoded["input_ids"]),
                             "prompt_tokens": len(encoded["prompt_ids"]),
                             "completion_tokens": encoded["completion_tokens"]})
        else:
            accepted.append(encoded)
    return accepted, excluded


def select_evaluation(records: list[dict], limit: int, seed: int) -> list[dict]:
    selected = sorted(records, key=lambda row: row["id"])
    random.Random(seed).shuffle(selected)
    return selected[:limit]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def append_json(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--dev", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--revision", required=True, help="Immutable 40-character model commit SHA")
    parser.add_argument("--purpose", choices=("student", "judge"), default="student")
    parser.add_argument("--max-length", type=int, default=8192)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-seconds", type=int, default=3600)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--gradient-accumulation", type=int, default=4)
    parser.add_argument("--eval-limit", type=int, default=16)
    parser.add_argument("--train-eval-limit", type=int, default=8)
    parser.add_argument("--generation-limit", type=int, default=2)
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    parser.add_argument("--generation-seconds", type=int, default=600)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-fA-F0-9]{40}", args.revision):
        parser.error("--revision must be an immutable 40-character commit SHA")
    for name in ("max_length", "max_steps", "max_seconds", "gradient_accumulation", "eval_limit",
                 "train_eval_limit", "max_new_tokens", "generation_seconds"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.generation_limit < 0 or not math.isfinite(args.learning_rate) or args.learning_rate <= 0:
        parser.error("generation limit must be nonnegative and learning rate must be finite and positive")
    return args


def generation_cap(row: dict, max_length: int, max_new_tokens: int) -> int:
    cap = min(max_new_tokens, max_length - len(row["prompt_ids"]))
    if cap < row["completion_tokens"]:
        raise ValueError(
            f"{row['id']}: generation cap {cap} cannot cover {row['completion_tokens']} reference tokens; "
            "increase --max-new-tokens or --max-length",
        )
    return cap


def generation_stop_reason(tokens: list[int], eos_token_id: int, cap: int, elapsed: float, seconds: float) -> str:
    if tokens and tokens[-1] == eos_token_id:
        return "eos"
    if len(tokens) >= cap:
        return "token_limit"
    if elapsed >= seconds:
        return "time_limit"
    return "other"


def load_model(args, torch):
    from transformers import AutoConfig, AutoModelForCausalLM, Qwen3_5ForCausalLM, Qwen3_5TextConfig

    config = AutoConfig.from_pretrained(args.model, revision=args.revision, trust_remote_code=False)
    if config.model_type == "qwen3":
        model_class = AutoModelForCausalLM
    elif config.model_type in {"qwen3_5", "qwen3_5_text"}:
        config = Qwen3_5TextConfig.from_pretrained(args.model, revision=args.revision)
        model_class = Qwen3_5ForCausalLM
    else:
        raise ValueError("This runner supports native dense Qwen3 or Qwen3.5 Hugging Face weights")
    if args.max_length > config.max_position_embeddings:
        raise ValueError("--max-length exceeds the model's configured context length")
    return model_class.from_pretrained(
        args.model, revision=args.revision, config=config, trust_remote_code=False,
        dtype=torch.bfloat16, attn_implementation="sdpa", output_loading_info=True,
    )


def completion_loss(model, row: dict, torch):
    """Only project completion positions into the large vocabulary, plus their predecessor."""
    device = next(model.parameters()).device
    input_ids = torch.tensor([row["input_ids"]], dtype=torch.long, device=device)
    target_count = row["completion_tokens"]
    logits = model(input_ids=input_ids, attention_mask=torch.ones_like(input_ids),
                   use_cache=False, logits_to_keep=target_count + 1).logits
    targets = input_ids[:, -target_count:]
    return torch.nn.functional.cross_entropy(
        logits[:, :-1, :].float().reshape(-1, logits.shape[-1]), targets.reshape(-1),
    )


def evaluate(model, tokenizer, rows, args, stage, torch, deadline, *, split="dev", generate=True):
    model.eval()
    total_nll, total_tokens = 0.0, 0
    with torch.no_grad():
        for row in rows:
            loss = float(completion_loss(model, row, torch).item())
            if not math.isfinite(loss):
                raise RuntimeError(f"Nonfinite {stage} {split} loss for {row['id']}")
            total_nll += loss * row["completion_tokens"]
            total_tokens += row["completion_tokens"]
            append_json(args.output / f"{split}_nll.jsonl", {
                "id": row["id"], "domain": row["domain"], "candidate_id": stage, "split": split,
                "nll": loss, "completion_tokens": row["completion_tokens"],
            })
        for row in rows[:args.generation_limit] if generate else []:
            device = next(model.parameters()).device
            inputs = torch.tensor([row["prompt_ids"]], dtype=torch.long, device=device)
            cap = generation_cap(row, args.max_length, args.max_new_tokens)
            generation_started = time.monotonic()
            seconds = min(float(args.generation_seconds), deadline - generation_started)
            if seconds <= 0:
                raise TimeoutError("No run time remains for generation")
            generated = model.generate(
                input_ids=inputs, attention_mask=torch.ones_like(inputs), do_sample=False,
                max_new_tokens=cap, max_time=seconds,
                pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id,
                use_cache=True,
            )[0, inputs.shape[1]:].tolist()
            elapsed = time.monotonic() - generation_started
            stop_reason = generation_stop_reason(generated, tokenizer.eos_token_id, cap, elapsed, seconds)
            append_json(args.output / "predictions.jsonl", {
                "id": row["id"], "domain": row["domain"], "candidate_id": stage, "split": split,
                "output": tokenizer.decode(generated, skip_special_tokens=True),
                "reference": row["completion"][0]["content"], "generated_tokens": len(generated),
                "max_new_tokens": cap, "finished_eos": stop_reason == "eos", "stop_reason": stop_reason,
                "generation_seconds": round(elapsed, 3), "max_time_seconds": seconds,
                "reference_tokens": row["completion_tokens"],
            })
    return {"nll": total_nll / total_tokens, "completion_tokens": total_tokens, "examples": len(rows)}


def run(args, summary, started):
    train = read_records(args.train, "train")
    dev = read_records(args.dev, "dev")
    assert_disjoint(train, dev)
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    train, train_excluded = prepare_records(train, tokenizer, args.max_length)
    dev, dev_excluded = prepare_records(dev, tokenizer, args.max_length)
    rows = select_evaluation(dev, args.eval_limit, args.seed)
    generation_rows = rows[:args.generation_limit]
    for row in train_excluded + dev_excluded:
        append_json(args.output / "excluded.jsonl", row)
    preflight = {"train_examples": len(train), "dev_examples": len(dev),
                 "excluded_train": len(train_excluded), "excluded_dev": len(dev_excluded),
                 "max_length": args.max_length, "truncation": False,
                 "train_ids": [row["id"] for row in train], "dev_ids": [row["id"] for row in dev],
                 "train_tokens": sum(len(row["input_ids"]) for row in train),
                 "train_completion_tokens": sum(row["completion_tokens"] for row in train),
                 "generation_ids": [row["id"] for row in generation_rows],
                 "generation_reference_max_tokens": max((row["completion_tokens"] for row in generation_rows), default=0),
                 "chat_template_sha256": hashlib.sha256(tokenizer.chat_template.encode()).hexdigest()}
    write_json(args.output / "preflight.json", preflight)
    summary["preflight"] = preflight
    if not train or not dev:
        raise ValueError("No usable train or dev examples after length preflight; sources were not truncated")
    for row in generation_rows:
        generation_cap(row, args.max_length, args.max_new_tokens)
    if args.preflight_only:
        summary["status"] = "preflight_complete"
        return

    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import set_seed

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("Training requires a CUDA GPU with native bfloat16 support")
    set_seed(args.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.use_deterministic_algorithms(True, warn_only=True)
    model, diagnostics = load_model(args, torch)
    # Transformers 5.8.1 converts model.language_model.* into model.* for text loading.
    # Missing text weights would otherwise silently initialize a partly random model.
    diagnostics = {key: sorted(value) if isinstance(value, set) else value
                   for key, value in diagnostics.items()}
    write_json(args.output / "model_loading.json", diagnostics)
    if any(diagnostics.get(name) for name in ("missing_keys", "mismatched_keys", "error_msgs")):
        raise RuntimeError("Checkpoint did not fully initialize text weights; inspect model_loading.json")
    unexpected = [key for key in diagnostics.get("unexpected_keys", [])
                  if not key.startswith(("model.visual.", "mtp.", "model.mtp."))]
    if unexpected:
        raise RuntimeError(f"Unexpected nonvision checkpoint weights: {unexpected[:10]}")
    model.to("cuda")
    model.config.use_cache = False
    train_rows = select_evaluation(train, args.train_eval_limit, args.seed)
    summary["eval_ids"] = [row["id"] for row in rows]
    summary["train_eval_ids"] = [row["id"] for row in train_rows]
    summary["cuda"] = {"device": torch.cuda.get_device_name(0), "torch_cuda": torch.version.cuda}
    deadline = started + args.max_seconds
    summary["base_train"] = evaluate(model, tokenizer, train_rows, args, "base", torch, deadline,
                                     split="train", generate=False)
    summary["base_dev"] = evaluate(model, tokenizer, rows, args, "base", torch, deadline)
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.0, target_modules="all-linear",
        bias="none", task_type=TaskType.CAUSAL_LM, revision=args.revision,
    ))
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    summary["trainable_parameters"] = sum(parameter.numel() for parameter in parameters)
    optimizer = torch.optim.AdamW(parameters, lr=args.learning_rate)
    rng = random.Random(args.seed)
    order: list[int] = []
    summary["optimizer_steps"] = 0
    model.train()
    try:
        for step in range(args.max_steps):
            # Keep a quarter of the remaining budget for the paired post-SFT evaluation.
            if time.monotonic() >= started + args.max_seconds * 0.75:
                summary["training_stop_reason"] = "evaluation_time_reserve"
                break
            optimizer.zero_grad(set_to_none=True)
            losses = []
            for _ in range(args.gradient_accumulation):
                if not order:
                    order = list(range(len(train)))
                    rng.shuffle(order)
                row = train[order.pop()]
                loss = completion_loss(model, row, torch)
                value = float(loss.detach().item())
                if not math.isfinite(value):
                    raise RuntimeError(f"Nonfinite train loss for {row['id']}")
                (loss / args.gradient_accumulation).backward()
                losses.append(value)
            norm = torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            if not math.isfinite(float(norm)):
                raise RuntimeError("Nonfinite adapter gradients")
            optimizer.step()
            summary["optimizer_steps"] = step + 1
            record = {"step": step + 1, "loss": sum(losses) / len(losses),
                      "elapsed_seconds": round(time.monotonic() - started, 2)}
            append_json(args.output / "train_metrics.jsonl", record)
            print(json.dumps(record), flush=True)
    finally:
        if summary["optimizer_steps"]:
            model.save_pretrained(args.output / "adapter", safe_serialization=True)
            tokenizer.save_pretrained(args.output / "adapter")
            summary["adapter_saved"] = True
    if not summary["optimizer_steps"]:
        raise RuntimeError("Budget expired before any optimizer step; increase max-seconds")
    summary["sft_train"] = evaluate(model, tokenizer, train_rows, args, "sft", torch, deadline,
                                    split="train", generate=False)
    summary["sft_dev"] = evaluate(model, tokenizer, rows, args, "sft", torch, deadline)
    summary["train_nll_delta"] = summary["sft_train"]["nll"] - summary["base_train"]["nll"]
    summary["dev_nll_delta"] = summary["sft_dev"]["nll"] - summary["base_dev"]["nll"]
    summary["status"] = "complete"


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Output directory must be empty to preserve earlier run evidence")
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    manifest = {"arguments": {name: str(value) if isinstance(value, Path) else value
                              for name, value in vars(args).items()},
                "python": sys.version, "model_revision": args.revision,
                "files_sha256": {str(path): sha256(path) for path in (
                    args.train, args.dev, Path(__file__), Path(__file__).with_name("requirements.txt"),
                )},
                "packages": {distribution.metadata["Name"]: distribution.version
                             for distribution in importlib.metadata.distributions()}}
    write_json(args.output / "manifest.json", manifest)
    summary = {"status": "running", "purpose": args.purpose}

    def timeout(signum, frame):
        raise TimeoutError("Run exceeded --max-seconds")

    previous = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, args.max_seconds)
    try:
        run(args, summary, started)
    except Exception as error:
        summary.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        summary["elapsed_seconds"] = round(time.monotonic() - started, 2)
        write_json(args.output / "summary.json", summary)
        print(json.dumps(summary, sort_keys=True, allow_nan=False), flush=True)
    return 0 if summary["status"] in {"complete", "preflight_complete"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
