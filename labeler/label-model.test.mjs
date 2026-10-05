import assert from 'node:assert/strict';
import test from 'node:test';
import * as L from './label-model.mjs';

// title; body > header > (nav > a1, a2), logo img; main > h1, p, ul > li1..li3; footer
const spec = [
  ['t', null, 'title', 'Example page'], ['b', null, 'body', ''],
  ['hd', 'b', 'header', ''], ['nav', 'hd', 'nav', ''], ['a1', 'nav', 'a', 'Home'], ['a2', 'nav', 'a', 'Docs'],
  ['logo', 'hd', 'img', ''], ['m', 'b', 'main', ''], ['h1', 'm', 'h1', 'Welcome'], ['p', 'm', 'p', 'Intro text'],
  ['ul', 'm', 'ul', ''], ['li1', 'ul', 'li', 'One'], ['li2', 'ul', 'li', 'Two'], ['li3', 'ul', 'li', 'Three'],
  ['f', 'b', 'footer', 'Copyright'],
];
const node = ([id, parent, tag, ownText]) => ({ id, parent, tag, ownText, attributes: tag === 'img' ? { alt: 'Logo' } : {},
  children: spec.filter(s => s[1] === id).map(s => s[0]) });
const model = { page: 's/p', url: 'https://example.test/', documentSha256: 'abc',
  compact: { roots: ['t', 'b'], nodes: spec.map(node) },
  raw: { roots: ['t', 'b'], nodes: spec.map(s => ({ ...node(s), text: s[3], compact: {}, style: {} })) } };
const ctx = L.pageIndex(model);
const kids = (label, id) => label.nodes[id].children;

test('a new label is rooted at the page title, and the title is never reported uncovered', () => {
  const label = L.newLabel(ctx);
  assert.equal(label.nodes.page.label, 'Example page');
  assert.deepEqual(L.uncovered(label, ctx), ['a1', 'a2', 'logo', 'h1', 'p', 'li1', 'li2', 'li3', 'f']);
});

test('grouping a container makes it one unit that covers its subtree', () => {
  const label = L.newLabel(ctx);
  const g = L.groupCompact(label, ctx, ['hd'], 'page', 'Site header');
  assert.deepEqual(kids(label, g), ['leaf-hd']);
  assert.deepEqual(L.uncovered(label, ctx), ['h1', 'p', 'li1', 'li2', 'li3', 'f']);
});

test('placing a node inside an existing unit splits that unit down to it', () => {
  const label = L.newLabel(ctx);
  const header = L.groupCompact(label, ctx, ['hd'], 'page', 'Site header');
  const nav = L.groupCompact(label, ctx, ['a1'], header, 'Navigation');
  assert.deepEqual(kids(label, header), [nav, 'leaf-a2', 'leaf-logo']);
  assert.deepEqual(kids(label, nav), ['leaf-a1']);
  assert.deepEqual(L.validateLabel(label, ctx).errors, []);
});

test('splitting in place keeps the units inside the same group and order', () => {
  const label = L.newLabel(ctx);
  const header = L.groupCompact(label, ctx, ['hd'], 'page', 'Site header');
  L.addLeaves(label, ctx, ['a2'], header);
  assert.deepEqual(kids(label, header), ['leaf-a1', 'leaf-a2', 'leaf-logo']);
});

test('a container holding placed units is refused, and Make one unit merges them', () => {
  const label = L.newLabel(ctx);
  L.addChildren(label, ctx, ['ul'], 'page');
  assert.deepEqual(kids(label, 'page'), ['leaf-li1', 'leaf-li2', 'leaf-li3']);
  assert.throws(() => L.addLeaves(label, ctx, ['m'], 'page'), /contains nodes already placed/);
  L.makeUnit(label, ctx, 'ul', 'page');
  assert.deepEqual(kids(label, 'page'), ['leaf-ul']);
  assert.equal(label.nodes['leaf-li1'], undefined);
});

