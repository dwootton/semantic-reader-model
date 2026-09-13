"""Browser checks against the loopback comparison page, with inert saved data."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8768/compression.html'
QA = ROOT / 'qa/compression'


def main():
    if os.environ.get("SEMANTIC_LOCAL_CORPUS_TESTS") != "1":
        print("SKIP: set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original compression artifacts and running server")
        return
    from playwright.sync_api import expect, sync_playwright

    QA.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((ROOT / 'data/compression/catalog.json').read_text())['documents']
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1080})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(URL)
        expect(page.locator('#document-title')).to_have_text('NASA')
        assert page.locator('#documents button').count() == 15
        page.screenshot(path=str(QA / 'desktop-initial.png'), full_page=True)
        for entry in catalog:
            page.get_by_role('button', name=entry['label'], exact=False).first.click()
            expect(page.locator('#document-title')).to_have_text(entry['label'])
            page.locator('#compressed-tree [role=treeitem]').first.wait_for()
            data = json.loads((ROOT / 'data/compression' / entry['file']).read_text())
            rows = data['profiles']['budget']['tree']['nodes']
            chosen = next(n for n in reversed(rows) if n.get('sourceId') and n.get('text') and n['tag'] not in ('script','style'))
            sid, cid = chosen['sourceId'], chosen['id']
            page.locator('#source-search').fill('no_such_text_in_snapshot_981')
            page.locator('#compressed-search').fill(sid)
            row = page.locator(f'#compressed-tree [data-node-id="{cid}"]')
            row.wait_for()
            row.click()
            assert page.locator('#source-search').input_value() == ''
            assert page.locator(f'#source-tree [data-node-id="{sid}"]').get_attribute('aria-selected') == 'true'
            page.locator('#compressed-search').fill('no_such_text_in_snapshot_981')
            page.locator('#source-search').fill(sid)
            full = page.locator(f'#source-tree [data-node-id="{sid}"]')
            full.wait_for()
            full.click()
            assert page.locator('#compressed-search').input_value() == ''
            assert page.locator(f'#compressed-tree [data-node-id="{cid}"]').get_attribute('aria-selected') == 'true'
            assert page.locator('#match-badge').inner_text() == 'Exact source link'
            results.append({'document': entry['id'], 'bidirectional': True})
        page.goto(URL + '?doc=nasa--page&profile=budget')
        expect(page.locator('#document-title')).to_have_text('NASA')
        data = json.loads((ROOT / 'data/compression/nasa--page.json').read_text())
        profile = data['profiles']['budget']
        retained = {n.get('sourceId') for n in profile['tree']['nodes']}
        omitted = next(n for n in profile['sourceMap'] if n['disposition']=='deferred' and n['representedBy'] in retained)
        page.locator('#source-search').fill(omitted['id'])
        page.locator(f'#source-tree [data-node-id="{omitted["id"]}"]').click()
        assert page.locator('#match-badge').inner_text() == 'Representative · not exact'
        assert page.locator('#compressed-tree .representative').count() == 1
        page.screenshot(path=str(QA / 'desktop-omission.png'), full_page=True)
        excluded = next(n for n in profile['sourceMap'] if n['disposition']=='excluded')
        page.locator('#source-search').fill(excluded['id'])
        page.locator(f'#source-tree [data-node-id="{excluded["id"]}"]').click()
        assert page.locator('#match-badge').inner_text() == 'No counterpart'
        assert page.locator('#compressed-tree [aria-selected=true]').count() == 0
        page.locator('#profile').select_option('excerpt')
        expect(page.locator('#profile')).to_have_value('excerpt')
        page.locator('#source-search').fill('unlikely_search_string_87371')
        expect(page.locator('#source-tree')).to_contain_text('No nodes match')
        page.goto(URL + '?doc=nyt-homepage--nyt&profile=structure')
        expect(page.locator('#document-title')).to_have_text('New York Times')
        assert page.locator('#warning').is_visible()
        page.goto(URL + '?doc=nasa--page&profile=budget')
        expect(page.locator('#document-title')).to_have_text('NASA')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(QA / 'mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert not errors, errors
        browser.close()
    (QA / 'verification.json').write_text(json.dumps({'documents': results, 'omission': True, 'absent': True,
        'emptySearch': True, 'profileSwitch': True, 'auditWarning': True, 'mobileNoOverflow': True,
        'pageErrors': errors}, indent=2)+'\n')
    print('15 bidirectional document checks plus omission, absence, search, profile, warning and mobile checks passed.')


if __name__ == '__main__':
    main()
