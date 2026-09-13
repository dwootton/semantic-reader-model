import json
import unittest

from inspector.comparison import ComparisonError
from inspector.lean_comparison import _decode, _encode, run_lean_comparison
from inspector.test_compact_comparison import fixture


class Client:
    def generate(self, model, system, prompt, **kwargs):
        from html.parser import HTMLParser
        owned = []

        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if "data-r" in attrs and not any(name.startswith("data-organizer-context") for name in attrs):
                    owned.append(int(attrs["data-r"]))

        task = json.loads(prompt)
        Parser().feed(task["html"])
        titles = kwargs["response_schema"]["properties"]["groups"]["items"]["properties"]["t"]["enum"]
        return {"groups": [{"t": titles[0], "p": 0, "s": [[n, n] for n in owned]}], "e": []}, {
            "usage": {"promptTokenCount": 12, "candidatesTokenCount": 8}}


class LeanTests(unittest.TestCase):
    def test_encoding_preserves_evidence_bytes(self):
        rendered = '<main data-r="root" data-deferred="yes">A &amp; B<a data-r="link" data-target-ref="root" href="#x">Jump</a></main>'
        encoded, aliases, labels = _encode(rendered, "data-r", ["root", "link"])
        self.assertEqual(encoded, rendered.replace('data-r="root"', 'data-r="1"')
                         .replace('data-r="link"', 'data-r="2"').replace('data-target-ref="root"', 'data-target-ref="1"'))
        self.assertEqual(aliases, {1: "root", 2: "link"})
        self.assertEqual(labels[2], "Jump")

    def decode(self, groups, owned=("a", "b", "c")):
        return _decode({"groups": groups, "e": []}, {1: "a", 2: "b", 3: "c"},
                       {1: "Title", 3: "Other"}, owned, 4, "test")

    def test_disjoint_ranges_and_title_grounding(self):
        output, titles = self.decode([{"t": 1, "p": 0, "s": [[1, 1], [3, 3]]}])
        self.assertEqual(output["groups"][0]["source_ids"], ["a", "c"])
        self.assertEqual(output["groups"][0]["label"], "Title")
        self.assertEqual(titles, ["a"])

    def test_readonly_crossing_rejected(self):
        with self.assertRaisesRegex(ComparisonError, "read-only"):
            self.decode([{"t": 1, "p": 0, "s": [[1, 3]]}], ("a", "c"))

    def test_invalid_outputs_fail_without_repair(self):
        bad = [
            [{"t": 2, "p": 0, "s": [[1, 1]]}],
            [{"t": 1, "p": 2, "s": [[1, 1]]}],
            [{"t": 1, "p": 1, "s": [[1, 1]]}],
            [{"t": 1, "p": 0, "s": [[1, 2], [2, 3]]}],
            [{"t": 1, "p": 0, "s": [[1, 4]]}],
            [{"t": True, "p": 0, "s": [[1, 1]]}],
        ]
        for groups in bad:
            with self.subTest(groups=groups), self.assertRaises(ComparisonError):
                self.decode(groups)

    def test_empty_label_has_no_fabricated_title(self):
        _, aliases, labels = _encode('<div data-r="a"></div>', "data-r", ["a"])
        self.assertEqual(labels, {})
        output, titles = _decode({"groups": [], "e": []}, aliases, labels, ["a"], 4, "test")
        self.assertEqual(output["groups"], [])
        self.assertEqual(titles, [])

    def test_whole_and_regions_keep_source_ids_and_coverage(self):
        for strategy in ("whole", "regions"):
            result = run_lean_comparison(fixture(20), strategy, Client(), "test")
            self.assertEqual(result["input_mode"], "compact-lean")
            self.assertEqual(result["metrics"]["annotation_coverage"], 1)
            self.assertEqual(result["metrics"]["composition_calls"], 0)
            for call in result["calls"]:
                self.assertIn("s", call["output"]["groups"][0])
                self.assertIn("source_ids", call["normalized_output"]["groups"][0])
                self.assertNotIn("SECRET", call["prompt"])
            groups = [n for n in result["variant"]["nodes"] if n["origin"] == "model-" + strategy]
            self.assertTrue(all(n["labelSourceRefs"][0].startswith("d0:") for n in groups))


if __name__ == "__main__":
    unittest.main()
