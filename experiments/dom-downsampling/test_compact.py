"""Offline browser tests for bounded, explicitly partial organizer evidence."""
import json
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent


class CompactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch(headless=True)
        cls.context = cls.browser.new_context(service_workers='block')
        cls.context.route('**/*', lambda route: route.abort())
        cls.page = cls.context.new_page()
        cls.page.goto('about:blank')
        cls.page.add_script_tag(path=str(HERE / 'compact.js'))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def compact(self, source, profile='budget', ratio=0.1):
        return json.loads(self.page.evaluate(
            'x=>JSON.stringify(compactDOM(x.source,{profile:x.profile,targetRatio:x.ratio}))',
            {'source': source, 'profile': profile, 'ratio': ratio}))

    def test_strip_payload_and_flatten_without_repeating_text(self):
        source = '<div class="long-class"><div><span><p>Unique prose</p></span></div></div>'
        source += '<script>secret()</script><svg><image href="data:image/png;base64,AAAA"/></svg>'
        result = self.compact(source, 'structure')
        self.assertTrue(result['report']['passed'], result['report'])
        self.assertEqual(result['html'].count('Unique prose'), 1)
        self.assertNotIn('AAAA', result['html'])
        self.assertNotIn('long-class', result['html'])
        self.assertGreater(result['report']['collapsedElements'], 1)
        self.assertEqual(len(result['sourceMap']), result['report']['sourceElements'])

    def test_excerpt_is_explicit_and_expansion_reads_original(self):
        text = 'Some original evidence. ' * 80
        source = '<p>' + text + '</p>'
        result = self.compact(source, 'excerpt')
        self.assertTrue(result['report']['passed'])
        self.assertIn('data-excerpt', result['html'])
        self.assertGreater(result['report']['omittedTextCharacters'], 0)
        ref = next(item['id'] for item in result['sourceMap'] if item['tag'] == 'p')
        expansion = self.page.evaluate('x=>expandCompact(x.source,x.id)', {'source': source, 'id': ref})
        self.assertIn(text, expansion['html'])

    def test_list_sampling_retains_selected_exception(self):
        source = '<select>' + ''.join(
            f'<option {"selected" if i == 12 else ""}>Option {i}</option>' for i in range(20)) + '</select>'
        result = self.compact(source, 'excerpt')
        self.assertTrue(result['report']['passed'], result['report'])
        self.assertIn('Option 12', result['html'])
        self.assertIn('Option 0', result['html'])
        self.assertIn('Option 19', result['html'])
        self.assertIn('data-omitted-items', result['html'])
        self.assertNotIn('Option 8', result['html'])
        self.assertTrue(any(n['disposition'] == 'deferred' for n in result['sourceMap']))

    def test_budget_report_counts_actual_output_and_preserves_heading(self):
        source = '<main><h1>Catalog</h1><ul>' + ''.join(
            f'<li><article><h2>Product {i}</h2><p>Description {i}</p><a href="/p/{i}">View</a></article></li>'
            for i in range(60)) + '</ul></main>'
        result = self.compact(source)
        self.assertTrue(result['report']['passed'], result['report'])
        self.assertFalse(result['report']['budgetMet'], result['report'])
        self.assertGreater(result['report']['nodeRatio'], .1)
        self.assertIn('Catalog', result['html'])
        for i in range(60):
            self.assertIn(f'Product {i}', result['html'])
        self.assertEqual(result['report']['exposedControls'], 60)

    def test_infeasible_budget_is_not_claimed_as_success(self):
        result = self.compact('<h1>Must stay</h1><input required><button>Submit</button>', ratio=.01)
        self.assertFalse(result['report']['budgetMet'])
        self.assertGreater(result['report']['nodeRatio'], .01)
        self.assertIn('Must stay', result['html'])

    def test_namespaces_forms_and_source_marker_collision(self):
        source = '''<main data-r="old"><h1>Form</h1><label for="q">Name</label>
        <input id="q" disabled aria-describedby="help"><p id="help" hidden>Help</p>
        <table><caption>Data</caption><tr><th id="h">Price</th><td headers="h">$2</td></tr></table>
        <math><mi>x</mi></math><pre> a\n b</pre></main>'''
        for profile in ['structure', 'excerpt', 'budget']:
            with self.subTest(profile=profile):
                result = self.compact(source, profile)
                self.assertTrue(result['report']['passed'], result['report'])
                self.assertEqual(result['report']['referenceAttribute'], 'data-r-x')
                self.assertTrue(result['report']['checks']['noDanglingRelations'])

    def test_fold_keeps_checked_control_label_and_description(self):
        source = '<main><h1>Survey</h1><label>Subscribe to news<input type="checkbox" checked aria-describedby="help"></label><p id="help">Email only</p>'
        source += '<section>' + '<p>Other content</p>' * 30 + '</section></main>'
        result = self.compact(source)
        self.assertTrue(result['report']['passed'], result['report'])
        self.assertIn('Subscribe to news', result['html'])
        self.assertIn('Email only', result['html'])
        self.assertNotIn('data-deferred="0"', result['html'])

    def test_form_inventory_survives_budget(self):
        source = '<main><h1>Survey</h1><form><fieldset><legend>Favorite park</legend>'
        source += ''.join(f'<label>Choice {i}<input name="park" type="radio" value="{i}"></label>' for i in range(40))
        source += '</fieldset></form></main>'
        result = self.compact(source)
        self.assertTrue(result['report']['passed'], result['report'])
        inspected = self.page.evaluate("html => { const d=new DOMParser().parseFromString(html,'text/html'); const f=d.querySelector('fieldset'); return {deferred:f?.hasAttribute('data-deferred'),fields:f?.querySelectorAll('input').length}; }", result['html'])
        self.assertEqual(inspected, {'deferred': False, 'fields': 40})
        for i in range(40):
            self.assertIn(f'Choice {i}', result['html'])

    def test_nested_alert_and_label_context_cannot_be_folded(self):
        source = '<main><h1>Page</h1><div role="alert"><section><p>Critical account warning</p></section></div>'
        source += '<label><section><span>Subscribe</span><input checked type="checkbox"></section></label>'
        source += '<section>' + '<p>Other</p>' * 40 + '</section></main>'
        result = self.compact(source)
        self.assertTrue(result['report']['passed'], result['report'])
        self.assertIn('Critical account warning', result['html'])
        self.assertIn('Subscribe', result['html'])

    def test_large_heading_and_pre_are_explicit_excerpts(self):
        result = self.compact('<h1>' + 'word ' * 2000 + '</h1><pre>' + 'code ' * 2000 + '</pre>', 'excerpt')
        self.assertTrue(result['report']['passed'], result['report'])
        self.assertGreaterEqual(result['report']['shortenedTextNodes'], 2)
        self.assertLess(result['report']['outputBytes'], 3000)
        self.assertIn('data-excerpt', result['html'])

    def test_branching_card_boundaries_survive_structure(self):
        source = '<main>' + ''.join(
            f'<div class="card"><h2>Plan {name}</h2><p>${price}</p><button>Choose</button></div>'
            for name, price in [('A', 10), ('B', 20)]) + '</main>'
        result = self.compact(source, 'structure')
        cards = self.page.evaluate("html => { const d=new DOMParser().parseFromString(html,'text/html'); return [...d.querySelectorAll('main > div')].map(e=>e.textContent); }", result['html'])
        self.assertEqual(cards, ['Plan A$10Choose', 'Plan B$20Choose'])
        self.assertTrue(result['report']['passed'], result['report'])

    def test_ordinary_form_inventory_survives_ancestor_fold(self):
        source = '<main><h1>Form</h1><section><form><label for="email">Email address</label><input id="email" type="email" required aria-describedby="help"><p id="help">Use your work email</p><button>Send</button></form></section>' + '<p>Other</p>' * 40 + '</main>'
        result = self.compact(source)
        for text in ['Email address', 'Use your work email', 'Send']:
            self.assertIn(text, result['html'])
        self.assertEqual(result['report']['exposedControls'], 2)
        self.assertIn('aria-describedby="help"', result['html'])
        self.assertIn('required', result['html'])
        self.assertTrue(result['report']['passed'], result['report'])

    def test_aria_heading_and_mixed_state_survive_budget(self):
        source = '<main><div role="heading" aria-level="2">Apply now</div><ul>' + ''.join(
            '<li><input type="checkbox" aria-checked="mixed">Mixed value</li>' if i == 4 else f'<li>Item {i}</li>'
            for i in range(20)) + '</ul>' + '<p>Other</p>' * 30 + '</main>'
        result = self.compact(source)
        self.assertIn('Apply now', result['html'])
        self.assertIn('aria-level="2"', result['html'])
        self.assertIn('aria-checked="mixed"', result['html'])
        self.assertIn('Mixed value', result['html'])
        self.assertTrue(result['report']['passed'], result['report'])

    def test_original_alert_qualification_is_not_excerpted(self):
        warning = 'Background information. ' * 20 + 'Do not submit another payment.'
        source = '<main><h1>Warning</h1><div role="alert">' + warning + '</div>' + '<p>Other</p>' * 30 + '</main>'
        for profile in ['excerpt', 'budget']:
            with self.subTest(profile=profile):
                result = self.compact(source, profile)
                alert = self.page.evaluate("html => new DOMParser().parseFromString(html,'text/html').querySelector('[role=alert]').textContent", result['html'])
                self.assertEqual(alert, warning)
                self.assertTrue(result['report']['checks']['stateContextPreserved'])

    def test_math_and_code_survive_ancestor_fold(self):
        source = '<main><h1>Formula</h1><section><math><mi>x</mi><mo>=</mo><mn>2</mn></math><pre> alpha\n beta</pre></section>' + '<p>Other</p>' * 30 + '</main>'
        result = self.compact(source)
        self.assertIn('<math', result['html'])
        self.assertIn(' alpha\n beta', result['html'])
        self.assertTrue(result['report']['passed'], result['report'])

    def test_preformatted_excerpt_preserves_line_breaks_and_indent(self):
        code = 'if True:\n    print(1)\n' * 100
        result = self.compact('<pre>' + code + '</pre>', 'excerpt')
        text = self.page.evaluate("html => new DOMParser().parseFromString(html,'text/html').querySelector('pre').textContent", result['html'])
        self.assertTrue(text.startswith('if True:\n    print(1)\n'), repr(text))
        self.assertLess(len(text), len(code))
        self.assertIn('data-excerpt', result['html'])

    def test_svg_preserves_title_description_and_visible_text(self):
        result = self.compact('<svg role="img"><title>Revenue</title><desc>Quarterly total by region</desc><text>North: $20</text><text>South: $40</text><path d="M0 0 L10 10"/></svg>', 'structure')
        for text in ['Revenue', 'Quarterly total by region', 'North: $20', 'South: $40']:
            self.assertIn(text, result['html'])
        self.assertNotIn('M0 0 L10 10', result['html'])
        self.assertTrue(result['report']['passed'], result['report'])

    def test_fragment_and_query_destination_relationships_survive(self):
        source = '<a href="#apply">More</a><a href="/search?q=cats">Results</a><a href="/search?q=dogs">Results</a><section id="apply">Apply</section>'
        result = self.compact(source, 'structure')
        values = self.page.evaluate("html => { const d=new DOMParser().parseFromString(html,'text/html'); const a=[...d.querySelectorAll('a')]; return {target:a[0].getAttribute('data-target-ref'),ref:d.querySelector('#apply').getAttribute('data-r'),destinations:a.slice(1).map(e=>e.getAttribute('data-destination-id'))}; }", result['html'])
        self.assertIsNotNone(values['target'])
        self.assertEqual(values['target'], values['ref'])
        self.assertTrue(all(values['destinations']))
        self.assertNotEqual(*values['destinations'])
        self.assertTrue(result['report']['passed'], result['report'])

    def test_partial_idref_retains_existing_endpoint(self):
        result = self.compact('<button aria-labelledby="primary missing">Go</button><span id="primary">Primary</span>', 'structure')
        self.assertIn('aria-labelledby="primary"', result['html'])
        self.assertIn('missing', result['html'])
        self.assertTrue(result['report']['checks']['noDanglingRelations'])

    def test_optgroup_label_and_selected_option_survive_sampling(self):
        source = '<select><optgroup label="Vegetables">' + ''.join(
            f'<option {"selected" if i == 12 else ""}>Choice {i}</option>' for i in range(20)) + '</optgroup></select>'
        result = self.compact(source, 'excerpt')
        self.assertIn('label="Vegetables"', result['html'])
        for text in ['Choice 0', 'Choice 12', 'Choice 19']:
            self.assertIn(text, result['html'])
        self.assertNotIn('Choice 8', result['html'])
        self.assertIn('data-omitted-items', result['html'])
        self.assertTrue(result['report']['passed'], result['report'])

    def test_short_distinct_ingredient_list_stays_complete(self):
        ingredients = ['flour', 'baking soda', 'salt', 'sugar', 'butter', 'eggs', 'bananas']
        source = '<main><h2>Ingredients</h2><ul>' + ''.join(f'<li>{item}</li>' for item in ingredients) + '</ul></main>'
        for profile in ['excerpt', 'budget']:
            with self.subTest(profile=profile):
                result = self.compact(source, profile)
                for ingredient in ingredients:
                    self.assertIn(ingredient, result['html'])
                self.assertNotIn('data-omitted-items', result['html'])
                self.assertTrue(result['report']['passed'], result['report'])

    def test_budget_preserves_svg_text_through_ancestor_folds(self):
        source = '<main><h1>Report</h1><section><svg role="img"><title>Revenue</title><desc>By region</desc><text>North: $20</text><text>South: $40</text><path d="M0 0 L10 10"/></svg></section>'
        source += '<p>' + 'Long unprotected body. ' * 50 + '</p></main>'
        result = self.compact(source)
        self.assertIn('>North: $20</text>', result['html'])
        self.assertIn('>South: $40</text>', result['html'])
        self.assertIn('>By region</desc>', result['html'])
        self.assertNotIn('M0 0 L10 10', result['html'])
        self.assertTrue(result['report']['passed'])

    def test_budget_keeps_sampled_options_without_selected_state(self):
        source = '<main><h1>Options</h1><select><optgroup label="Cities">'
        source += ''.join(f'<option>City {i}</option>' for i in range(20))
        source += '</optgroup></select></main>'
        result = self.compact(source)
        for i in [0, 1, 19]:
            self.assertIn(f'>City {i}</option>', result['html'])
        self.assertNotIn('>City 8</option>', result['html'])
        self.assertIn('label="Cities"', result['html'])
        self.assertTrue(result['report']['passed'])

    def test_percent_encoded_fragment_keeps_target_identity(self):
        result = self.compact('<a href="#part%3Aone">Part one</a><section id="part:one">Text</section>')
        self.assertIn('id="part:one"', result['html'])
        self.assertIn('data-target-ref=', result['html'])
        self.assertTrue(result['report']['passed'])

    def test_nyt_titles_survive_with_parse_stable_output(self):
        source = (HERE.parents[1] / 'runs/compression/compact-10pct/nyt-homepage--nyt.source.html').read_text()
        result = self.compact(source)
        self.assertTrue(result['report']['passed'], result['report']['checks'])
        self.assertIn('The 25 Photos That Changed Fashion Forever', result['html'])
        self.assertTrue(result['report']['checks']['emittedReferenceOrder'])

    def test_invalid_profile_ratio_and_expansion_ref(self):
        for expression in ["compactDOM('',{profile:'bogus'})", "compactDOM('',{targetRatio:0})", "expandCompact('','??')"]:
            with self.subTest(expression=expression):
                result = self.page.evaluate('x=>{try{eval(x);return false;}catch{return true;}}', expression)
                self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
