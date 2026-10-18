"""Drift scoring and capture parsing on synthetic data; no browser or network."""

import json
from pathlib import Path
import tempfile
import unittest

from render_pages import blocked_like_capture, captured_anchors, drift, same_site

HTML = """<!doctype html><html data-sr-capture-id="n1"><body data-sr-capture-id="n2">
<h1 data-sr-capture-id="n3">Docker</h1><p data-sr-capture-id="n4">Install <a data-sr-capture-id="n5">here</a> today</p>
<a data-sr-capture-id="n6">More</a><a data-sr-capture-id="n7">More</a><img alt="x" data-sr-capture-id="n8">
<p data-sr-capture-id="n9">Below the fold</p></body></html>"""
GEOMETRY = {"elements_and_text": [
    {"dom_id": "n3", "bounds": [10, 20, 100, 30]}, {"dom_id": "n4", "bounds": [10, 60, 300, 20]},
    {"dom_id": "n5", "bounds": [60, 60, 30, 20]}, {"dom_id": "n6", "bounds": [10, 90, 40, 20]},
    {"dom_id": "n7", "bounds": [60, 90, 40, 20]}, {"dom_id": "n9", "bounds": [10, 1500, 200, 20]}]}


class RenderPagesTest(unittest.TestCase):
    def anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "document.html").write_text(HTML)
            (state / "geometry.json").write_text(json.dumps(GEOMETRY))
            return captured_anchors(state, {"width": 1365, "height": 900})

    def test_anchors_are_unique_own_text_in_the_first_screen(self):
        anchors = self.anchors()
        self.assertEqual(sorted(anchors), [("a", "here"), ("h1", "Docker"), ("p", "Install today")],
                         "duplicate 'More' links and below-the-fold text are not anchors")

    def test_drift_allows_one_common_offset(self):
        anchors = self.anchors()
        live = [{"tag": "h1", "text": "Docker", "box": [10, 80, 100, 30]},
                {"tag": "p", "text": "Install today", "box": [10, 120, 300, 20]},
                {"tag": "a", "text": "here", "box": [400, 120, 30, 20]}]
        result = drift(anchors, live)
        self.assertEqual((result["found"], result["aligned"], result["offset"]), (3, 2, 60))
        self.assertAlmostEqual(result["score"], 2 / 3, places=3)
        self.assertEqual(result["misaligned"], [["a", "here"]])

    def test_missing_live_text_lowers_the_score(self):
        result = drift(self.anchors(), [{"tag": "h1", "text": "Docker", "box": [10, 20, 100, 30]}])
        self.assertEqual((result["found"], result["aligned"], result["score"]), (1, 1, 0.333))

    def test_same_site_requests_only(self):
        site = "https://www.example.org/docs/"
        self.assertTrue(same_site("https://www.example.org/app.css", site))
        self.assertTrue(same_site("https://cdn.example.org/font.woff2", site))
        self.assertTrue(same_site("data:image/png;base64,xx", site))
        self.assertFalse(same_site("https://ads.tracker.com/x.js", site))
        self.assertFalse(same_site("https://example.org.evil.com/x", site))

    def test_blocks_what_the_capture_blocked(self):
        site = "https://www.example.org/"
        self.assertTrue(blocked_like_capture("image", "https://www.example.org/a.png", site, True))
        self.assertTrue(blocked_like_capture("font", "https://www.example.org/f", site, True))
        self.assertTrue(blocked_like_capture("stylesheet", "https://www.example.org/x.woff2", site, True))
        self.assertTrue(blocked_like_capture("document", "https://www.example.org/embed", site, False), "frames")
        self.assertFalse(blocked_like_capture("stylesheet", "https://www.example.org/site.css", site, True))
        self.assertFalse(blocked_like_capture("script", "https://static.example.org/app.js", site, True))


if __name__ == "__main__":
    unittest.main()
