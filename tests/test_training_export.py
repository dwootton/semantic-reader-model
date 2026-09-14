import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from training import export


class TrainingExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.run = self.root / "finished-run"
        self.output = self.root / "export"
        self.checkout = self.root / "llama.cpp"
        self.revision = "a" * 40
        self.tool_revision = "b" * 40
        self.write(self.run / "manifest.json", {"arguments": {"model": export.MODEL, "revision": self.revision},
                                                "model_revision": self.revision, "packages": {"peft": "test"}})
        self.write(self.run / "summary.json", {"status": "complete", "adapter_saved": True, "optimizer_steps": 40})
        self.adapter_config = {"base_model_name_or_path": export.MODEL, "revision": self.revision,
                               "peft_type": "LORA", "task_type": "CAUSAL_LM"}
        self.write(self.run / "adapter/adapter_config.json", self.adapter_config)
        self.write(self.run / "adapter/tokenizer_config.json", {})
        self.write(self.run / "adapter/tokenizer.json", {})
        (self.run / "adapter/adapter_model.safetensors").write_bytes(b"fixture adapter, not real weights")
        self.write(self.checkout / "gguf-py/gguf/__init__.py", {})
        (self.checkout / "convert_hf_to_gguf.py").write_text("# fixture converter\n")
        binary = self.checkout / "build/bin/llama-quantize"
        binary.parent.mkdir(parents=True)
        binary.write_text("# fixture binary\n")
        binary.chmod(0o700)
        self.git = mock.patch.object(export, "git", side_effect=self.git_result)
        self.git.start()
        self.addCleanup(self.git.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def git_result(self, checkout, *args):
        if args == ("rev-parse", "--show-toplevel"):
            return str(checkout)
        if args == ("rev-parse", "HEAD"):
            return self.tool_revision
        return ""

    def plan(self):
        return export.build_plan(self.run, self.output, self.checkout, self.tool_revision)

    def test_plan_has_pinned_metadata_correct_converter_and_quantize_arguments(self):
        with mock.patch.object(export, "merge_adapter", side_effect=AssertionError("weights loaded")):
            plan = self.plan()
        self.assertEqual(plan["status"], "planned")
        self.assertFalse(plan["model_loaded"])
        self.assertFalse(self.output.exists())
        self.assertEqual(plan["base_model"], export.MODEL)
        self.assertEqual(plan["base_revision"], self.revision)
        convert = plan["commands"][1]["argv"]
        self.assertEqual(Path(convert[1]).name, "convert_hf_to_gguf.py")
        self.assertEqual(convert[-2:], ["--outtype", "bf16"])
        self.assertEqual(plan["commands"][2]["argv"][-1], "Q4_K_M")
        self.assertNotIn("--remote", convert)
        self.assertIn(str(self.run / "adapter/adapter_config.json"), plan["source_sha256"])
        self.assertEqual(len(plan["toolchain"]["quantizer_sha256"]), 64)

    def test_default_cli_prints_plan_without_exporting(self):
        with mock.patch.object(export, "apply_plan", side_effect=AssertionError("apply called")):
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(export.main(["--run", str(self.run), "--output", str(self.output),
                                              "--llama-cpp", str(self.checkout), "--llama-cpp-revision", self.tool_revision]), 0)
        self.assertEqual(json.loads(stream.getvalue())["status"], "planned")
        self.assertFalse(self.output.exists())

    def test_failed_or_preflight_run_cannot_export(self):
        for status in ("failed", "preflight_complete", "running"):
            with self.subTest(status=status):
                self.write(self.run / "summary.json", {"status": status, "adapter_saved": True, "optimizer_steps": 40})
                with self.assertRaisesRegex(ValueError, "successful training summary"):
                    self.plan()

    def test_adapter_model_and_revision_must_match_training(self):
        for field, value in (("base_model_name_or_path", "Qwen/Other"), ("revision", "c" * 40), ("revision", "main")):
            with self.subTest(field=field, value=value):
                self.write(self.run / "adapter/adapter_config.json", {**self.adapter_config, field: value})
                with self.assertRaises(ValueError):
                    self.plan()

    def test_mutable_or_wrong_tool_revision_is_rejected(self):
        for revision in ("main", "c" * 40):
            with self.subTest(revision=revision):
                with self.assertRaises(ValueError):
                    export.build_plan(self.run, self.output, self.checkout, revision)

    def test_dirty_toolchain_is_rejected(self):
        def dirty(checkout, *arguments):
            return " M convert_hf_to_gguf.py" if arguments[0] == "status" else self.git_result(checkout, *arguments)
        with mock.patch.object(export, "git", side_effect=dirty):
            with self.assertRaisesRegex(ValueError, "modified or untracked"):
                self.plan()

    def test_output_collision_preserves_existing_artifacts(self):
        self.output.mkdir()
        sentinel = self.output / "old.gguf"
        sentinel.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            self.plan()
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_changed_adapter_after_planning_fails_before_mutation(self):
        plan = self.plan()
        (self.run / "adapter/adapter_model.safetensors").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            export.apply_plan(plan)
        self.assertFalse(self.output.exists())

    def test_failed_converter_never_claims_quantized_artifact(self):
        plan = self.plan()
        with mock.patch.object(export, "merge_adapter"), mock.patch.object(export.subprocess, "run"):
            with self.assertRaisesRegex(ValueError, "produced no output"):
                export.apply_plan(plan)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["status"], "failed")
        self.assertFalse(summary["quantized_artifact_verified"])
        self.assertNotIn("quantized_sha256", summary)

    def test_invalid_gguf_reader_type_is_rejected(self):
        gguf = mock.Mock()
        gguf.__file__ = str(self.checkout / "gguf-py/gguf/__init__.py")
        reader = gguf.GGUFReader.return_value
        reader.get_field.return_value.contents.return_value = 1
        reader.tensors = [object()]
        with mock.patch.object(export.importlib, "import_module", return_value=gguf):
            with self.assertRaisesRegex(ValueError, "incorrect file type"):
                export.verify_gguf(self.output / "fake.gguf", self.checkout, 15)

    def test_merge_loads_exact_base_on_cpu_and_uses_safe_merge(self):
        plan = self.plan()
        torch, transformers, peft = mock.Mock(), mock.Mock(), mock.Mock()
        model = mock.Mock()
        model.config.model_type = "qwen3"
        transformers.AutoModelForCausalLM.from_pretrained.return_value = (model, {})
        modules = {"torch": torch, "transformers": transformers, "peft": peft}
        with mock.patch.object(export.importlib, "import_module", side_effect=modules.__getitem__):
            export.merge_adapter(plan)
        args, kwargs = transformers.AutoModelForCausalLM.from_pretrained.call_args
        self.assertEqual(args, (export.MODEL,))
        self.assertEqual(kwargs["revision"], self.revision)
        self.assertEqual(kwargs["device_map"], {"": "cpu"})
        self.assertFalse(kwargs["trust_remote_code"])
        self.assertTrue(kwargs["use_safetensors"])
        peft.PeftModel.from_pretrained.return_value.merge_and_unload.assert_called_once_with(safe_merge=True)
        self.assertTrue(transformers.AutoTokenizer.from_pretrained.call_args.kwargs["local_files_only"])


if __name__ == "__main__":
    unittest.main()
