"""Audit saved HTML with Chromium; never navigate to or execute captured pages."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    fixtures = {
        'semantics': '''<!doctype html><html lang="en"><head><title>Test</title></head><body>
        <main><h1>Heading</h1><p>Some <em>mixed</em> text &amp; entities.</p>
        <ul><li>Repeated</li><li>Repeated</li></ul><table><caption>Data</caption>
        <thead><tr><th id="col">Name</th></tr></thead><tbody><tr><td headers="col">Ada</td></tr></tbody></table>
        <form><label for="q">Query</label><input id="q" required value="hello" aria-describedby="help">
        <p id="help" hidden>Instructions</p><button disabled>Submit</button>
        <select><option selected>A</option><option>B</option></select><textarea>  exact\n text</textarea></form>
        <details><summary>More</summary><p>Collapsed content</p></details><div role="button" tabindex="0">Custom</div>
        <pre>  a\n b</pre><div style="display:none">Hidden</div><a href="#col">Column</a>
        <svg viewBox="0 0 10 10"><title>Icon</title><path d="M0 0L1 1"/></svg>
        <math><mi>x</mi></math><template><p>Template text</p><script>bad()</script></template>
        <script>bad()</script><style>body{display:none}</style><!-- comment --></main></body></html>''',
        'wrappers': '<div id="root"><div><div><div>Keep all text</div></div></div></div>',
        'identity': '<div><div id="anchor"><div>Anchor</div></div><div role="group"><div>Group</div></div></div>',
        'malformed': '<table><td>Cell</table><p>one<p>two<ul><li>a<li>b',
    }
    reports = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(service_workers='block')
        context.route('**/*', lambda route: route.abort())
        page = context.new_page()
        page.add_script_tag(path=str(HERE / 'downsample.js'))
        for name, source in fixtures.items():
            for unwrap in (False, True):
                result = page.evaluate('(x) => downsampleHTML(x.source, {unwrap:x.unwrap, targetBytes:1})',
                                       {'source': source, 'unwrap': unwrap})
                assert result['report']['overBudget']
                assert result['report']['textRetention'] == 1
                if name == 'wrappers':
                    assert result['report']['removed']['wrappers'] == (2 if unwrap else 0)
                if name == 'identity':
                    assert result['report']['removed']['wrappers'] == 0
                reports.append({'fixture': name, **result['report']})
        out = HERE / 'output'
        out.mkdir(exist_ok=True)
        for source_path in sorted((ROOT / 'examples/vision-study/captures').glob('*/page.html')):
            result = page.evaluate('(source) => downsampleHTML(source)', source_path.read_text())
            name = source_path.parent.name
            (out / f'{name}.html').write_text(result['html'])
            reports.append({'capture': name, **result['report']})
        browser.close()
    (HERE / 'report.json').write_text(json.dumps(reports, indent=2) + '\n')
    for item in reports:
        print(item.get('capture', item.get('fixture')), item['profile'],
              f"{item['byteReduction']:.1%} byte reduction", item['checks'])


if __name__ == '__main__':
    main()
