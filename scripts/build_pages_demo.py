"""Build a static Pages artifact from the reviewed public datasets only.

Public datasets are listed explicitly in PUBLIC_DATASETS: the banana bread example and the three
SFT-109 held-out test cases (published on 2026-09-14 at the maintainer's decision). Each dataset is
sanitized once into examples/ and validated again at build time; nothing else in the repository is
published.
"""

import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from inspector.build_data import validate  # noqa: E402 - support direct script execution
from scripts.check_staged_files import scan_blob  # noqa: E402

STATIC_FILES = ('index.html', 'app.mjs', 'style.css', 'model.mjs', 'metrics.mjs', 'narration.mjs')
PUBLIC_SOURCE = ROOT / 'examples/banana-bread'
SFT_SOURCE = ROOT / 'examples/sft109-cases'
ALLRECIPES_HOSTS = frozenset({'allrecipes.com', 'www.allrecipes.com'})
SFT_LIMITATIONS = (
    'Sanitized published view; removed fields differ from the local capture.',
    'Held-out SFT-109 test page: the model saw only compact HTML, never the full DOM or a screenshot.',
    'No pixel screenshot exists for this media-suppressed capture; the screenshot pane is a wireframe drawn from captured element geometry and saved DOM text.',
    'Silver reference outline is an automated teacher label, not human gold; the gold standard was authored from the captured DOM on 2026-09-14 and awaits human review.',
)
SFT_VARIANTS = {'sft-109': 'Qwen3.5-9B SFT-109 output', 'silver-reference': 'Silver reference (Gemini teacher)',
                'gold': 'Gold standard (authored, review pending)'}
WIREFRAME = {'kind': 'wireframe', 'note': 'Wireframe drawn from captured element geometry and saved DOM text; the media-suppressed capture recorded no pixel screenshot.'}
PUBLIC_DATASETS = {
    'allrecipes': {
        'label': 'Banana Bread', 'url': 'https://www.allrecipes.com/recipe/20144/banana-banana-bread/',
        'hosts': ALLRECIPES_HOSTS, 'source': PUBLIC_SOURCE,
        'variants': {'baseline': 'Authored original', 'revised': 'Authored revised'}, 'settings': {},
        'screenshot': {},
        'limitations': ('Sanitized published view; removed fields differ from the local capture.',
                        'Authored original and revised hierarchies; these are not model-run results.',
                        'Screenshot and DOM were captured sequentially; only the first viewport is shown.')},
    'sft109-ergo': {
        'label': 'Ergo IRC landing page · SFT-109 test case', 'url': 'https://ergo.chat/',
        'hosts': frozenset({'ergo.chat'}), 'source': SFT_SOURCE, 'variants': SFT_VARIANTS,
        'settings': {'gold': 'gold'}, 'screenshot': WIREFRAME, 'limitations': SFT_LIMITATIONS},
    'sft109-scribblers': {
        'label': 'Scribble.rs lobby configuration · SFT-109 test case', 'url': 'https://scribblers.fly.dev/',
        'hosts': frozenset({'scribblers.fly.dev', 'github.com'}), 'source': SFT_SOURCE, 'variants': SFT_VARIANTS,
        'settings': {'gold': 'gold'}, 'screenshot': WIREFRAME, 'limitations': SFT_LIMITATIONS},
    'sft109-debops': {
        'label': 'DebOps service ports documentation · SFT-109 test case',
        'url': 'https://docs.debops.org/en/stable-3.3/admin-guide/service-ports.html',
        'hosts': frozenset({'docs.debops.org', 'github.com', 'www.sphinx-doc.org', 'readthedocs.org'}),
        'source': SFT_SOURCE, 'variants': SFT_VARIANTS, 'settings': {'gold': 'gold'},
        'screenshot': WIREFRAME, 'limitations': SFT_LIMITATIONS},
}
DATA_FILES = tuple(f'{name}.{ext}' for name in PUBLIC_DATASETS for ext in ('json', 'jpg'))
SAFE_ATTRIBUTES = frozenset({
    'id', 'role', 'alt', 'title', 'type', 'tabindex', 'for', 'disabled',
    'aria-label', 'aria-labelledby', 'aria-describedby', 'aria-controls',
    'aria-hidden', 'aria-expanded', 'aria-disabled', 'aria-modal', 'aria-live',
    'aria-orientation', 'aria-level', 'aria-posinset', 'aria-setsize',
    'aria-haspopup', 'aria-required', 'aria-readonly', 'href',
})
HIERARCHY_FIELDS = {'id', 'kind', 'label', 'summary', 'origin', 'children', 'sourceRefs',
                    'reading_text', 'display_role', 'label_origin'}
