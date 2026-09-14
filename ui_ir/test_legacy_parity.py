"""Run the existing 26 DOM-compactor regression inputs through the new pipeline too.

The existing assertions still test the legacy compactor. Additional assertions
check the IR contract/preservation result for every same-source/profile invocation.
Different profile policies (notably protected code) intentionally need not emit
identical strings or element counts.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import unittest

from ui_ir.bridge import invoke

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('legacy_compactor_tests', ROOT/'experiments/dom-downsampling/test_compact.py')
LEGACY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEGACY)


@unittest.skipUnless(os.environ.get('SEMANTIC_BROWSER_INTEGRATION') == '1', 'opt-in offline browser environment required')
class LegacyInputParityTests(LEGACY.CompactTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        script = (ROOT/'ui_ir/dom/parse.mjs').read_text().replace('export function parseDOM', 'function parseDOM')
        cls.page.evaluate('(() => {\n' + script + '\nglobalThis.__parseIR = parseDOM;\n})()')
        cls.measurements = []

    def compact(self, source, profile='budget', ratio=.1):
        legacy = super().compact(source, profile, ratio)
        start = time.perf_counter()
        parsed = self.page.evaluate('s => __parseIR(s,{documentId:"d0",networkIsolated:true})', source)
        parsed_ms = (time.perf_counter()-start)*1000
        start = time.perf_counter()
        result = invoke({'operation': 'pipeline', 'input': {'snapshotId': hashlib.sha256(source.encode()).hexdigest(), 'documents': [parsed]}, 'request': {'profile': profile, 'maxBytes': 200000, 'planRegions': False}})
        elapsed = (time.perf_counter()-start)*1000
        view, report, packet = result['result']['view'], result['result']['report'], result['packet']
        self.assertEqual(view['version'], 'ui-view/0.1')
        self.assertEqual(report['encodedBytes'], len(packet['text'].encode()))
        self.assertEqual(report['status']=='ready', report['completePromptBytes']<=report['maxBytes'])
        self.assertEqual(len(result['result']['ledger']['nodes']), len(result['bundle']['observation']['nodes']))
        self.assertEqual(len({row['id'] for row in result['result']['ledger']['nodes']}), len(result['result']['ledger']['nodes']))
        self.assertNotIn('grounding', json.loads(packet['text']))
        self.measurements.append({'test': self._testMethodName, 'profile': profile, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'legacy_elements': legacy['report']['outputElements'], 'legacy_html_bytes': len(legacy['html'].encode()),
            'ir_nodes': len(view['nodes']), 'ir_model_bytes': report['encodedBytes'],
            'ir_status': report['status'], 'parse_ms': parsed_ms, 'ir_cli_ms': elapsed})
        return legacy

    @classmethod
    def tearDownClass(cls):
        out=ROOT/'runs/ui-ir-validation'
        out.mkdir(parents=True, exist_ok=True)
        (out/'legacy-input-parity.json').write_text(json.dumps({'comparison':'same source inputs; legacy HTML bytes and IR model JSON bytes, not token/quality equivalence',
            'invocations':len(cls.measurements),'tests_exercised':len({r['test'] for r in cls.measurements}), 'rows':cls.measurements},indent=2)+'\n')
        super().tearDownClass()


if __name__ == '__main__':
    unittest.main()