test('semantic edits: group, move, indent, outdent, unwrap, merge, remove', () => {
  const label = L.newLabel(ctx);
  L.addLeaves(label, ctx, ['h1', 'p', 'f'], 'page');
  const intro = L.groupNodes(label, ['leaf-h1', 'leaf-p'], 'Intro');
  assert.deepEqual(kids(label, 'page'), [intro, 'leaf-f']);
  L.move(label, ['leaf-f'], -1);
  assert.deepEqual(kids(label, 'page'), ['leaf-f', intro]);
  L.move(label, ['leaf-f'], 1);
  L.indent(label, ['leaf-f']);
  assert.deepEqual(kids(label, intro), ['leaf-h1', 'leaf-p', 'leaf-f']);
  L.outdent(label, ['leaf-f']);
  assert.deepEqual(kids(label, 'page'), [intro, 'leaf-f']);
  const other = L.groupNodes(label, ['leaf-f'], 'Footer');
  L.merge(label, [intro, other]);
  assert.deepEqual(kids(label, intro), ['leaf-h1', 'leaf-p', 'leaf-f']);
  L.unwrap(label, intro);
  assert.deepEqual(kids(label, 'page'), ['leaf-h1', 'leaf-p', 'leaf-f']);
  L.remove(label, ['leaf-p']);
  assert.ok(L.uncovered(label, ctx).includes('p'));
  assert.throws(() => L.groupNodes(label, ['leaf-h1', 'page'], 'x'), /root/);
  assert.throws(() => L.indent(label, ['leaf-h1']), /group just above/);
});

test('split a unit into its children', () => {
  const label = L.newLabel(ctx);
  L.addLeaves(label, ctx, ['ul'], 'page');
  L.splitLeaf(label, ctx, 'leaf-ul');
  assert.deepEqual(kids(label, 'page'), ['leaf-li1', 'leaf-li2', 'leaf-li3']);
  assert.throws(() => L.splitLeaf(label, ctx, 'leaf-li1'), /nothing inside/);
});

test('skip covers a subtree, refuses placed content, and unskips', () => {
  const label = L.newLabel(ctx);
  L.skip(label, ctx, ['hd'], 'site chrome');
  assert.ok(!L.uncovered(label, ctx).includes('a1'));
  assert.throws(() => L.addLeaves(label, ctx, ['a1'], 'page'), /skipped/);
  L.addLeaves(label, ctx, ['f'], 'page');
  assert.throws(() => L.skip(label, ctx, ['b'], 'x'), /overlaps a placed unit/);
  L.unskip(label, ['hd']);
  assert.ok(L.uncovered(label, ctx).includes('a1'));
});

test('validation reports structural errors and coverage warnings', () => {
  const label = L.newLabel(ctx);
  L.addLeaves(label, ctx, ['ul', 'h1'], 'page');
  assert.deepEqual(L.validateLabel(label, ctx).errors, []);
  assert.match(L.validateLabel(label, ctx).warnings.join(' '), /not placed or skipped/);
  label.nodes['leaf-li1'] = { id: 'leaf-li1', kind: 'dom', label: 'One', children: [], sourceRefs: ['li1'] };
  label.nodes.page.children.push('leaf-li1');
  label.nodes.page.children.push('leaf-h1');
  const { errors } = L.validateLabel(label, ctx);
  assert.ok(errors.some(e => /inside another unit/.test(e)));
  assert.ok(errors.some(e => /more than one parent/.test(e)));
});

test('saved form round-trips and exports a banana-bread-shaped dataset', () => {
  const label = L.newLabel(ctx);
  L.groupCompact(label, ctx, ['ul'], 'page', 'List', true);
  L.skip(label, ctx, ['f'], 'legal');
  const saved = L.toSaved(label, ctx, 'draft');
  assert.equal(saved.nodes[0].id, 'page');
  assert.deepEqual(saved.provenance.skipped, { f: 'legal' });
  assert.deepEqual(L.fromSaved(JSON.parse(JSON.stringify(saved))), label);
  const dataset = L.toDataset(model, saved);
  assert.equal(dataset.id, 'label-p');
  assert.deepEqual(Object.keys(dataset.variants), ['gold']);
  assert.ok(dataset.dom.nodes.every(n => !('compact' in n) && !('style' in n)));
});
