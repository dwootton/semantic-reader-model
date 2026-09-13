import copy
import json
import unittest
from pathlib import Path

import contract

ROOT = Path(__file__).parent


def packet(name='good'):
    return json.loads((ROOT/'fixtures'/f'{name}.json').read_text())


def result_for(p):
    evidence = [{'kind': 'candidate', 'id': 'product', 'pointer': '/label', 'note': 'Test contract reference.'}]
    criteria = {}
    for key, checks in contract.CHECKS.items():
        criteria[key] = {
            'status': 'assessed', 'score': 2, 'reason': 'Synthetic contract-test placeholder, not a quality rating.',
            'checks': {name: {'status': 'pass', 'reason': 'Synthetic contract-test check.', 'evidence': copy.deepcopy(evidence)} for name in checks},
        }
    criteria['continuity'] = {
        'status': 'not_assessable', 'score': None, 'reason': 'No transitions supplied.',
        'checks': {name: {'status': 'not_assessable', 'reason': 'No transition evidence.', 'evidence': []} for name in contract.CHECKS['continuity']},
    }
    r = {
        'rubric_version': contract.VERSION, 'evaluation_id': p['evaluation_id'], 'candidate_id': p['candidate']['id'],
        'review': {'extent': 'complete', 'source_sufficient': True, 'limitations': ['Contract-only test; no semantic judgment.']},
        'gates': {key: {'status': 'pass', 'reason': 'Synthetic contract-test gate.', 'evidence': copy.deepcopy(evidence)} for key in contract.GATES},
        'criteria': criteria, 'issues': [], 'decision': 'usable_candidate', 'next_actions': [],
    }
    r['decision'] = contract.derive_decision(p, r)
    return r


class ContractTests(unittest.TestCase):
    def test_complete_and_incomplete_reference_inventory_differ(self):
        partial = packet('incomplete_source')
        self.assertEqual(contract.preflight(partial)['references']['status'], 'not_assessable')
        partial['source']['complete_for_scope'] = True
        self.assertEqual(contract.preflight(partial)['references']['status'], 'fail')

    def test_primary_target_is_checked(self):
        self.assertEqual(contract.preflight(packet('bad_primary_target'))['references']['status'], 'fail')

    def test_missing_control_is_not_hidden_by_parent_source_reference(self):
        checks = contract.preflight(packet('missing_control'))
        self.assertEqual(checks['graph']['status'], 'pass')
        self.assertEqual(checks['required_sources']['status'], 'not_assessable')
        self.assertIn('s_buy', ' '.join(checks['required_sources']['details']))

    def test_cycle_does_not_recurse_forever(self):
        p = packet()
        p['candidate']['nodes'][0]['children'].append('product')
        self.assertEqual(contract.preflight(p)['graph']['status'], 'fail')

    def test_duplicate_presentation_parent_is_rejected(self):
        p = packet()
        p['candidate']['nodes'][0]['children'].append('buy')
        self.assertEqual(contract.preflight(p)['graph']['status'], 'fail')

    def test_optional_runtime_evidence_does_not_block_static_review(self):
        p = packet()
        self.assertEqual(contract.validate_result(p, result_for(p))['decision'], 'usable_candidate')

    def test_required_runtime_evidence_blocks_unqualified_pass(self):
        p = packet('runtime_missing')
        self.assertEqual(contract.validate_result(p, result_for(p))['decision'], 'insufficient_evidence')

    def test_known_failure_precedes_missing_runtime_evidence(self):
        p = packet('known_failure_and_unknown')
        r = result_for(p)
        r['gates']['meaning_and_action_integrity']['status'] = 'fail'
        r['criteria']['fidelity']['score'] = 0
        r['criteria']['fidelity']['checks']['claims_supported']['status'] = 'fail'
        r['criteria']['fidelity']['checks']['qualifiers_preserved'] = {'status': 'not_assessable', 'reason': 'An unrelated region is missing.', 'evidence': []}
        r['decision'] = 'reject'
        self.assertEqual(contract.validate_result(p, r)['decision'], 'reject')

    def test_high_score_cannot_ignore_missing_check_evidence(self):
        p = packet()
        r = result_for(p)
        r['criteria']['fidelity']['checks']['qualifiers_preserved'] = {'status': 'not_assessable', 'reason': 'Missing source.', 'evidence': []}
        with self.assertRaises(AssertionError):
            contract.validate_result(p, r)

    def test_material_fidelity_failure_cannot_be_downgraded_to_revision(self):
        p = packet()
        r = result_for(p)
        r['criteria']['fidelity']['score'] = 0
        r['criteria']['fidelity']['checks']['claims_supported']['status'] = 'fail'
        r['decision'] = 'revise'
        with self.assertRaises(AssertionError):
            contract.validate_result(p, r)

    def test_numeric_score_cannot_accompany_unassessed_status(self):
        p = packet()
        r = result_for(p)
        r['criteria']['continuity']['score'] = 3
        with self.assertRaises(AssertionError):
            contract.validate_result(p, r)

    def test_fabricated_evidence_is_rejected(self):
        p = packet()
        r = result_for(p)
        r['gates']['essential_access']['evidence'][0]['id'] = 'imaginary-node'
        with self.assertRaises(KeyError):
            contract.validate_result(p, r)

    def test_pointer_must_reference_existing_field(self):
        p = packet()
        r = result_for(p)
        r['gates']['essential_access']['evidence'][0]['pointer'] = '/nonexistent'
        with self.assertRaises(KeyError):
            contract.validate_result(p, r)

    def test_computed_decision_cannot_be_overridden(self):
        p = packet('runtime_missing')
        r = result_for(p)
        r['decision'] = 'usable_candidate'
        with self.assertRaises(AssertionError):
            contract.validate_result(p, r)

    def test_model_cannot_override_caller_source_completeness(self):
        p = packet()
        p['source']['complete_for_scope'] = False
        r = result_for(p)
        self.assertEqual(r['decision'], 'insufficient_evidence')

    def test_mechanical_graph_failure_cannot_be_scored_as_pass(self):
        p = packet()
        p['candidate']['nodes'][0]['children'].append('missing')
        with self.assertRaises(AssertionError):
            contract.validate_result(p, result_for(p))

    def test_checked_in_schema_matches_generator(self):
        self.assertEqual(json.loads((ROOT/'result.schema.json').read_text()), contract.result_schema())


if __name__ == '__main__':
    unittest.main()