INERT_TAGS = {'script', 'style', 'noscript', 'template', 'iframe', 'object', 'embed'}
FORM_TAGS = {'input', 'textarea', 'select', 'option'}
URL_RE = re.compile(r'(?:https?://|file://|(?:localhost|127\.0\.0\.1)(?::\d+)?/)[^\s<>\"\']+', re.I)
LOCAL_PATH = re.compile(r'(?:/(?:Users|home|private|tmp|var|opt)/[^\s<>\"\']+|[A-Za-z]:\\[^\s]+)')
CREDENTIAL_ASSIGNMENT = re.compile(
    r'(?:password|passwd|secret|(?:access|refresh|session|auth)[_-]?token|api[_-]?key|cookie|authorization)'
    r'\s*[=:]\s*\S+', re.I)
EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)


def spec_for(dataset_id):
    if dataset_id not in PUBLIC_DATASETS:
        raise ValueError('Dataset is not on the reviewed public list')
    return PUBLIC_DATASETS[dataset_id]


def safe_url(value, hosts=ALLRECIPES_HOSTS):
    """Only the dataset's public source-site HTTPS paths and document fragments survive."""
    if not isinstance(value, str):
        return ''
    if re.fullmatch(r'#[A-Za-z0-9_-]+', value):
        return value
    try:
        parts = urlsplit(value)
        host = parts.hostname or ''
        if parts.username or parts.password or parts.port not in (None, 443):
            return ''
        try:
            ipaddress.ip_address(host)
            return ''
        except ValueError:
            pass
        if parts.scheme != 'https' or host not in hosts:
            return ''
        if parts.query or re.search(r'(?i)(token|session|secret|password|api[_-]?key)', parts.path):
            return ''
        return urlunsplit(('https', host, parts.path, '', ''))
    except ValueError:
        return ''


def safe_text(value, hosts=ALLRECIPES_HOSTS):
    if not isinstance(value, str):
        return ''
    if scan_blob('public-text.txt', value.encode()) or CREDENTIAL_ASSIGNMENT.search(value):
        return '[omitted]'
    value = LOCAL_PATH.sub('[omitted]', value)
    value = EMAIL.sub('[omitted]', value)
    return URL_RE.sub(lambda match: safe_url(match[0], hosts) or '[omitted]', value)


