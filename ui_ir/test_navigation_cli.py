"""Bounded source identity and exclusion checks through the public JSON bridge."""
import hashlib
import json
import unittest

from ui_ir.bridge import invoke


def fixture():
    records = [
        {'id': '0', 'kind': 'element', 'tag': '#document', 'parent': None, 'children': ['1', '3'], 'attributes': {}},
        {'id': '1', 'kind': 'element', 'tag': 'div', 'parent': '0', 'children': ['2'], 'attributes': {'aria-hidden': 'true'}},
        {'id': '2', 'kind': 'element', 'tag': 'button', 'parent': '1', 'children': [], 'attributes': {}},
        {'id': '3', 'kind': 'element', 'tag': 'button', 'parent': '0', 'children': [], 'attributes': {}},
    ]
    return invoke({'operation': 'pipeline', 'input': {'snapshotId': 'navigation-test', 'documents': [
        {'documentId': 'd0', 'profile': 'saved-dom', 'roots': ['0'], 'records': records}]}})


class NavigationCLITests(unittest.TestCase):
    def test_scoped_hidden_control_stays_excluded(self):
        bundle = fixture()
        observation = bundle['bundle']['observation']
        scope = invoke({'operation': 'compact', 'observation': observation, 'request': {'roots': ['d0:2']}})
        packet = invoke({'operation': 'navigation', 'view': scope['result']['view'], 'observation': observation})
        self.assertNotIn('d0:2', packet['eligibleSourceIds'])

    def test_rehashed_forged_projection_rejected_against_bound_view(self):
        bundle = fixture()
        observation, view = bundle['bundle']['observation'], bundle['result']['view']
        packet = invoke({'operation': 'navigation', 'view': view, 'observation': observation})
        hidden = next(alias for alias, key in packet['aliases']['nodes'].items() if key == 'd0:2')
        packet['eligibleIds'].append(hidden)
        packet['eligibleSourceIds'].append('d0:2')
        model = json.loads(packet['text'])
        model['nodes'].append([hidden, 'button', []])
        packet['text'] = json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        packet.pop('packetHash')
        packet['packetHash'] = hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'Stale packetHash'):
            invoke({'operation': 'navigation-references', 'packet': packet, 'refs': [hidden], 'view': view, 'observation': observation})

    def test_valid_visible_control_resolves(self):
        bundle = fixture()
        observation, view = bundle['bundle']['observation'], bundle['result']['view']
        packet = invoke({'operation': 'navigation', 'view': view, 'observation': observation})
        visible = next(alias for alias, key in packet['aliases']['nodes'].items() if key == 'd0:3')
        result = invoke({'operation': 'navigation-references', 'packet': packet, 'refs': [visible], 'view': view, 'observation': observation})
        self.assertEqual(result['ids'], ['d0:3'])


if __name__ == '__main__':
    unittest.main()
