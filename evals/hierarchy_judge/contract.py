"""Schema, mechanical preflight, and result consistency checks for the judge.

No model API calls or changes to the project's existing harness.
The optional result-schema check uses the environment's existing jsonschema package.
"""
import argparse
import json
from pathlib import Path

VERSION = 'semantic-hierarchy-judge/0.1'
CHECKS = {
    'fidelity': ('claims_supported', 'qualifiers_preserved'),
    'units': ('membership_coherent', 'dependent_parts_associated'),
    'labels': ('labels_predict_contents', 'destinations_distinguishable'),
    'organization': ('levels_earn_their_place', 'routes_fit_purpose'),
    'coverage': ('in_scope_units_represented', 'peers_treated_consistently'),
    'economy': ('previews_inform_choice', 'default_reading_avoids_repetition'),
    'continuity': ('place_preserved', 'updates_scoped'),
}
GATES = ('structural_integrity', 'meaning_and_action_integrity', 'essential_access')
STATUSES = ('pass', 'fail', 'not_assessable', 'not_applicable')
DECISIONS = ('reject', 'insufficient_evidence', 'revise', 'usable_candidate')


def object_schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def result_schema():
    text = {'type': 'string', 'minLength': 1}
    evidence = object_schema({
        'kind': {'enum': ['source', 'candidate', 'image', 'trace', 'preflight', 'capture', 'context']},
        'id': text, 'pointer': {'type': 'string'}, 'note': {'type': 'string'},
    })
    evidence_list = {'type': 'array', 'items': {'$ref': '#/$defs/evidence'}}
    check = object_schema({'status': {'enum': list(STATUSES)}, 'reason': text, 'evidence': evidence_list})
    gate = object_schema({'status': {'enum': ['pass', 'fail', 'not_assessable']}, 'reason': text, 'evidence': evidence_list})
    criteria = {}
    for key, checks in CHECKS.items():
        criteria[key] = object_schema({
            'status': {'enum': ['assessed', 'not_assessable', 'not_applicable']},
            'score': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 3},
            'reason': text,
            'checks': object_schema({name: {'$ref': '#/$defs/check'} for name in checks}),
        })
    issue = object_schema({
        'id': text, 'severity': {'enum': ['critical', 'major', 'minor']},
        'primary_criterion': {'enum': [*CHECKS, None]},
        'gate_ids': {'type': 'array', 'items': {'enum': list(GATES)}, 'uniqueItems': True},
        'affected_criteria': {'type': 'array', 'items': {'enum': list(CHECKS)}, 'uniqueItems': True},
        'description': text, 'evidence': evidence_list, 'repair': text,
    })
    schema = object_schema({
        'rubric_version': {'const': VERSION}, 'evaluation_id': text, 'candidate_id': text,
        'review': object_schema({
            'extent': {'enum': ['complete', 'partial', 'none']},
            'source_sufficient': {'type': 'boolean'},
            'limitations': {'type': 'array', 'items': text},
        }),
        'gates': object_schema({key: {'$ref': '#/$defs/gate'} for key in GATES}),
        'criteria': object_schema(criteria),
        'issues': {'type': 'array', 'items': issue},
        'decision': {'enum': list(DECISIONS)},
        'next_actions': {'type': 'array', 'items': text, 'maxItems': 5},
    })
    schema.update({'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'urn:semantic-hierarchy-judge:result:0.1', '$defs': {'evidence': evidence, 'check': check, 'gate': gate}})
    return schema


def preflight(packet):
    """Check the supplied graph/inventory. Required refs are a coverage aid only."""
    candidate = packet['candidate']
    source = packet['source']
    raw_nodes = candidate['nodes']
    nodes = {node['id']: node for node in raw_nodes}
    problems = []
    if len(nodes) != len(raw_nodes):
        problems.append('Duplicate presentation node IDs.')
    if candidate['root_id'] not in nodes:
        problems.append('Root does not exist.')
    parents: dict[str, list[str]] = {}
    for node in raw_nodes:
        for child in node.get('children', []):
            parents.setdefault(child, []).append(node['id'])
            if child not in nodes:
                problems.append(f'Missing child {child} referenced by {node["id"]}.')
        if node['kind'] == 'dom' and (node.get('children') or len(node.get('source_refs', [])) != 1):
            problems.append(f'DOM leaf {node["id"]} requires one source reference and no children.')
    for child, owners in parents.items():
        if len(owners) != 1:
            problems.append(f'Multiple presentation parents/edges for {child}.')
    seen, active = set(), set()
    def visit(key):
        if key in active:
            problems.append(f'Cycle at {key}.')
            return
        if key in seen or key not in nodes:
            return
        active.add(key)
        seen.add(key)
        for child in nodes[key].get('children', []):
            visit(child)
        active.remove(key)
    visit(candidate['root_id'])
    if set(nodes) - seen:
        problems.append('Unreachable presentation nodes: ' + ', '.join(sorted(set(nodes) - seen)))
    inventory = {e['id'] for e in source.get('elements', [])}
    images = {e['id'] for e in source.get('images', [])}
    unresolved = []
    all_refs = set()
    for node in raw_nodes:
        refs = list(node.get('source_refs', []))
        if node.get('primary_source'):
            refs.append(node['primary_source'])
        all_refs.update(refs)
        unresolved += [f'{node["id"]}: source {ref}' for ref in refs if ref not in inventory]
        unresolved += [f'{node["id"]}: image {ref}' for ref in node.get('image_refs', []) if ref not in images]
    complete = source.get('complete_for_scope') is True
    ref_status = 'pass' if not unresolved else ('fail' if complete else 'not_assessable')
    required = set(packet['evaluation_context'].get('required_source_ids', []))
    missing_required = sorted(required - all_refs)
    # Presence in provenance is not exposure; absence may still require checking a fallback.
    return {
        'graph': {'status': 'fail' if problems else 'pass', 'details': problems or ['Connected acyclic single-parent graph.']},
        'references': {'status': ref_status, 'details': unresolved or ['Declared source/image/primary-target IDs resolve.']},
        'required_sources': {
            'status': 'not_assessable' if missing_required else 'pass',
            'details': ['Required IDs are referenced somewhere; evaluate presentation access separately.'] if not missing_required else ['No explicit references for: ' + ', '.join(missing_required), 'Check caller-approved descendant expansion/fallback before judging essential access.'],
        },
    }


def derive_decision(packet, result):
    if any(g['status'] == 'fail' for g in result['gates'].values()):
        return 'reject'
    required = [key for key in CHECKS if key != 'continuity']
    if packet['evaluation_context'].get('runtime_assessment_required', False):
        required.append('continuity')
    if (packet['source'].get('complete_for_scope') is not True
            or result['review']['extent'] != 'complete' or not result['review']['source_sufficient']
            or any(g['status'] == 'not_assessable' for g in result['gates'].values())
            or any(result['criteria'][key]['status'] == 'not_assessable' for key in required)):
        return 'insufficient_evidence'
    if any(result['criteria'][key]['status'] == 'assessed' and result['criteria'][key]['score'] <= 1 for key in required):
        return 'revise'
    return 'usable_candidate'


def resolve_evidence(packet, evidence):
    collections = {
        'source': {e['id']: e for e in packet['source'].get('elements', [])},
        'candidate': {n['id']: n for n in packet['candidate']['nodes']},
        'image': {e['id']: e for e in packet['source'].get('images', [])},
        'trace': {e['id']: e for e in packet['source'].get('traces', [])},
        'preflight': packet.get('preflight', {}),
        'capture': {packet['source']['capture_id']: packet['source']},
        'context': {packet['evaluation_context']['scope_id']: packet['evaluation_context']},
    }
    value = collections[evidence['kind']][evidence['id']]
    pointer = evidence['pointer']
    if pointer:
        if not pointer.startswith('/'):
            raise ValueError('Evidence pointer must be empty or an RFC 6901 pointer.')
        for raw in pointer[1:].split('/'):
            key = raw.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def validate_result(packet, result):
    import jsonschema  # Already available locally; not needed to use the prompt itself.
    jsonschema.Draft202012Validator(result_schema()).validate(result)
    assert result['evaluation_id'] == packet['evaluation_id'], 'Evaluation ID mismatch'
    assert result['candidate_id'] == packet['candidate']['id'], 'Candidate ID mismatch'
    mechanical = preflight(packet)
    structural = result['gates']['structural_integrity']['status']
    if mechanical['graph']['status'] == 'fail' or mechanical['references']['status'] == 'fail':
        assert structural == 'fail', 'Structural gate contradicts a confirmed mechanical failure'
    elif mechanical['references']['status'] == 'not_assessable':
        assert structural == 'not_assessable', 'Incomplete source inventory cannot establish reference validity or invalidity'
    for key, criterion in result['criteria'].items():
        assert (criterion['status'] == 'assessed') == (criterion['score'] is not None), f'{key}: status/score mismatch'
        checks = criterion['checks'].values()
        if criterion['status'] == 'not_applicable':
            assert all(c['status'] == 'not_applicable' for c in checks), f'{key}: NA contradicts its checks'
        if criterion['status'] == 'assessed':
            assert any(c['status'] in {'pass', 'fail'} for c in checks), f'{key}: no assessed check'
            if criterion['score'] >= 2:
                assert all(c['status'] != 'not_assessable' for c in checks), f'{key}: high score with missing necessary evidence'
    if result['criteria']['fidelity']['score'] == 0:
        assert result['gates']['meaning_and_action_integrity']['status'] == 'fail', 'Fidelity 0 establishes a material integrity failure under this rubric'
    issues = result['issues']
    assert len({i['id'] for i in issues}) == len(issues), 'Duplicate issue IDs'
    for issue in issues:
        assert issue['primary_criterion'] is not None or issue['gate_ids'], 'Gate-only issue requires gate attribution'
        assert issue['evidence'], 'Issue requires evidence'
    def walk(value):
        if isinstance(value, dict):
            if set(value) == {'kind', 'id', 'pointer', 'note'}:
                resolve_evidence(packet, value)
            if 'status' in value and 'evidence' in value and value['status'] in {'pass', 'fail'}:
                assert value['evidence'], 'Supported pass/fail check requires evidence'
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(result)
    expected = derive_decision(packet, result)
    assert result['decision'] == expected, f'Decision mismatch: expected {expected}'
    return {'status': 'valid_contract', 'decision': expected, 'meaning': 'Schema, references, and decision consistency only; semantic judgment not independently verified.'}


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    schema_cmd = commands.add_parser('schema')
    schema_cmd.add_argument('output', type=Path)
    pre = commands.add_parser('preflight')
    pre.add_argument('input', type=Path)
    pre.add_argument('output', type=Path)
    validate = commands.add_parser('validate')
    validate.add_argument('input', type=Path)
    validate.add_argument('result', type=Path)
    args = parser.parse_args()
    if args.command == 'schema':
        args.output.write_text(json.dumps(result_schema(), indent=2) + '\n')
    elif args.command == 'preflight':
        packet = json.loads(args.input.read_text())
        packet['preflight'] = preflight(packet)
        packet['evaluation_context']['preflight_trusted'] = True
        args.output.write_text(json.dumps(packet, indent=2) + '\n')
    else:
        print(json.dumps(validate_result(json.loads(args.input.read_text()), json.loads(args.result.read_text())), indent=2))


if __name__ == '__main__':
    main()
