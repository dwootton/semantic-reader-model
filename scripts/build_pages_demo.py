"""Build a static Pages artifact from the reviewed banana bread example only."""

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
DATA_FILES = ('allrecipes.json', 'catalog.json', 'allrecipes.jpg')
PUBLIC_SOURCE = ROOT / 'examples/banana-bread'
SAFE_ATTRIBUTES = frozenset({
    'id', 'role', 'alt', 'title', 'type', 'tabindex', 'for', 'disabled',
    'aria-label', 'aria-labelledby', 'aria-describedby', 'aria-controls',
    'aria-hidden', 'aria-expanded', 'aria-disabled', 'aria-modal', 'aria-live',
    'aria-orientation', 'aria-level', 'aria-posinset', 'aria-setsize',
    'aria-haspopup', 'aria-required', 'aria-readonly', 'href',
})
INERT_TAGS = {'script', 'style', 'noscript', 'template', 'iframe', 'object', 'embed'}
FORM_TAGS = {'input', 'textarea', 'select', 'option'}
URL_RE = re.compile(r'(?:https?://|file://|(?:localhost|127\.0\.0\.1)(?::\d+)?/)[^\s<>\"\']+', re.I)
LOCAL_PATH = re.compile(r'(?:/(?:Users|home|private|tmp|var|opt)/[^\s<>\"\']+|[A-Za-z]:\\[^\s]+)')
CREDENTIAL_ASSIGNMENT = re.compile(
    r'(?:password|passwd|secret|(?:access|refresh|session|auth)[_-]?token|api[_-]?key|cookie|authorization)'
    r'\s*[=:]\s*\S+', re.I)
EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)


def safe_url(value):
    """Only public source-site HTTPS paths and document fragments survive."""
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
        if parts.scheme != 'https' or host not in {'allrecipes.com', 'www.allrecipes.com'}:
            return ''
        if parts.query or re.search(r'(?i)(token|session|secret|password|api[_-]?key)', parts.path):
            return ''
        return urlunsplit(('https', host, parts.path, '', ''))
    except ValueError:
        return ''


def safe_text(value):
    if not isinstance(value, str):
        return ''
    if scan_blob('public-text.txt', value.encode()) or CREDENTIAL_ASSIGNMENT.search(value):
        return '[omitted]'
    value = LOCAL_PATH.sub('[omitted]', value)
    value = EMAIL.sub('[omitted]', value)
    return URL_RE.sub(lambda match: safe_url(match[0]) or '[omitted]', value)


def sanitized_dataset(source):
    """Preserve graph IDs, but publish only explicit display fields and safe text."""
    validate(source)
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
            cleaned = safe_url(value) if key == 'href' else safe_text(str(value))
            if cleaned and cleaned != '[omitted]':
                attrs[key] = cleaned
        node = {
            'id': raw['id'], 'parent': raw['parent'], 'children': list(raw['children']),
            'tag': tag, 'text': '' if blocked else safe_text(raw.get('text', '')),
            'ownText': '' if blocked else safe_text(raw.get('ownText', '')),
            'attributes': attrs, 'hidden': bool(raw.get('hidden')),
        }
        rect = raw.get('rect')
        if isinstance(rect, dict):
            node['rect'] = {key: value for key, value in rect.items()
                            if key in {'x', 'y', 'width', 'height', 'top', 'left', 'right', 'bottom'}
                            and isinstance(value, (int, float)) and not isinstance(value, bool)}
        nodes.append(node)
    variants = {}
    for name in ('baseline', 'revised'):
        tree = source['variants'][name]
        result = []
        for raw in tree['nodes']:
            node = {key: safe_text(raw.get(key, ''))
                    for key in ('id', 'kind', 'label', 'summary', 'origin')}
            node['children'] = list(raw['children'])
            node['sourceRefs'] = list(raw['sourceRefs'])
            for key in ('reading_text', 'display_role', 'label_origin'):
                if key in raw:
                    node[key] = ('' if key == 'reading_text' and set(raw['sourceRefs']) & form_ids
                                 else safe_text(raw[key]))
            result.append(node)
        variants[name] = {'rootId': tree['rootId'], 'nodes': result}
    shot = source['screenshot']
    dataset = {
        'id': 'allrecipes', 'label': 'Banana Bread',
        'url': 'https://www.allrecipes.com/recipe/20144/banana-banana-bread/',
        'dom': {'roots': list(source['dom']['roots']), 'nodes': nodes},
        'variants': variants,
        'screenshot': {'url': 'data/allrecipes.jpg', **{key: shot[key] for key in
                       ('width', 'height', 'scrollX', 'scrollY')}},
        'limitations': ['Sanitized published view; removed fields differ from the local capture.',
                        'Authored original and revised hierarchies; these are not model-run results.',
                        'Screenshot and DOM were captured sequentially; only the first viewport is shown.'],
    }
    validate_public(dataset)
    return dataset


