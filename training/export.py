"""Plan or apply a pinned Qwen3-8B PEFT merge and Q4_K_M GGUF export.

Default --plan-only reads local evidence without loading models or writing output.
--apply may download the exact training base revision, then merges on CPU. Supply
an existing clean llama.cpp checkout with its converter requirements and compiled
build/bin/llama-quantize; this command never installs or builds dependencies.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


SCHEMA = "semantic-reader-gguf-export/1"
MODEL = "Qwen/Qwen3-8B"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def commit_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", value):
        raise ValueError(f"{name} must be an exact 40-character commit SHA")
    return value.lower()


def git(checkout: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(checkout), *arguments], check=True,
                          capture_output=True, text=True).stdout.strip()


def validate_toolchain(checkout: Path, revision: str) -> dict:
    revision = commit_sha(revision, "llama.cpp revision")
    if Path(git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout:
        raise ValueError("--llama-cpp must name the checkout root")
    if git(checkout, "rev-parse", "HEAD").lower() != revision:
        raise ValueError("llama.cpp checkout does not match its pinned revision")
    if git(checkout, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"):
        raise ValueError("llama.cpp checkout has modified or untracked source files")
    converter = checkout / "convert_hf_to_gguf.py"
    quantizer = checkout / "build" / "bin" / "llama-quantize"
    for path in (converter, quantizer, checkout / "gguf-py" / "gguf" / "__init__.py"):
        if not path.is_file() or not path.resolve().is_relative_to(checkout):
            raise ValueError(f"Required tool must exist inside pinned checkout: {path}")
    if not os.access(quantizer, os.X_OK):
        raise ValueError("llama-quantize must be executable")
    return {"checkout": str(checkout), "revision": revision,
            "converter": str(converter), "converter_sha256": sha256(converter),
            "quantizer": str(quantizer), "quantizer_sha256": sha256(quantizer),
            "binary_provenance": "Binary bytes hashed; checkout revision verified; build reproducibility not independently attested."}


def build_plan(run: Path, output: Path, llama_cpp: Path, llama_cpp_revision: str,
               outtype: str = "bf16") -> dict:
    run, output, llama_cpp = run.resolve(), output.resolve(), llama_cpp.resolve()
    if output.exists():
        raise FileExistsError(f"Export output already exists: {output}")
    if outtype not in {"bf16", "f16"}:
        raise ValueError("Intermediate GGUF must be bf16 or f16")
    manifest = read_json(run / "manifest.json")
    summary = read_json(run / "summary.json")
    if (summary.get("status") != "complete" or summary.get("adapter_saved") is not True
            or type(summary.get("optimizer_steps")) is not int or summary["optimizer_steps"] <= 0):
        raise ValueError("Export requires a successful training summary with a saved, trained adapter")
    arguments = manifest.get("arguments", {})
    model = arguments.get("model")
    if model != MODEL:
        raise ValueError(f"This exporter requires training base {MODEL}")
    revision = commit_sha(arguments.get("revision"), "training base revision")
    if commit_sha(manifest.get("model_revision"), "manifest model revision") != revision:
        raise ValueError("Training manifest contains inconsistent base revisions")
    adapter = run / "adapter"
    adapter_config = read_json(adapter / "adapter_config.json")
    if adapter_config.get("base_model_name_or_path") != model:
        raise ValueError("Adapter base model does not match the training manifest")
    if commit_sha(adapter_config.get("revision"), "adapter base revision") != revision:
        raise ValueError("Adapter base revision does not match the training manifest")
    if adapter_config.get("peft_type") != "LORA" or adapter_config.get("task_type") != "CAUSAL_LM":
        raise ValueError("Expected a causal-LM LoRA adapter")
    if not (adapter / "adapter_model.safetensors").is_file():
        raise ValueError("Missing safe adapter weights: adapter/adapter_model.safetensors")
    for required in ("tokenizer_config.json", "tokenizer.json"):
        if not (adapter / required).is_file():
            raise ValueError(f"Missing training tokenizer artifact: adapter/{required}")
    tools = validate_toolchain(llama_cpp, llama_cpp_revision)
    merged = output / "merged-hf"
    intermediate = output / f"model-{outtype.upper()}.gguf"
    quantized = output / "model-Q4_K_M.gguf"
    adapter_files = sorted(path for path in adapter.rglob("*") if path.is_file())
    if any(not path.resolve().is_relative_to(adapter) for path in adapter_files):
        raise ValueError("Adapter artifacts must not link outside the training adapter directory")
    return {
        "schema": SCHEMA, "status": "planned", "model_loaded": False,
        "run": str(run), "output": str(output), "base_model": model, "base_revision": revision,
        "adapter": str(adapter), "merge_device": "cpu", "intermediate_type": outtype,
        "quantization": "Q4_K_M", "toolchain": tools,
        "artifacts": {"merged_hf": str(merged), "intermediate_gguf": str(intermediate), "quantized_gguf": str(quantized)},
        "commands": [
            {"stage": "merge", "operation": "PeftModel.from_pretrained(...).merge_and_unload(safe_merge=True)",
             "base_model": model, "revision": revision, "adapter": str(adapter), "output": str(merged)},
            {"stage": "convert", "argv": [sys.executable, tools["converter"], str(merged), "--outfile", str(intermediate), "--outtype", outtype]},
            {"stage": "quantize", "argv": [tools["quantizer"], str(intermediate), str(quantized), "Q4_K_M"]},
        ],
        "source_sha256": {str(path): sha256(path) for path in [run / "manifest.json", run / "summary.json", *adapter_files]},
        "exporter_sha256": sha256(Path(__file__)), "training_packages": manifest.get("packages", {}),
        "limitations": ["Export is not a quantized-model quality evaluation.",
                        "CPU merging and intermediates require substantial RAM and disk; provision at least 64 GB RAM for this workflow.",
                        "No importance matrix is used; evaluate Q4_K_M on the same held-out tasks after export."],
        "references": ["https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md",
                       "https://huggingface.co/docs/peft/package_reference/peft_model"],
    }


def merge_adapter(plan: dict) -> None:
    """Heavy imports and pinned Hugging Face downloads occur only during apply."""
    torch = importlib.import_module("torch")
    transformers = importlib.import_module("transformers")
    peft = importlib.import_module("peft")
    dtype = torch.bfloat16 if plan["intermediate_type"] == "bf16" else torch.float16
    model, diagnostics = transformers.AutoModelForCausalLM.from_pretrained(
        plan["base_model"], revision=plan["base_revision"], trust_remote_code=False,
        use_safetensors=True, dtype=dtype, device_map={"": "cpu"},
        low_cpu_mem_usage=True, output_loading_info=True,
    )
    if model.config.model_type != "qwen3" or any(diagnostics.get(key) for key in
                                               ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")):
        raise ValueError("Pinned Qwen3 base did not load completely and exactly")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        plan["adapter"], local_files_only=True, trust_remote_code=False,
    )
    model = peft.PeftModel.from_pretrained(model, plan["adapter"], is_trainable=False, local_files_only=True)
    merged = model.merge_and_unload(safe_merge=True)
    merged.config.use_cache = True
    merged.save_pretrained(plan["artifacts"]["merged_hf"], safe_serialization=True, max_shard_size="4GB")
    tokenizer.save_pretrained(plan["artifacts"]["merged_hf"])


def verify_gguf(path: Path, checkout: Path, expected_type: int) -> dict:
    sys.path.insert(0, str(checkout / "gguf-py"))
    try:
        gguf = importlib.import_module("gguf")
        module_file = getattr(gguf, "__file__", None)
        if not module_file or not Path(module_file).resolve().is_relative_to(checkout):
            raise ValueError("GGUF reader must come from the pinned llama.cpp checkout")
        reader = gguf.GGUFReader(path)
        file_type = reader.get_field("general.file_type")
        if file_type is None or int(file_type.contents()) != expected_type or not reader.tensors:
            raise ValueError("GGUF has incorrect file type or no tensors")
        if any(tensor.n_bytes <= 0 or tensor.data_offset + tensor.n_bytes > path.stat().st_size
               for tensor in reader.tensors):
            raise ValueError("GGUF tensor data is empty or truncated")
        if expected_type == 15 and not any(tensor.tensor_type.name == "Q4_K" for tensor in reader.tensors):
            raise ValueError("Q4_K_M export contains no Q4_K tensors")
        return {"file_type": expected_type, "tensor_count": len(reader.tensors),
                "tensor_types": dict(Counter(str(tensor.tensor_type.name) for tensor in reader.tensors))}
    finally:
        sys.path.pop(0)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def apply_plan(plan: dict) -> dict:
    # Recheck all planned input bytes immediately before the first mutation.
    for name, expected in plan["source_sha256"].items():
        if sha256(Path(name)) != expected:
            raise ValueError(f"Training artifact changed after export planning: {name}")
    tools = plan["toolchain"]
    checkout = Path(tools["checkout"])
    if validate_toolchain(checkout, tools["revision"]) != tools:
        raise ValueError("llama.cpp toolchain changed after planning")
    output = Path(plan["output"])
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "manifest.json", {**plan, "status": "running", "execution_packages": {
        distribution.metadata["Name"]: distribution.version for distribution in importlib.metadata.distributions()}})
    summary: dict[str, Any] = {"status": "running", "model_loaded": False, "quantized_artifact_verified": False}
    try:
        merge_adapter(plan)
        summary["model_loaded"] = True
        for stage in plan["commands"][1:]:
            destination = Path(plan["artifacts"]["intermediate_gguf" if stage["stage"] == "convert" else "quantized_gguf"])
            if destination.exists():
                raise FileExistsError(f"Refusing to overwrite export artifact: {destination}")
            with (output / f'{stage["stage"]}.log').open("w", encoding="utf-8") as log:
                subprocess.run(stage["argv"], cwd=checkout, check=True, stdout=log, stderr=subprocess.STDOUT)
            if not destination.is_file() or destination.stat().st_size == 0:
                raise ValueError(f"{stage['stage']} produced no output")
            file_type = (32 if plan["intermediate_type"] == "bf16" else 1) if stage["stage"] == "convert" else 15
            summary[f'{stage["stage"]}_metadata'] = verify_gguf(destination, checkout, file_type)
        quantized = Path(plan["artifacts"]["quantized_gguf"])
        summary.update(status="complete", quantized_artifact_verified=True, quantization="Q4_K_M",
                       quantized_path=str(quantized), quantized_sha256=sha256(quantized),
                       quantized_bytes=quantized.stat().st_size,
                       files_sha256={str(path.relative_to(output)): sha256(path)
                                     for path in sorted(output.rglob("*")) if path.is_file()},
                       quality_evaluation="not_run")
    except Exception as error:
        summary.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        write_json(output / "summary.json", summary)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--llama-cpp", required=True, type=Path)
    parser.add_argument("--llama-cpp-revision", required=True)
    parser.add_argument("--outtype", choices=("bf16", "f16"), default="bf16")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    plan = build_plan(args.run, args.output, args.llama_cpp, args.llama_cpp_revision, args.outtype)
    result = apply_plan(plan) if args.apply else plan
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
