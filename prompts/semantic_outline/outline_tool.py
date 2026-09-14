"""Parse, validate, render and convert semantic-outline model output.

Usage:
  python3 outline_tool.py check  OUTPUT.json --source-map SOURCE_MAP.json [--refmap REFMAP.json] [--dataset inspector/data/SITE.json]
        [--md OUT.md] [--hierarchy OUT.json]
  python3 outline_tool.py md     OUTPUT.json            # print the gold-format outline

OUTPUT.json is the labeler's JSON ({page, scope, outline:[{depth,label,refs?}], needs_expansion}).
A Markdown outline in the reference form (bullets with `→ \`ref, ref\``) is also accepted.
"""
import argparse, json, re, sys
from pathlib import Path


def load_output(path):
    text = Path(path).read_text()
    stripped = text.strip()
    if stripped.startswith('{'):
        data = json.loads(stripped)
    else:
        # tolerate a fenced JSON block or a markdown outline
        m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S)
        if m:
            data = json.loads(m.group(1))
        else:
            data = parse_markdown(text)
    lines = data.get('outline') or []
    return data, lines


def parse_markdown(text):
    lines = []
    for raw in text.splitlines():
        m = re.match(r'^(\s*)- (.*)$', raw)
        if not m:
            continue
        depth = len(m.group(1)) // 2
        body = m.group(2)
        refs = []
        rm = re.search(r'\s*→\s*`([^`]*)`\s*$', body)
        if rm:
            refs = [r.strip() for r in re.split(r'[,\s]+', rm.group(1)) if r.strip() and not r.startswith('…') and r != '+']
            refs = [r for r in refs if not re.fullmatch(r'\+?\d+', r) and r not in ('more',)]
            body = body[:rm.start()]
        entry = {'depth': depth, 'label': body.strip()}
        if refs:
            entry['refs'] = refs
        lines.append(entry)
    return {'page': lines[0]['label'] if lines else '', 'scope': '', 'outline': lines, 'needs_expansion': []}


def valid_refs_from_source_map(path):
    sm = json.load(open(path))
    # A reference is valid when it was emitted (retained) or represents a folded/deferred subtree.
    emitted = {x['id'] for x in sm if x.get('disposition') == 'retained'}
    represented = {x['representedBy'] for x in sm if x.get('representedBy')}
    return emitted | represented, sm


def validate(lines, valid=None):
    errors, warnings = [], []
    if not lines:
        return ['empty outline'], warnings
    if lines[0].get('depth') != 0:
        errors.append('first line must have depth 0')
    if sum(1 for l in lines if l.get('depth') == 0) != 1:
        errors.append('exactly one depth-0 line is allowed')
    prev = -1
    seen = {}
    for i, l in enumerate(lines):
        d = l.get('depth')
        if not isinstance(d, int) or d < 0:
            errors.append(f'line {i}: bad depth {d!r}'); continue
        if d > prev + 1:
            errors.append(f'line {i} ({l.get("label","")[:40]!r}): depth jumps from {prev} to {d}')
        prev = d
        label = l.get('label')
        if not isinstance(label, str) or not label.strip():
            errors.append(f'line {i}: empty label')
        elif len(label) > 200:
            warnings.append(f'line {i}: label longer than 200 characters')
        refs = l.get('refs') or []
        if refs is not None and not isinstance(refs, list):
            errors.append(f'line {i}: refs must be a list'); refs = []
        for r in refs:
            if not isinstance(r, str) or not r:
                errors.append(f'line {i}: bad ref {r!r}'); continue
            if valid is not None and r not in valid:
                errors.append(f'line {i} ({label[:40]!r}): unknown ref {r}')
            if r in seen:
                warnings.append(f'line {i}: ref {r} already used by line {seen[r]}')
            else:
                seen[r] = i
    # groups need children
    for i, l in enumerate(lines):
        if l.get('refs'):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if not nxt or nxt.get('depth', 0) != l.get('depth', 0) + 1:
            errors.append(f'line {i} ({l.get("label","")[:40]!r}): group without children')
    return errors, warnings


