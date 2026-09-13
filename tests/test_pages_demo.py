"""Publication tests use synthetic attacks; suspected values are never logged."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_pages_demo import (
    DATA_FILES, PUBLIC_SOURCE, ROOT, STATIC_FILES, build, make_catalog,
    safe_text, safe_url, sanitized_dataset, validate_image, validate_public,
)


def source_fixture():
    dom = {'roots': ['e0'], 'nodes': [
        {'id': 'e0', 'parent': None, 'children': ['e1', 'e2'], 'tag': 'body',
         'text': 'Recipe', 'ownText': '', 'attributes': {}, 'hidden': False},
        {'id': 'e1', 'parent': 'e0', 'children': [], 'tag': 'input',
         'text': 'private entry', 'ownText': 'private entry',
         'attributes': {'value': 'private entry', 'name': 'email', 'type': 'email'}, 'hidden': False},
        {'id': 'e2', 'parent': 'e0', 'children': [], 'tag': 'a',
         'text': 'Ingredients', 'ownText': 'Ingredients', 'attributes': {
             'href': 'https://www.allrecipes.com/recipe/20144/banana-banana-bread/',
             'onclick': 'tracking()', 'data-session': 'private', 'style': 'display:block',
             'aria-label': 'Ingredients'}, 'hidden': False},
    ]}
    tree = {'rootId': 'page', 'nodes': [{'id': 'page', 'kind': 'group', 'label': 'Recipe',
            'summary': 'Ingredients and directions', 'children': [], 'sourceRefs': ['e0'],
            'origin': 'inferred', 'notes': 'unpublished note'}]}
    return {'id': 'allrecipes', 'dom': dom, 'variants': {'baseline': tree, 'revised': copy.deepcopy(tree)},
            'screenshot': {'width': 1280, 'height': 720, 'scrollX': 0, 'scrollY': 0}}


class PublicSanitizationTests(unittest.TestCase):
    def test_attributes_are_allowlisted_and_input_values_removed(self):
        data = sanitized_dataset(source_fixture())
        self.assertEqual(data['dom']['nodes'][1]['ownText'], '')
        self.assertEqual(data['dom']['nodes'][1]['attributes'], {'type': 'email'})
        self.assertEqual(set(data['dom']['nodes'][2]['attributes']), {'href', 'aria-label'})
        self.assertNotIn('notes', data['variants']['baseline']['nodes'][0])
        validate_public(data)

    def test_ids_edges_and_source_references_survive(self):
        source = source_fixture()
        result = sanitized_dataset(source)
        for old, new in zip(source['dom']['nodes'], result['dom']['nodes']):
            for key in ('id', 'parent', 'children'):
                self.assertEqual(old[key], new[key])
        self.assertEqual(result['variants']['revised']['nodes'][0]['sourceRefs'], ['e0'])

    def test_script_text_is_inert_and_private_text_scrubbed(self):
        source = source_fixture()
        source['dom']['nodes'][1]['tag'] = 'script'
        source['dom']['nodes'][2]['ownText'] = 'See /Users/example/private.json or person@example.com'
        source['variants']['baseline']['nodes'][0]['summary'] = 'api_key=' + 'x' * 30
        data = sanitized_dataset(source)
        self.assertEqual(data['dom']['nodes'][1]['text'], '')
        self.assertNotIn('/Users/', json.dumps(data))
        self.assertNotIn('person@', json.dumps(data))
        self.assertEqual(data['variants']['baseline']['nodes'][0]['summary'], '[omitted]')

    def test_private_and_credential_urls_rejected(self):
        urls = ['http://127.0.0.1:8766/index.html', 'https://10.0.0.1/x',
                'https://user:pass@www.allrecipes.com/x', 'file:///home/example/x',
                'https://www.allrecipes.com/x?session=private', 'https://example.com/x',
                'https://www.allrecipes.com/session/private', 'javascript:alert(1)']
        for url in urls:
            self.assertEqual(safe_url(url), '')
        self.assertEqual(safe_url('#ingredients'), '#ingredients')

    def test_credential_shaped_strings_scrubbed_anywhere(self):
        # Construct dummy provider-shaped strings to exercise the scanner without a literal secret.
        text = 'gh' + 'p_' + 'z' * 36
        self.assertEqual(safe_text(text), '[omitted]')
        data = sanitized_dataset(source_fixture())
        data['variants']['revised']['nodes'][0]['label'] = text
        with self.assertRaises(ValueError):
            validate_public(data)

    def test_invalid_mapping_and_unexpected_fields_rejected(self):
        data = sanitized_dataset(source_fixture())
        data['dom']['nodes'][0]['cssPath'] = 'body'
        with self.assertRaises(ValueError):
            validate_public(data)
        data = sanitized_dataset(source_fixture())
        data['variants']['baseline']['nodes'][0]['sourceRefs'] = ['missing']
        with self.assertRaises(AssertionError):
            validate_public(data)


class PagesArtifactTests(unittest.TestCase):
    def test_reviewed_example_is_valid_and_catalog_is_honest(self):
        data = json.loads((PUBLIC_SOURCE / 'allrecipes.json').read_text())
        validate_public(data)
        self.assertEqual(json.loads((PUBLIC_SOURCE / 'catalog.json').read_text()), make_catalog(data))
        self.assertTrue(all('Authored' in item['label'] for item in make_catalog(data)['datasets'][0]['variants']))

    def test_only_explicit_static_files_are_published(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'site'
            names = build(destination)
            expected = set(STATIC_FILES) | {f'data/{name}' for name in DATA_FILES} | {'.nojekyll'}
            self.assertEqual(set(names), expected)
            actual = {str(path.relative_to(destination)) for path in destination.rglob('*') if path.is_file()}
            self.assertEqual(actual, expected)
            self.assertNotIn('compare.html', actual)
            self.assertFalse(any('gov-uk' in name for name in actual))

    def test_nonempty_destination_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            (destination / 'existing').write_text('keep')
            with self.assertRaises(FileExistsError):
                build(destination)
            self.assertEqual((destination / 'existing').read_text(), 'keep')

    def test_image_metadata_rejected(self):
        image = (PUBLIC_SOURCE / 'allrecipes.jpg').read_bytes()
        validate_image(image)
        for marker in (0xE1, 0xED, 0xFE):
            with self.assertRaises(ValueError):
                validate_image(image[:2] + bytes([255, marker, 0, 4]) + b'ab' + image[2:])

    def test_symlink_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            inspector = Path(directory) / 'inspector'
            inspector.mkdir()
            for name in STATIC_FILES:
                (inspector / name).symlink_to(ROOT / 'inspector' / name)
            with self.assertRaises(ValueError):
                build(Path(directory) / 'out', inspector=inspector)


if __name__ == '__main__':
    unittest.main()