def sanitized_dataset(source):
    """Preserve graph IDs, but publish only explicit display fields and safe text."""
    validate(source)
    spec = spec_for(source['id'])
    hosts = spec['hosts']
    nodes = []
    form_ids = set()
    for raw in source['dom']['nodes']:
        tag = raw['tag'].lower()
        blocked = tag in INERT_TAGS | FORM_TAGS
        if blocked:
            form_ids.add(raw['id'])
        attrs = {}
        for key, value in raw.get('attributes', {}).items():
            if key not in SAFE_ATTRIBUTES or not isinstance(value, (str, bool, int, float)):
                continue
            cleaned = safe_url(value, hosts) if key == 'href' else safe_text(str(value), hosts)
            if cleaned and cleaned != '[omitted]':
                attrs[key] = cleaned
        node = {
            'id': raw['id'], 'parent': raw['parent'], 'children': list(raw['children']),
            'tag': tag, 'text': '' if blocked else safe_text(raw.get('text', ''), hosts),
            'ownText': '' if blocked else safe_text(raw.get('ownText', ''), hosts),
            'attributes': attrs, 'hidden': bool(raw.get('hidden')),
        }
        rect = raw.get('rect')
        if isinstance(rect, dict):
            node['rect'] = {key: value for key, value in rect.items()
                            if key in {'x', 'y', 'width', 'height', 'top', 'left', 'right', 'bottom'}
                            and isinstance(value, (int, float)) and not isinstance(value, bool)}
        nodes.append(node)
    variants = {}
    for name in spec['variants']:
        tree = source['variants'][name]
        result = []
        for raw in tree['nodes']:
            node = {key: safe_text(raw.get(key, ''), hosts)
                    for key in ('id', 'kind', 'label', 'summary', 'origin')}
            node['children'] = list(raw['children'])
            node['sourceRefs'] = list(raw['sourceRefs'])
            for key in ('reading_text', 'display_role', 'label_origin'):
                if key in raw:
                    node[key] = ('' if key == 'reading_text' and set(raw['sourceRefs']) & form_ids
                                 else safe_text(raw[key], hosts))
            result.append(node)
        variants[name] = {'rootId': tree['rootId'], 'nodes': result}
    shot = source['screenshot']
    dataset = {
        'id': source['id'], 'label': spec['label'], 'url': spec['url'],
        'dom': {'roots': list(source['dom']['roots']), 'nodes': nodes},
        'variants': variants,
        'screenshot': {'url': f"data/{source['id']}.jpg", **{key: shot[key] for key in
                       ('width', 'height', 'scrollX', 'scrollY')}, **spec['screenshot']},
        'limitations': list(spec['limitations']),
    }
    validate_public(dataset)
    return dataset


def validate_public(dataset):
    validate(dataset)
    if set(dataset) != {'id', 'label', 'url', 'dom', 'variants', 'screenshot', 'limitations'}:
        raise ValueError('Unexpected published dataset fields')
    spec = spec_for(dataset['id'])
    hosts = spec['hosts']
    if dataset['label'] != spec['label'] or dataset['url'] != spec['url'] or list(dataset['limitations']) != list(spec['limitations']):
        raise ValueError('Published dataset metadata differs from the reviewed specification')
    if set(dataset['dom']) != {'roots', 'nodes'}:
        raise ValueError('Unexpected DOM container fields')
    if set(dataset['variants']) != set(spec['variants']):
        raise ValueError('Unexpected public dataset or variants')
    for tree in dataset['variants'].values():
        if set(tree) != {'rootId', 'nodes'}:
            raise ValueError('Unexpected hierarchy container fields')
        for node in tree['nodes']:
            if set(node) - HIERARCHY_FIELDS:
                raise ValueError('Unexpected hierarchy field')
    shot = dataset['screenshot']
    expected_shot = {'url', 'width', 'height', 'scrollX', 'scrollY', *spec['screenshot']}
    if set(shot) != expected_shot or shot['url'] != f"data/{dataset['id']}.jpg":
        raise ValueError('Unexpected screenshot metadata')
    if any(shot[key] != value for key, value in spec['screenshot'].items()):
        raise ValueError('Screenshot description differs from the reviewed specification')
    for node in dataset['dom']['nodes']:
        if set(node) - {'id', 'parent', 'children', 'tag', 'text', 'ownText', 'attributes', 'hidden', 'rect'}:
            raise ValueError('Unexpected DOM field')
        if set(node['attributes']) - SAFE_ATTRIBUTES:
            raise ValueError('Unexpected DOM attribute')
        if node['tag'] in INERT_TAGS | FORM_TAGS and (node['text'] or node['ownText']):
            raise ValueError('Inert or form content present')
    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and safe_text(value, hosts) != value:
            raise ValueError('Unsafe string in published dataset')
    walk(dataset)
    for node in dataset['dom']['nodes']:
        if 'href' in node['attributes'] and safe_url(node['attributes']['href'], hosts) != node['attributes']['href']:
            raise ValueError('Unsafe URL attribute')
    payload = json.dumps(dataset, ensure_ascii=False, allow_nan=False).encode()
    if scan_blob('public-dataset.json', payload):
        raise ValueError('Published dataset failed credential scan')