def render_md(lines, max_refs=6):
    out = []
    for l in lines:
        refs = l.get('refs') or []
        suffix = ''
        if refs:
            shown = ', '.join(refs[:max_refs]) + (f' … +{len(refs) - max_refs} more' if len(refs) > max_refs else '')
            suffix = f' → `{shown}`'
        out.append('  ' * l['depth'] + '- ' + l['label'] + suffix)
    return '\n'.join(out)


def to_hierarchy(data, lines, refmap=None, dataset=None, site_id='model'):
    """Convert to the inspector hierarchy schema (same as condensed.json). refmap maps input refs -> capture ids."""
    dom = {}
    if dataset:
        ds = json.load(open(dataset))
        dom = {n['id']: n for n in ds['dom']['nodes']}
        site_id = ds['id']
    def text(e):
        n = dom.get(e)
        if not n:
            return ''
        return ' '.join((n.get('text') or '').split())
    nodes = []
    stack = []  # (depth, id)
    counter = 0
    for i, l in enumerate(lines):
        d = l['depth']
        while stack and stack[-1][0] >= d:
            stack.pop()
        parent = stack[-1][1] if stack else None
        refs = l.get('refs') or []
        mapped = [refmap.get(r, r) if refmap else r for r in refs]
        mapped = [m for m in mapped if not dom or m in dom]
        if refs:
            nid = f'u{i}'
            node = {'id': nid, 'kind': 'dom', 'label': l['label'], 'summary': '', 'reading_text': text(mapped[0]) if mapped else l['label'],
                    'children': [], 'source_refs': mapped, 'origin': 'source', 'display_role': (dom.get(mapped[0], {}).get('tag') if mapped else '')}
        else:
            nid = 'page' if d == 0 else f'g{i}'
            node = {'id': nid, 'kind': 'group', 'label': l['label'], 'summary': data.get('scope', '') if d == 0 else '',
                    'children': [], 'source_refs': [], 'origin': 'inferred', 'display_role': 'doc' if d == 0 else ''}
        nodes.append(node)
        if parent is not None:
            next(n for n in nodes if n['id'] == parent)['children'].append(nid)
        stack.append((d, nid))
    # group refs = first ref of each child unit (as the authored files do)
    by = {n['id']: n for n in nodes}
    def fill(n):
        if n['kind'] == 'group' and not n['source_refs']:
            refs = []
            for c in n['children']:
                fill(by[c])
                for r in by[c]['source_refs'][:1]:
                    if r not in refs:
                        refs.append(r)
            n['source_refs'] = refs
    fill(nodes[0])
    if dom and not nodes[0]['source_refs']:
        roots = [r for r in json.load(open(dataset))['dom']['roots']]
        nodes[0]['source_refs'] = roots[:1]
    return {'site_id': site_id, 'root_id': nodes[0]['id'], 'method': 'Model-generated semantic outline (prompts/semantic_outline)',
            'scope': data.get('scope', ''), 'nodes': nodes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['check', 'md'])
    ap.add_argument('output')
    ap.add_argument('--source-map')
    ap.add_argument('--refmap')
    ap.add_argument('--dataset')
    ap.add_argument('--md')
    ap.add_argument('--hierarchy')
    a = ap.parse_args()
    data, lines = load_output(a.output)
    if a.command == 'md':
        print(render_md(lines)); return
    valid = None
    if a.source_map:
        valid, _ = valid_refs_from_source_map(a.source_map)
    errors, warnings = validate(lines, valid)
    units = [l for l in lines if l.get('refs')]
    groups = [l for l in lines if not l.get('refs')]
    refs = {r for l in units for r in l['refs']}
    report = {'lines': len(lines), 'groups': len(groups), 'units': len(units), 'distinct_refs': len(refs),
              'max_depth': max((l['depth'] for l in lines), default=0), 'errors': errors, 'warnings': warnings[:40],
              'warning_count': len(warnings), 'needs_expansion': data.get('needs_expansion', [])}
    print(json.dumps(report, indent=1, ensure_ascii=False))
    if a.md:
        Path(a.md).write_text(f"# {data.get('page','')}\n\nScope: {data.get('scope','')}\n\n" + render_md(lines) + '\n')
    if a.hierarchy:
        refmap = json.load(open(a.refmap)) if a.refmap else None
        h = to_hierarchy(data, lines, refmap, a.dataset)
        Path(a.hierarchy).write_text(json.dumps(h, ensure_ascii=False, indent=1))
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
