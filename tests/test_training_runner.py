"""Offline tests for training admission and completion-only supervision."""

from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from training.train import (
    assert_disjoint, encode_record, generation_cap, generation_stop_reason, load_model,
    main, parse_args, prepare_records, read_records, select_evaluation,
)


class FakeTokenizer:
    chat_template = "fake chat template"
    pad_token_id = 0

    def apply_chat_template(self, messages, *, add_generation_prompt, **options):
        assert options == {"tokenize": True, "enable_thinking": False, "truncation": False, "return_dict": False}
        text = "".join(f"<{message['role']}>{message['content']}</>" for message in messages)
        if add_generation_prompt:
            text += "<assistant>"
        return list(text.encode())


def record(identifier="a", domain="train.example", split="train"):
    return {"id": identifier, "domain": domain, "split": split,
            "prompt": [{"role": "system", "content": "Do the task"},
                       {"role": "user", "content": "source content"}],
            "completion": [{"role": "assistant", "content": '{"answer":true}'}]}


class TrainingRunnerTests(unittest.TestCase):
    def test_masks_prompt_and_preserves_every_completion_token(self):
        encoded = encode_record(record(), FakeTokenizer())
        boundary = len(encoded["prompt_ids"])
        self.assertEqual(encoded["labels"][:boundary], [-100] * boundary)
        self.assertEqual(bytes(encoded["labels"][boundary:]), b'{"answer":true}</>')
        self.assertEqual(encoded["completion_tokens"], len(encoded["labels"]) - boundary)

    def test_rejects_chat_template_token_prefix_mismatch(self):
        class DifferentPrefix(FakeTokenizer):
            def apply_chat_template(self, messages, **options):
                tokens = super().apply_chat_template(messages, **options)
                return tokens + [999] if options["add_generation_prompt"] else tokens
        with self.assertRaisesRegex(ValueError, "exact token prefix"):
            encode_record(record(), DifferentPrefix())

    def test_extracts_input_ids_when_tokenizer_returns_batch_encoding_mapping(self):
        class MappingTokenizer(FakeTokenizer):
            def apply_chat_template(self, messages, **options):
                tokens = super().apply_chat_template(messages, **options)
                return {"input_ids": tokens, "attention_mask": [1] * len(tokens)}
        encoded = encode_record(record(), MappingTokenizer())
        self.assertEqual(encoded, encode_record(record(), FakeTokenizer()))
        self.assertTrue(all(type(token) is int for token in encoded["input_ids"]))

    def test_rejects_nested_or_noninteger_token_sequences(self):
        for result in [["input_ids", "attention_mask"], [[1, 2]], [True], {"attention_mask": [1]}]:
            tokenizer = types.SimpleNamespace(apply_chat_template=Mock(return_value=result))
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, "flat sequence of integer"):
                encode_record(record(), tokenizer)

    def test_overlength_excludes_whole_record_and_reports_length(self):
        row = record()
        original = deepcopy(row)
        count = len(encode_record(row, FakeTokenizer())["input_ids"])
        accepted, excluded = prepare_records([row], FakeTokenizer(), count - 1)
        self.assertEqual(accepted, [])
        self.assertEqual(excluded[0]["tokens"], count)
        self.assertEqual(excluded[0]["id"], row["id"])
        self.assertEqual(row, original)
        accepted, excluded = prepare_records([row], FakeTokenizer(), count)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(excluded, [])

    def test_rejects_id_and_normalized_domain_leakage(self):
        for dev in [record("a", "dev.example", "dev"), record("b", "TRAIN.EXAMPLE.", "dev")]:
            with self.subTest(dev=dev), self.assertRaisesRegex(ValueError, "overlap"):
                assert_disjoint([record()], [dev])
        assert_disjoint([record()], [record("b", "dev.example", "dev")])

    def test_read_rejects_empty_duplicate_wrong_split_and_nontext(self):
        malformed = record()
        malformed["completion"][0]["content"] = [{"type": "text", "text": "bad"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.jsonl"
            for rows in [[], [record(), record()], [record(split="test")], [malformed]]:
                with self.subTest(rows=rows):
                    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
                    with self.assertRaises(ValueError):
                        read_records(path, "train")
            path.write_text(json.dumps(record()) + "\n")
            self.assertEqual(read_records(path, "train"), [record()])

    def test_evaluation_selection_is_reproducible_and_order_independent(self):
        rows = [record(str(index)) for index in range(20)]
        selected = select_evaluation(rows, 5, 42)
        self.assertEqual(selected, select_evaluation(list(reversed(rows)), 5, 42))
        self.assertEqual(len(selected), 5)
        self.assertNotEqual(selected, select_evaluation(rows, 5, 43))

    def test_cli_requires_immutable_revision_and_positive_limits(self):
        base = ["--train", "train.jsonl", "--dev", "dev.jsonl", "--output", "out"]
        for extra in [["--revision", "main"], ["--revision", "a" * 40, "--max-steps", "0"],
                      ["--revision", "a" * 40, "--learning-rate", "nan"]]:
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args(base + extra)
        args = parse_args(base + ["--revision", "a" * 40])
        self.assertEqual(args.max_length, 8192)
        self.assertEqual(args.model, "Qwen/Qwen3-8B")
        self.assertEqual(args.generation_seconds, 600)

    def test_generation_budget_must_cover_full_reference(self):
        row = {"id": "a", "prompt_ids": list(range(100)), "completion_tokens": 2000}
        self.assertEqual(generation_cap(row, 2100, 8192), 2000)
        for max_length, max_new_tokens in [(2100, 1000), (1500, 8192)]:
            with self.assertRaisesRegex(ValueError, "cannot cover"):
                generation_cap(row, max_length, max_new_tokens)

    def test_generation_records_eos_token_time_and_unknown_stops(self):
        self.assertEqual(generation_stop_reason([1, 9], 9, 2, 700, 600), "eos")
        self.assertEqual(generation_stop_reason([1, 2], 9, 2, 700, 600), "token_limit")
        self.assertEqual(generation_stop_reason([1], 9, 2, 700, 600), "time_limit")
        self.assertEqual(generation_stop_reason([1], 9, 2, 1, 600), "other")

    def test_native_model_loading_selects_qwen3_and_qwen35_text_backbones(self):
        args = types.SimpleNamespace(model="Qwen/Qwen3-8B", revision="a" * 40, max_length=8192)
        torch = types.SimpleNamespace(bfloat16="bf16")
        for model_type in ("qwen3", "qwen3_5", "unsupported"):
            with self.subTest(model_type=model_type):
                config = types.SimpleNamespace(model_type=model_type, max_position_embeddings=32768)
                config_loader = types.SimpleNamespace(from_pretrained=Mock(return_value=config))
                causal_loader = types.SimpleNamespace(from_pretrained=Mock(return_value=("qwen3", {})))
                text_loader = types.SimpleNamespace(from_pretrained=Mock(return_value=("qwen35", {})))
                module = types.SimpleNamespace(AutoConfig=config_loader, AutoModelForCausalLM=causal_loader,
                                               Qwen3_5ForCausalLM=text_loader, Qwen3_5TextConfig=config_loader)
                with patch.dict("sys.modules", {"transformers": module}):
                    if model_type == "unsupported":
                        with self.assertRaisesRegex(ValueError, "native dense"):
                            load_model(args, torch)
                        continue
                    result = load_model(args, torch)
                selected = causal_loader if model_type == "qwen3" else text_loader
                self.assertEqual(result[0], "qwen3" if model_type == "qwen3" else "qwen35")
                self.assertEqual(selected.from_pretrained.call_args.kwargs["dtype"], "bf16")
                self.assertEqual(selected.from_pretrained.call_args.kwargs["revision"], "a" * 40)

    def test_preflight_runs_without_model_or_torch_and_writes_evidence(self):
        class AutoTokenizer:
            @staticmethod
            def from_pretrained(model, *, revision, trust_remote_code):
                self.assertEqual(revision, "a" * 40)
                self.assertFalse(trust_remote_code)
                return FakeTokenizer()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train, dev, output = root / "train.jsonl", root / "dev.jsonl", root / "output"
            train.write_text(json.dumps(record()) + "\n")
            dev.write_text(json.dumps(record("b", "dev.example", "dev")) + "\n")
            fake_transformers = types.SimpleNamespace(AutoTokenizer=AutoTokenizer)
            with patch.dict("sys.modules", {"transformers": fake_transformers}), contextlib.redirect_stdout(io.StringIO()):
                result = main(["--train", str(train), "--dev", str(dev), "--output", str(output),
                               "--revision", "a" * 40, "--preflight-only"])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads((output / "summary.json").read_text())["status"], "preflight_complete")
            self.assertEqual(json.loads((output / "preflight.json").read_text())["train_ids"], ["a"])
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(len(manifest["files_sha256"][str(train)]), 64)
            self.assertFalse((output / "adapter").exists())


if __name__ == "__main__":
    unittest.main()