def validate_public(dataset):
    validate(dataset)
    if set(dataset) != {'id', 'label', 'url', 'dom', 'variants', 'screenshot', 'limitations'}:
        raise ValueError('Unexpected published dataset fields')
    if set(dataset['dom']) != {'roots', 'nodes'}:
        raise ValueError('Unexpected DOM container fields')
    for tree in dataset['variants'].values():
        if set(tree) != {'rootId', 'nodes'}:
            raise ValueError('Unexpected hierarchy container fields')
        for node in tree['nodes']:
            if set(node) - {'id', 'kind', 'label', 'summary', 'origin', 'children',
                            'sourceRefs', 'reading_text', 'display_role', 'label_origin'}:
                raise ValueError('Unexpected hierarchy field')
    shot = dataset['screenshot']
    if set(shot) != {'url', 'width', 'height', 'scrollX', 'scrollY'} or shot['url'] != 'data/allrecipes.jpg':
        raise ValueError('Unexpected screenshot metadata')
    if dataset['id'] != 'allrecipes' or set(dataset['variants']) != {'baseline', 'revised'}:
        raise ValueError('Unexpected public dataset or variants')
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
        elif isinstance(value, str) and safe_text(value) != value:
            raise ValueError('Unsafe string in published dataset')
    walk(dataset)
    for node in dataset['dom']['nodes']:
        if 'href' in node['attributes'] and safe_url(node['attributes']['href']) != node['attributes']['href']:
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


def build(destination, source=PUBLIC_SOURCE, inspector=ROOT / 'inspector'):
    destination = Path(destination)
    source = Path(source)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError('Output directory must be empty')
    dataset = json.loads((source / 'allrecipes.json').read_text())
    validate_public(dataset)
    catalog = json.loads((source / 'catalog.json').read_text())
    expected_catalog = make_catalog(dataset)
    if catalog != expected_catalog:
        raise ValueError('Public catalog does not match reviewed dataset')
    validate_image((source / 'allrecipes.jpg').read_bytes())
    files = {name: Path(inspector) / name for name in STATIC_FILES}
    files.update({f'data/{name}': source / name for name in DATA_FILES})
    for name, path in files.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError('Only regular source files may be published')
        if scan_blob(name, path.read_bytes()):
            raise ValueError(f'Publication scan failed for {name}; matched values withheld')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'data').mkdir()
    for name, path in files.items():
        shutil.copyfile(path, destination / name)
    (destination / '.nojekyll').write_text('')
    return sorted([*files, '.nojekyll'])


def make_catalog(dataset):
    return {'datasets': [{'id': 'allrecipes', 'label': 'Banana Bread', 'url': dataset['url'],
                          'variants': [{'id': 'baseline', 'label': 'Authored original'},
                                       {'id': 'revised', 'label': 'Authored revised'}],
                          'hasScreenshot': True, 'domCount': len(dataset['dom']['nodes'])}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / '.pages-dist')
    args = parser.parse_args()
    files = build(args.destination)
    print(f'Built {len(files)} reviewed static files.')


if __name__ == '__main__':
    main()
