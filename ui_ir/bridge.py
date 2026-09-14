"""Offline browser parsing and bounded JSON transport to the dependency-free IR CLI."""
import json
import hashlib
import copy
import os
from contextlib import contextmanager
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def invoke(payload, *, timeout=120):
    completed = subprocess.run(['node', str(ROOT / 'cli.mjs')], input=json.dumps(payload),
                               text=True, capture_output=True, timeout=timeout, check=False)
    if completed.returncode:
        raise ValueError('IR pipeline failed: ' + completed.stderr[:2000])
    return json.loads(completed.stdout)


@contextmanager
def _offline_page():
    from playwright.sync_api import sync_playwright
    executable = os.environ.get('SEMANTIC_IR_CHROMIUM_EXECUTABLE')
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        try:
            context = browser.new_context(java_script_enabled=False, service_workers='block')
            context.route('**/*', lambda route: route.abort())
            yield context.new_page(), browser.version
        finally:
            browser.close()


def parse_documents(documents, *, profile='saved-dom'):
    """Parse complete HTML with browser repair; never execute captured scripts."""
    script = (ROOT / 'dom' / 'parse.mjs').read_text().replace('export function parseDOM', 'function parseDOM')
    parsed = []
    with _offline_page() as (page, browser_version):
        page.evaluate('(() => {\n' + script + '\nglobalThis.__parseIR = parseDOM;\n})()')
        for document in documents:
            result = page.evaluate('x => __parseIR(x.html, x.options)', {
                'html': document['html'], 'options': {'documentId': document['id'],
                    'profile': profile, 'networkIsolated': True,
                    'baseURL': document.get('baseURL') or document.get('url')}})
            result['sourceHash'] = document.get('sourceHash') or hashlib.sha256(document['html'].encode('utf-8')).hexdigest()
            result['metadata']['browserVersion'] = browser_version
            if 'reference_attribute' in document:
                result['metadata']['referenceAttribute'] = document['reference_attribute']
            for field in ('host', 'coordinateSpaces'):
                if field in document:
                    result[field] = copy.deepcopy(document[field])
            if document.get('partial'):
                result['metadata']['partial'] = True
            parsed.append(result)
    return parsed


def pipeline(documents, *, snapshot_id, profile='saved-dom', request=None):
    return invoke({'operation': 'pipeline', 'input': {'snapshotId': snapshot_id,
                   'documents': parse_documents(documents, profile=profile)}, 'request': request or {}})
