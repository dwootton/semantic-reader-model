"""CSS and media inlining for page copies; no browser or network."""
import unittest

from snapshot_pages import inline_css, inline_page, pin_vh

PNG = ("image/png", b"\x89PNG")
ASSETS = {"https://ex.org/img/a.png": PNG, "https://ex.org/f.woff2": ("font/woff2", b"wOF2"),
          "https://ex.org/css/base.css": ("text/css", b".b { background: url(../img/a.png) }")}


class SnapshotPagesTest(unittest.TestCase):
    def test_viewport_heights_are_pinned_to_the_capture(self):
        self.assertEqual(pin_vh("min-height:100vh;height:50dvh;top:-2.5vh"), "min-height:900px;height:450px;top:-22.5px")

    def test_urls_resolve_against_the_stylesheet_and_become_data_uris(self):
        css = inline_css('@import "base.css"; @font-face { src: url("../f.woff2") } .x { background: url(missing.png) }',
                         "https://ex.org/css/site.css", ASSETS, [1 << 20])
        self.assertIn("data:image/png;base64,", css, "imported sheet's url() resolves against the imported sheet")
        self.assertIn("data:font/woff2;base64,", css)
        self.assertIn('url("data:,")', css, "anything not loaded stays offline")
        self.assertNotIn("@import", css)

    def test_page_styles_attributes_and_images(self):
        page = ('<style data-sr-href="https://ex.org/css/base.css"></style><style>.h{height:100vh}</style>'
                '<div style="background:url(&quot;img/a.png&quot;)"></div><img src="https://ex.org/img/a.png">'
                '<img src="https://ex.org/gone.png"><a href="https://ex.org/next">next</a>')
        out = inline_page(page, "https://ex.org/", ASSETS)
        self.assertEqual(out.count("data:image/png;base64,"), 3)
        self.assertIn(".h{height:900px}", out)
        self.assertIn('src="data:,"', out)
        self.assertIn('href="https://ex.org/next"', out, "links are kept")


if __name__ == "__main__":
    unittest.main()
