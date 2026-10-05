import assert from 'node:assert/strict';
import test from 'node:test';
import { buildPage, collectorIds, compactFor } from './corpus.mjs';

// html(0) > head(1) > script(2); html > body(3) > div(4, collapsed into body) > a(5)
const el = (index, tag, parent, children, text = '') =>
  ({ index, tag, parent, children, attributes: {}, ownText: text, text, textTruncated: false, hidden: false });
const elements = [el(0, 'html', null, [1, 3]), el(1, 'head', 0, [2]), el(2, 'script', 1, []),
  el(3, 'body', 0, [4]), el(4, 'div', 3, [5]), el(5, 'a', 4, [], 'Home')];
const entry = (id, tag, parent, disposition = 'retained', representedBy = id) => ({ id, tag, parent, disposition, representedBy });
const sourceMap = [entry('0', 'html', null), entry('1', 'head', '0'), entry('2', 'script', '1', 'removed', null),
  entry('3', 'body', '0'), entry('4', 'div', '3', 'collapsed', '3'), entry('5', 'a', '4')];
const compact = [{ ref: '0', tag: 'html', parentRef: null, ownText: '', attributes: {} },
  { ref: '1', tag: 'head', parentRef: '0', ownText: '', attributes: {} },
  { ref: '3', tag: 'body', parentRef: '0', ownText: '', attributes: {} },
  { ref: '5', tag: 'a', parentRef: '3', ownText: 'Home', attributes: { 'data-destination': 'x/' } }];
const geometry = { elements_and_text: [{ dom_id: 'n5', bounds: [1, 2, 30, 10] }, { dom_id: 'n6', bounds: [0, 0, 5, 5] }] };
const input = () => ({ page: 's/p', capture: { final_url: 'https://x/', record: { category: 'C' } },
  environment: { viewport: { width: 1365, height: 900 } }, elements, sourceMap, geometry, compact });

test('collector ids put excluded tags last', () => {
  const ids = collectorIds(elements);
  assert.equal(ids.get('n1'), 0);
  assert.equal(ids.get('n5'), 5);
  assert.equal(ids.get('n6'), 2); // script
});

test('raw and compact trees share IDs and geometry lands on the right element', () => {
  const page = buildPage(input());
  const raw = new Map(page.raw.nodes.map(n => [n.id, n]));
  assert.deepEqual(page.raw.roots, ['src-0']);
  assert.deepEqual(raw.get('src-5').rect, { x: 1, y: 2, width: 30, height: 10 });
  assert.deepEqual(raw.get('src-2').rect, { x: 0, y: 0, width: 5, height: 5 });
  assert.deepEqual(raw.get('src-4').compact, { disposition: 'collapsed', representedBy: 'src-3' });
  const compactById = new Map(page.compact.nodes.map(n => [n.id, n]));
  assert.deepEqual(compactById.get('src-3').children, ['src-5']);
  assert.deepEqual(page.stats, { elements: 6, compactNodes: 4, geometry: 2, missingRetained: 0 });
  const withoutLink = buildPage({ ...input(), compact: compact.slice(0, 3) });
  assert.equal(withoutLink.stats.missingRetained, 1);
});

test('compactFor resolves exact, represented and ancestor matches', () => {
  const page = buildPage(input());
  const raw = new Map(page.raw.nodes.map(n => [n.id, n]));
  const compactById = new Map(page.compact.nodes.map(n => [n.id, n]));
  assert.equal(compactFor('src-5', raw, compactById), 'src-5');
  assert.equal(compactFor('src-4', raw, compactById), 'src-3');
  assert.equal(compactFor('src-2', raw, compactById), 'src-1');
});

test('rejects a parse that disagrees with the source map', () => {
  const wrongTag = { ...input(), elements: elements.map(e => e.index === 4 ? { ...e, tag: 'span' } : e) };
  assert.throws(() => buildPage(wrongTag), /diverges .* element 4/);
  assert.throws(() => buildPage({ ...input(), elements: elements.slice(0, 5) }), /element count/);
});

test('rejects compact elements that are not retained', () => {
  const bad = [...compact, { ref: '4', tag: 'div', parentRef: '3', ownText: '', attributes: {} }];
  assert.throws(() => buildPage({ ...input(), compact: bad }), /collapsed in the source map/);
});
