"""Opt-in offline browser tests; no source website navigation or model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from ui_ir.bridge import invoke

ROOT = Path(__file__).parent


@unittest.skipUnless(os.environ.get('SEMANTIC_BROWSER_INTEGRATION') == '1', 'opt-in browser environment required')
class DOMBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.runtime = sync_playwright().start()
        opts = {'headless': True}
        if os.environ.get('SEMANTIC_IR_CHROMIUM_EXECUTABLE'):
            opts['executable_path'] = os.environ['SEMANTIC_IR_CHROMIUM_EXECUTABLE']
        cls.browser = cls.runtime.chromium.launch(**opts)
        cls.context = cls.browser.new_context(java_script_enabled=False, service_workers='block')
        cls.requests = []

        def block(route):
            cls.requests.append(route.request.url)
            route.abort()

        cls.context.route('**/*', block)
        cls.page = cls.context.new_page()
        script = (ROOT/'dom/parse.mjs').read_text().replace('export function parseDOM', 'function parseDOM')
        cls.page.evaluate('(() => {\n' + script + '\nglobalThis.__parseIR = parseDOM;\n})()')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def parsed(self, source, document_id='d0'):
        return self.page.evaluate('x => __parseIR(x.source, {documentId:x.id, networkIsolated:true})', {'source': source, 'id': document_id})

    def run_ir(self, source, profile='structure', **options):
        return invoke({'operation': 'pipeline', 'input': {'snapshotId': 'browser-fixture', 'documents': [self.parsed(source)]}, 'request': {'profile': profile, 'maxBytes': 200000, **options}})

    def test_full_document_parsing_keeps_text_order_title_and_browser_table_repair(self):
        parsed = self.parsed('<!doctype html><html lang="en"><head><title>Title</title></head><body><p>Pay <a href="/i">invoice</a> now.</p><table><tr><td>A<td>B</table></body></html>')
        tags = [r.get('tag') for r in parsed['records']]
        self.assertIn('html', tags)
        self.assertIn('head', tags)
        self.assertIn('tbody', tags)
        data = invoke({'operation': 'adapt', 'input': {'snapshotId': 's', 'documents': [parsed]}})
        texts = [n['text'] for n in data['observation']['nodes'].values() if 'text' in n]
        # Canonical JSON dictionary order is not text order; inspect child order.
        paragraph = next(n for n in data['observation']['nodes'].values() if n['role'] == 'paragraph')
        nodes = data['observation']['nodes']
        self.assertEqual([nodes[c]['role'] for c in paragraph['children']], ['text', 'link', 'text'])
        self.assertIn('Title', texts)

    def test_source_scripts_and_resources_never_execute(self):
        source = '<script>globalThis.__irPwned=1;fetch("https://example.invalid/leak")</script><img src="https://example.invalid/a.png" onerror="globalThis.__irPwned=2"><iframe src="https://example.invalid/frame"></iframe><p>safe</p>'
        result = self.run_ir(source)
        self.assertIsNone(self.page.evaluate('globalThis.__irPwned ?? null'))
        self.assertEqual(self.page.url, 'about:blank')
        self.assertNotIn('__irPwned', result['packet']['text'])
        self.assertNotIn('example.invalid', result['packet']['text'])

    def test_shipping_preserves_control_help_error_header_and_svg_text(self):
        source = (ROOT/'fixtures/shipping.html').read_text()
        result = self.run_ir(source, 'budget', maxBytes=500)
        self.assertFalse(result['result']['report']['fits'])
        model = result['packet']['text']
        for text in ['Postal code', 'Do not submit another payment.', 'Price', 'Home', 'Two stops', 'Continue']:
            self.assertIn(text, model)
        self.assertNotIn('M0 0L10 10', model)
        self.assertEqual(invoke({'operation': 'validate', 'observation': result['bundle']['observation']})['valid'], True)

    def test_unchecked_fields_and_short_distinct_items_survive(self):
        source = '<form><label>Email<input type="email" required></label><label><input type="checkbox">Subscribe</label><button>Submit</button></form>'
        source += '<ul>' + ''.join(f'<li>{name}</li>' for name in ['Flour', 'Salt', 'Sugar', 'Butter', 'Eggs', 'Bananas', 'Baking soda']) + '</ul>'
        result = self.run_ir(source, 'budget', maxBytes=1000)
        for text in ['Email', 'Subscribe', 'Submit', 'Flour', 'Salt', 'Sugar', 'Butter', 'Eggs', 'Bananas', 'Baking soda']:
            self.assertIn(text, result['packet']['text'])

    def test_default_selected_option_is_not_current_but_survives_preview(self):
        source = '<select><optgroup label="Countries">' + ''.join(f'<option {"selected" if i == 12 else ""}>Country {i}</option>' for i in range(25)) + '</optgroup></select>'
        result = self.run_ir(source, 'excerpt')
        self.assertIn('Countries', result['packet']['text'])
        self.assertIn('Country 12', result['packet']['text'])
        self.assertNotIn('"selected":true', result['packet']['text'])
        self.assertIn('choice-preview', result['packet']['text'])

    def test_two_documents_with_identical_html_ids_remain_disjoint(self):
        docs = [self.parsed('<label for="x">Label</label><input id="x">', key) for key in ['a', 'b']]
        result = invoke({'operation': 'pipeline', 'input': {'snapshotId': 's', 'documents': docs}})
        self.assertEqual(len(result['bundle']['observation']['roots']), 2)
        for r in result['bundle']['observation']['relations']:
            for t in r['targets']:
                if 'node' in t:
                    self.assertEqual(r['from'].split(':')[0], t['node'].split(':')[0])

    def test_bridge_and_json_schemas_on_real_parsed_output(self):
        from jsonschema import Draft202012Validator
        # A separate caller process exercises the bridge without nesting Playwright's sync loop.
        script = 'import json,sys; from ui_ir.bridge import pipeline; print(json.dumps(pipeline(json.load(sys.stdin), snapshot_id="bridge-test")))'
        completed = subprocess.run([sys.executable, '-c', script], input=json.dumps([{'id': 'd0', 'html': '<h1>Example</h1><p>Read <a href="/more">more</a>.</p>'}]), text=True, capture_output=True, check=True, timeout=60)
        result = json.loads(completed.stdout)
        for name, value in [('observation', result['bundle']['observation']), ('view', result['result']['view'])]:
            schema = json.loads((ROOT/f'schema/{name}-v0.schema.json').read_text())
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(value)

    def test_protected_code_and_long_alert_not_prefix_truncated(self):
        alert = 'Context. ' * 100 + 'Do not submit another payment.'
        code = '  if (ready) {\n    run();\n  }\n' * 100
        result = self.run_ir(f'<div role="alert">{alert}</div><pre>{code}</pre>', 'budget', maxBytes=2000)
        fields = [n.get('text', {}).get('value') for n in result['result']['view']['nodes'].values()]
        self.assertIn(alert, fields)
        self.assertIn(code, fields)

    def test_legacy_partial_text_and_destination_reach_model_without_raw_recovery(self):
        source = '<p data-r="a" data-excerpt="true">Preview only…</p><a data-r="b" data-destination-id="u0" data-destination="example.test/pay" data-target-ref="a">Pay</a>'
        parsed = self.page.evaluate('s => __parseIR(s,{documentId:"d0",profile:"legacy-compact-dom",referenceAttribute:"data-r",networkIsolated:true})', source)
        result = invoke({'operation': 'pipeline', 'input': {'snapshotId': 'legacy', 'documents': [parsed]}})
        model = json.loads(result['packet']['text'])
        links = [n for n in model['nodes'] if n['role'] == 'link']
        self.assertEqual(len(links), 1)
        self.assertIn('destination', links[0])
        self.assertFalse(any(a['kind']=='invoke' for a in links[0].get('actions', [])))
        self.assertTrue(any(g['field']=='text' and g['expansion']=='unavailable' for g in model['gaps']))
        self.assertTrue(any(n.get('text', {}).get('kind')=='extract' for n in model['nodes']))
        self.assertTrue(any(r['kind']=='fragmentTarget' for r in model['relations']))

    @unittest.skipUnless(os.environ.get('SEMANTIC_LOCAL_CORPUS_TESTS') == '1', 'optional local audited corpus')
    def test_real_audited_input_reaches_fake_model_as_ir_json(self):
        script = '''
import json
from inspector.ir_input import load_ir
from inspector.ir_comparison import run_ir_comparison
class Fake:
    calls = 0
    def generate(self, model, system, prompt, **kwargs):
        self.calls += 1
        task = json.loads(prompt)
        assert 'ir' in task and 'html' not in task
        aliases = kwargs['response_schema']['properties']['groups']['items']['properties']['source_ids']['items']['enum']
        return {'groups':[{'id':'g1','label':'Observed content','parent':None,'source_ids':aliases[:1]}], 'needs_expansion':[]}, {}
prepared = load_ir('gov-uk')
client = Fake()
output = run_ir_comparison(prepared, 'whole', client, 'fake-no-model')
print(json.dumps({'calls':client.calls,'mode':output['input_mode'],'assigned':output['metrics']['annotated_source_nodes']}))
'''
        completed = subprocess.run([sys.executable, '-c', script], text=True, capture_output=True, check=True, timeout=120)
        self.assertEqual(json.loads(completed.stdout), {'calls': 1, 'mode': 'ir-v0', 'assigned': 1})


if __name__ == '__main__':
    unittest.main()