def validate_image(data):
    """Reject metadata-bearing JPEGs; the selected image is reviewed separately."""
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('Expected the reviewed JPEG format')
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 255:
            raise ValueError('Invalid JPEG marker')
        marker = data[offset + 1]
        if marker == 0xDA:  # Start of image data: remaining bytes are not metadata segments.
            return
        if marker in {0xE1, 0xED, 0xFE}:
            raise ValueError('JPEG contains unreviewed EXIF, IPTC, XMP, or comment metadata')
        length = int.from_bytes(data[offset + 2:offset + 4], 'big')
        if length < 2 or offset + 2 + length > len(data):
            raise ValueError('Invalid JPEG segment')
        offset += 2 + length
    raise ValueError('Missing JPEG image data')


def make_catalog(*datasets):
    entries = []
    for dataset in datasets:
        spec = spec_for(dataset['id'])
        entries.append({'id': dataset['id'], 'label': spec['label'], 'url': dataset['url'],
                        'variants': [{'id': name, 'label': label,
                                      **({'setting': spec['settings'][name]} if name in spec['settings'] else {})}
                                     for name, label in spec['variants'].items()],
                        'hasScreenshot': True, 'domCount': len(dataset['dom']['nodes'])})
    return {'datasets': entries}


def build(destination, sources=None, inspector=ROOT / 'inspector'):
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError('Output directory must be empty')
    datasets, files = [], {name: Path(inspector) / name for name in STATIC_FILES}
    for dataset_id, spec in PUBLIC_DATASETS.items():
        source = Path((sources or {}).get(dataset_id, spec['source']))
        dataset = json.loads((source / f'{dataset_id}.json').read_text())
        if dataset['id'] != dataset_id:
            raise ValueError('Reviewed dataset identity mismatch')
        validate_public(dataset)
        validate_image((source / f'{dataset_id}.jpg').read_bytes())
        datasets.append(dataset)
        files[f'data/{dataset_id}.json'] = source / f'{dataset_id}.json'
        files[f'data/{dataset_id}.jpg'] = source / f'{dataset_id}.jpg'
    for name, path in files.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError('Only regular source files may be published')
        if scan_blob(name, path.read_bytes()):
            raise ValueError(f'Publication scan failed for {name}; matched values withheld')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'data').mkdir()
    for name, path in files.items():
        shutil.copyfile(path, destination / name)
    catalog = json.dumps(make_catalog(*datasets), ensure_ascii=False, indent=2)
    if scan_blob('data/catalog.json', catalog.encode()):
        raise ValueError('Publication scan failed for the catalog')
    (destination / 'data/catalog.json').write_text(catalog)
    (destination / '.nojekyll').write_text('')
    return sorted([*files, 'data/catalog.json', '.nojekyll'])


def prepare(dataset_ids, data_root=ROOT / 'inspector/data'):
    """Sanitize local inspector exports into their reviewed public source directory."""
    written = []
    for dataset_id in dataset_ids:
        spec = spec_for(dataset_id)
        source = json.loads((Path(data_root) / f'{dataset_id}.json').read_text())
        dataset = sanitized_dataset(source)
        image = (Path(data_root) / f'{dataset_id}.jpg').read_bytes()
        validate_image(image)
        spec['source'].mkdir(parents=True, exist_ok=True)
        (spec['source'] / f'{dataset_id}.json').write_text(json.dumps(dataset, ensure_ascii=False, separators=(',', ':')))
        (spec['source'] / f'{dataset_id}.jpg').write_bytes(image)
        written.append(dataset_id)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / '.pages-dist')
    parser.add_argument('--prepare', nargs='+', metavar='DATASET_ID',
                        help='Sanitize these inspector/data exports into examples/ instead of building')
    args = parser.parse_args()
    if args.prepare:
        print('Prepared ' + ', '.join(prepare(args.prepare)))
        return
    files = build(args.destination)
    print(f'Built {len(files)} reviewed static files.')


if __name__ == '__main__':
    main()
