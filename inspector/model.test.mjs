import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { indexDataset, ancestors, hierarchyRefs, domToHierarchy, visibleRows, screenshotBounds } from './model.mjs';

const sample = {
  variants: { revised: { rootId: 'page', nodes: [
    { id: 'page', children: ['card'], sourceRefs: ['body'], kind: 'group', label: 'Page' },
    { id: 'card', children: ['price'], sourceRefs: ['a', 'b'], kind: 'group', label: 'Card' },
    { id: 'price', children: [], sourceRefs: ['b', 'c'], kind: 'dom', label: 'Price' },
  ] } },
  dom: { roots: ['body', 'frame'], nodes: [
    { id: 'body', parent: null, children: ['a', 'b', 'c'] },
    { id: 'a', parent: 'body', children: ['span'] },
    { id: 'span', parent: 'a', children: [] },
    { id: 'b', parent: 'body', children: [], rect: { x: -10, y: 5, width: 30, height: 20 } },
    { id: 'c', parent: 'body', children: [], rect: { x: 0, y: 800, width: 10, height: 20 } },
    { id: 'frame', parent: null, children: [] },
  ] },
};
const index = indexDataset(sample, 'revised');

test('group selection includes multiple exact references and optional child references, deduplicated', () => {
  assert.deepEqual([...hierarchyRefs(index, 'card', false)], ['a', 'b']);
  assert.deepEqual([...hierarchyRefs(index, 'card', true)], ['a', 'b', 'c']);
});
test('reverse mapping returns every exact owner and contextual ancestors', () => {
  const result = domToHierarchy(index, 'b');
  assert.deepEqual([...result.exact], ['card', 'price']);
  assert.deepEqual([...result.context], ['page']);
  assert.equal(result.viaAncestor, false);
});
test('unannotated descendants distinguish containment from direct ownership', () => {
  const result = domToHierarchy(index, 'span', false);
  assert.equal(result.viaAncestor, true);
  assert.equal(result.mappedSource, 'a');
  assert.deepEqual([...result.exact], ['card']);
  assert.equal(result.context.size, 0);
});
test('unmapped separate frame does not inherit owners from another document', () => {
  assert.equal(domToHierarchy(index, 'frame').exact.size, 0);
});
test('filter reveals matched nodes and their ancestors without unrelated siblings', () => {
  const rows = visibleRows(index.hierarchy, ['page'], new Set(), 'price', n => n.label);
  assert.deepEqual(rows.map(r => r.node.id), ['page', 'card', 'price']);
  assert.deepEqual(rows.map(r => r.depth), [0, 1, 2]);
});
test('collapsed branches stay collapsed without a search', () => {
  assert.deepEqual(visibleRows(index.hierarchy, ['page'], new Set(['page']), '', n => n.label).map(r => r.node.id), ['page', 'card']);
});
test('screenshot bounds are clipped to the recorded viewport; offscreen references are omitted', () => {
  assert.deepEqual(screenshotBounds(index.dom, new Set(['b', 'c']), { width: 100, height: 100 }), [{ id: 'b', x: 0, y: 5, width: 20, height: 20 }]);
  assert.deepEqual(screenshotBounds(index.dom, new Set(['b']), null), []);
});
test('ancestor walk terminates on corrupt cyclic input', () => {
  assert.deepEqual(ancestors('a', id => id === 'a' ? 'b' : 'a'), ['b']);
});
test('all exported variants resolve every semantic leaf in both mapping directions', { skip: process.env.SEMANTIC_LOCAL_CORPUS_TESTS !== '1'
  ? 'Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original 14-site corpus' : false }, async () => {
  const catalog = JSON.parse(await readFile(new URL('data/catalog.json', import.meta.url)));
  let variants = 0, references = 0;
  for (const entry of catalog.datasets) {
    const data = JSON.parse(await readFile(new URL(`data/${entry.id}.json`, import.meta.url)));
    for (const variant of entry.variants) {
      const idx = indexDataset(data, variant.id); variants++;
      const allRefs = hierarchyRefs(idx, idx.rootId);
      for (const n of idx.hierarchy.values()) for (const ref of n.sourceRefs) {
        assert.ok(allRefs.has(ref), `${entry.id}: unreachable reference ${ref}`);
        assert.ok(domToHierarchy(idx, ref, false).exact.has(n.id)); references++;
      }
    }
  }
  assert.ok(catalog.datasets.length >= 14, 'Original 14-site corpus plus any imported datasets');
  assert.equal(variants, catalog.datasets.reduce((total, entry) => total + entry.variants.length, 0));
  assert.ok(variants >= 27, 'Original corpus variants remain available alongside imported trees');
  assert.ok(references > 7000);
});
