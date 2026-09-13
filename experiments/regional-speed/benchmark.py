"""Paired local region probes; continue after invalid model outputs and report them."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness.ollama_model import OllamaClient  # noqa: E402
from inspector.compact_input import load_compact  # noqa: E402
from inspector.compact_comparison import _validate, run_compact_comparison  # noqa: E402
from inspector.lean_comparison import _decode, _encode, run_lean_comparison  # noqa: E402
from inspector.anchor_comparison import _decode as decode_anchors, _labels, run_anchor_comparison  # noqa: E402
from inspector.selection_comparison import _decode as decode_selection, _candidates, LIMIT, run_selection_comparison  # noqa: E402


class Planner:
    def __init__(self):
        self.calls = []

    def generate(self, model, system, prompt, **kwargs):
        self.calls.append({'system': system, 'prompt': prompt, **kwargs})
        if 'keep' in kwargs['response_schema']['properties']:
            return {'keep': [], 'needs_expansion': []}, {}
        if 'regions' in kwargs['response_schema']['properties']:
            return {'regions': [], 'needs_expansion': []}, {}
        return ({'groups': [], 'e': []} if 'e' in kwargs['response_schema']['properties']
                else {'groups': [], 'needs_expansion': []}), {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', default='gov-uk')
    parser.add_argument('--regions', type=int, default=3)
    parser.add_argument('--region-size', type=int, default=160)
    parser.add_argument('--model', default='qwen3.5:2b')
    parser.add_argument('--methods', nargs='+', choices=['standard','lean','anchors','selection'], default=['standard','selection'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    prepared = load_compact(args.site)
    plans = {}
    for name, runner in [('standard', run_compact_comparison), ('lean', run_lean_comparison), ('anchors', run_anchor_comparison), ('selection', run_selection_comparison)]:
        planner = Planner()
        result = runner(prepared, 'regions', planner, args.model, region_size=args.region_size)
        plans[name] = (planner.calls, result['regions'])
    assert all(plans['standard'][1] == plans[method][1] for method in args.methods), 'Partitions differ'
    client = OllamaClient(args.output, max_calls=args.regions * len(args.methods) + 1)
    client.deadline = time.monotonic() + 900
    client.generate(args.model, 'Return JSON only.', 'Return an object with ok set to true.',
                    purpose='warmup', max_tokens=16,
                    response_schema={'type':'OBJECT','properties':{'ok':{'type':'BOOLEAN'}},'required':['ok']})
    report = {'site': args.site, 'model': args.model, 'input_provenance': prepared['provenance'],
              'region_size': args.region_size, 'total_page_regions': len(plans['standard'][0]),
              'scope': 'Independent section probes; not a full-page timing or semantic-quality benchmark.',
              'order': 'Alternate method order after warmup.', 'methods':args.methods, 'protocol':'section-probe/2', 'results': []}
    for index in range(min(args.regions, len(plans['standard'][0]))):
        base = plans['standard'][0][index]
        source = json.loads(base['prompt'])
        old = base['response_schema']['properties']
        owned = old['groups']['items']['properties']['source_ids']['items']['enum']
        observed = old['needs_expansion']['items']['enum']
        _, aliases, labels = _encode(source['html'], source['reference_attribute'], observed)
        for method in (args.methods if index % 2 == 0 else list(reversed(args.methods))):
            call = plans[method][0][index]
            entry = {'method': method, 'region': index + 1,
                     'owned_nodes': len(owned), 'evidence_sha256': hashlib.sha256(source['html'].encode()).hexdigest(),
                     'request': call, 'accepted': False}
            started = time.monotonic()
            try:
                output, metadata = client.generate(args.model, call['system'], call['prompt'],
                    purpose=f"section-probe:{args.site}:r{index+1}:{method}",
                    max_tokens=call['max_tokens'], response_schema=call['response_schema'])
                entry.update(output=output, metadata=metadata)
                if method == 'selection':
                    nodes = [n for d in prepared['documents'] for n in d['nodes']]
                    proposals = _candidates(source['html'], source['reference_attribute'], owned, observed, nodes)[:LIMIT]
                    normalized, _ = decode_selection(output, proposals, nodes, owned, observed, source['group_budget'], 'probe')
                elif method == 'anchors':
                    labels_anchors = _labels(source['html'], source['reference_attribute'], observed)
                    nodes = [n for d in prepared['documents'] for n in d['nodes']]
                    normalized, _ = decode_anchors(output, nodes, owned, observed, labels_anchors, source['group_budget'], 'probe')
                elif method == 'lean':
                    normalized, _ = _decode(output, aliases, labels, owned, source['group_budget'], 'probe')
                else:
                    groups, expansion = _validate(output, owned, observed, source['group_budget'], 'probe')
                    normalized = {'groups': groups, 'needs_expansion': expansion}
                entry.update(accepted=True, normalized_output=normalized,
                             assigned_nodes=len({ref for g in normalized['groups'] for ref in g['source_ids']}))
            except (ValueError, RuntimeError, OSError) as error:
                entry['error'] = str(error)
            entry['wall_seconds'] = time.monotonic() - started
            report['results'].append(entry)
            (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            usage = entry.get('metadata', {}).get('usage', {})
            print(json.dumps({k:entry.get(k) for k in ['method','region','accepted','wall_seconds','error']} |
                             {'input_tokens':usage.get('promptTokenCount'),'output_tokens':usage.get('candidatesTokenCount')}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
