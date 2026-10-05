"""Queue order on a synthetic corpus; no captured data."""

import json
from pathlib import Path
import tempfile
import unittest

from queue_order import CAPTURE_FILES, build, round_robin


def pages(spec):
    """spec: {category: {site: page_count}}"""
    return [{"page": f"{site}/p{i}", "site": site, "category": category}
            for category, sites in spec.items() for site, n in sites.items() for i in range(n)]


class RoundRobinTest(unittest.TestCase):
    SPEC = {"A": {"a1": 3, "a2": 1}, "B": {"b1": 2}, "C": {"c1": 1, "c2": 1, "c3": 1}}

    def test_every_site_before_any_second_page(self):
        order = round_robin(pages(self.SPEC), seed=1)
        sites = [p["site"] for p in order]
        self.assertEqual(len(order), 9)
        self.assertEqual(sorted(sites[:6]), ["a1", "a2", "b1", "c1", "c2", "c3"])
        self.assertEqual(sorted(sites[6:8]), ["a1", "b1"])
        self.assertEqual(sites[8], "a1")

    def test_categories_alternate_within_a_pass(self):
        first = [p["category"] for p in round_robin(pages(self.SPEC), seed=1)][:3]
        self.assertEqual(sorted(first), ["A", "B", "C"])

    def test_deterministic_for_a_seed(self):
        records = pages(self.SPEC)
        self.assertEqual(round_robin(records, seed=7), round_robin(list(reversed(records)), seed=7))

    def test_build_groups_and_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            captures = corpus / "public-research-v1/captures"
            for site, page, category, complete in [("s1", "p1", "X", True), ("s1", "p2", "X", True),
                                                   ("s2", "p3", "Y", True), ("s3", "p4", "Y", False)]:
                state = captures / site / page / "state-000"
                for name in CAPTURE_FILES if complete else CAPTURE_FILES[:1]:
                    (state / name).parent.mkdir(parents=True, exist_ok=True)
                    (state / name).write_text("{}")
                (state / "capture.json").write_text(json.dumps({"record": {"url": f"https://{page}", "category": category}}))
            (corpus / "pro-pages.json").write_text(json.dumps(["s1/p2"]))
            (corpus / "excluded.json").write_text(json.dumps({"pages": [{"page": "s2/p3", "error": "x"}]}))
            queue = build(corpus, seed=3)
            self.assertEqual([p["page"] for p in queue["groups"]["pro"]], ["s1/p2"])
            self.assertEqual([p["page"] for p in queue["groups"]["main"]], ["s1/p1"])
            self.assertEqual(queue["skipped"], {"no complete desktop capture": 1, "failed corpus check": 1})
            self.assertEqual(queue["excluded"], [{"page": "s2/p3", "error": "x"}])
            self.assertEqual(json.loads((corpus / "queue.json").read_text()), queue)


if __name__ == "__main__":
    unittest.main()
