"""Real HTML5 parser regression and damage tests for local recovery patches."""
import json
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch(headless=True)
        cls.context = cls.browser.new_context(service_workers='block')
        cls.context.route('**/*', lambda route: route.abort())
        cls.page = cls.context.new_page()
        cls.page.add_script_tag(path=str(HERE / 'recovery.js'))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def run_case(self, source, profile='conservative'):
        return self.page.evaluate('(x) => runRecoveryExperiment(x.source, x.profile)',
                                  {'source': source, 'profile': profile})

    def test_semantics_and_excluded_payload(self):
        source = '''<!doctype html><!--outside--><html lang="en"><head><title>Title</title></head>
        <body><p class="a" onclick="run()">a<!--split-->b<em>NOT</em>c</p>
        <table><caption>Prices</caption><tr><th id="h">Price</th><td headers="h">$20</td></tr></table>
        <form><label for="q">Query</label><input id="q" aria-describedby="help" value="x" disabled>
        <span id="help" hidden>Help</span><textarea> a\n b</textarea></form>
        <template><p>Template</p><script>x()</script></template><style>a{color:red}</style>
        <svg viewBox="0 0 1 1"><title>Icon</title><path d="M0 0"/></svg><math><mi>x</mi></math>
        <details><summary>More</summary>Closed text</details><pre>  x\n y</pre></body></html>'''
        for profile in ('conservative', 'wrappers'):
            with self.subTest(profile=profile):
                result = self.run_case(source, profile)
                self.assertTrue(result['report']['passed'], result['report'])
                self.assertEqual(result['report']['excludedElements'], 2)
                self.assertEqual(result['report']['sourceElements'], result['report']['recoveredElements'])

    def test_wrappers_reconstructed_and_markers_do_not_collide(self):
        source = '<div data-sr-node="original"><div><div><div>hello</div></div></div></div>'
        result = self.run_case(source, 'wrappers')
        self.assertTrue(result['report']['passed'])
        self.assertEqual(result['report']['collapsedElements'], 2)
        self.assertEqual(result['patch']['marker'], 'data-sr-node-x')
        self.assertNotIn('hello', str(result['patch']))  # retained text is not backed up

    def test_malformed_input_and_empty_document(self):
        for source in ('', '<table><td>A</table><p>one<p>two', '<div>a<!--x-->b</div>'):
            with self.subTest(source=source):
                self.assertTrue(self.run_case(source)['report']['passed'])

    def test_deep_patch_transfers_as_json(self):
        source = '<div>' * 300 + 'deep' + '</div>' * 300
        encoded = self.page.evaluate(
            's => JSON.stringify(runRecoveryExperiment(s, "wrappers"))', source)
        result = json.loads(encoded)
        self.assertTrue(result['report']['passed'])
        self.assertGreater(result['report']['collapsedElements'], 200)

    def test_metadata_join_is_explicit(self):
        result = self.page.evaluate('''() => runRecoveryExperiment('<p id="x">Text</p>', 'conservative', [
            {id:'e1',css_path:'p',tag:'p'}, {id:'e2',css_path:'button',tag:'button'}])''')
        self.assertEqual(result['report']['metadataJoin'], {'total': 2, 'matched': 1, 'failed': 1})
        self.assertEqual(result['sourceMatches'][1]['disposition'], 'unknown')

    def test_unexpected_content_is_rejected(self):
        result = self.page.evaluate('''() => {
          const r = runRecoveryExperiment('<p>Text</p>');
          return [r.html.replace('Text', 'Text extra'),
            r.html.replace('<p ', '<p data-new=\"extra\" '),
            r.html.replace('</body>', '<b data-sr-node=\"extra\">x</b></body>')].map(html => {
              try { restoreCompressed(html, r.patch); return false; } catch { return true; }
            });
        }''')
        self.assertEqual(result, [True, True, True])

    def test_damage_is_not_recovered_from_a_hidden_text_copy(self):
        result = self.page.evaluate('''() => {
          const r = runRecoveryExperiment('<p>Keep NOT</p>');
          const full = restoreCompressed(r.html, r.patch);
          const damaged = restoreCompressed(r.html.replace('Keep NOT','Keep YES'), r.patch);
          let missingRejected = false;
          try { restoreCompressed(r.html.replace(/data-sr-node="n3"/, ''), r.patch); }
          catch { missingRejected = true; }
          return {different: full !== damaged, missingRejected};
        }''')
        self.assertTrue(result['different'])
        self.assertTrue(result['missingRejected'])


if __name__ == '__main__':
    unittest.main()
