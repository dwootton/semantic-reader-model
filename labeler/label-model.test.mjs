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

test('drops place units and nodes exactly where they land', () => {
  const label = L.newLabel(ctx);
  L.addLeaves(label, ctx, ['h1', 'p'], 'page');
  L.addLeaves(label, ctx, ['f'], 'page', 'leaf-h1');
  assert.deepEqual(kids(label, 'page'), ['leaf-f', 'leaf-h1', 'leaf-p'], 'before a sibling, not in document order');
  L.addLeaves(label, ctx, ['f'], 'page', null);
  assert.deepEqual(kids(label, 'page'), ['leaf-h1', 'leaf-p', 'leaf-f'], 'null appends; an existing unit moves');
  const g = L.groupNodes(label, ['leaf-p'], 'G');
  L.moveTo(label, ['leaf-f', 'leaf-h1'], g, 'leaf-p');
  assert.deepEqual(kids(label, g), ['leaf-h1', 'leaf-f', 'leaf-p'], 'kept in tree order, before the drop target');
  L.moveTo(label, ['leaf-h1', 'leaf-f'], g, 'leaf-f');
  assert.deepEqual(kids(label, g), ['leaf-h1', 'leaf-f', 'leaf-p'], 'dropping onto the moved block leaves it in place');
  assert.throws(() => L.moveTo(label, [g], g), /into itself/);
  L.addLeaves(label, ctx, ['li2'], g, 'leaf-p');
  assert.deepEqual(kids(label, g), ['leaf-h1', 'leaf-f', 'leaf-li2', 'leaf-p']);
});

test('skip all skips unplaced content but never covers a placed unit', () => {
  const label = L.newLabel(ctx);
  L.addLeaves(label, ctx, ['a1'], 'page');
  const left = L.skipUncovered(label, ctx, 'not content');
  assert.equal(left, 0);
  assert.ok(!('nav' in label.skipped) && !('hd' in label.skipped), 'containers of the placed link are not skipped');
  assert.ok('a2' in label.skipped && 'logo' in label.skipped && 'ul' in label.skipped === false);
  assert.deepEqual(L.validateLabel(label, ctx).errors, []);
});

test('select siblings and similar siblings, then one group per card', () => {
  // body > list > (card, card, ad); card = h3 + a; ad = div with text
  const cards = [['t', null, 'title', 'T'], ['b', null, 'body', ''], ['list', 'b', 'div', ''],
    ['c1', 'list', 'article', ''], ['c1h', 'c1', 'h3', 'First'], ['c1a', 'c1', 'a', 'Read'],
    ['c2', 'list', 'article', ''], ['c2h', 'c2', 'h3', 'Second'], ['c2a', 'c2', 'a', 'Read'],
    ['ad', 'list', 'div', 'Sponsored']];
  const mk = ([id, parent, tag, ownText]) => ({ id, parent, tag, ownText, attributes: {}, children: cards.filter(s => s[1] === id).map(s => s[0]) });
  const m = { page: 's/q', url: 'u', compact: { roots: ['t', 'b'], nodes: cards.map(mk) }, raw: { roots: ['t', 'b'], nodes: cards.map(s => ({ ...mk(s), text: s[3] })) } };
  const c = L.pageIndex(m);
  assert.deepEqual(L.selectSiblings(c, ['c1']), ['c1', 'c2', 'ad']);
  assert.deepEqual(L.selectSimilar(c, ['c1']).ids, ['c1', 'c2']);
  const label = L.newLabel(c);
  const groups = L.groupEach(label, c, L.selectSimilar(c, ['c2']).ids, 'page');
  assert.deepEqual(groups.map(g => label.nodes[g].label), ['First', 'Second']);
  assert.deepEqual(label.nodes[groups[0]].children, ['leaf-c1h', 'leaf-c1a']);
  assert.deepEqual(label.nodes.page.children, groups);
  const solo = L.groupEach(label, c, ['ad'], 'page');
  assert.deepEqual(label.nodes[solo[0]].children, ['leaf-ad'], 'a node without children becomes its own unit');
});

test('select similar widens from siblings to cousins along the same tag path', () => {
  // body > (div#d1 > p > strong, strong ; p > strong ; ul > li > strong), div#d2 > p > strong
  const spec2 = [['t', null, 'title', 'T'], ['b', null, 'body', ''],
    ['d1', 'b', 'div', ''], ['p1', 'd1', 'p', ''], ['s1', 'p1', 'strong', 'A'], ['s2', 'p1', 'strong', 'B'],
    ['p2', 'd1', 'p', ''], ['s3', 'p2', 'strong', 'C'], ['u', 'd1', 'ul', ''], ['li', 'u', 'li', ''], ['s4', 'li', 'strong', 'D'],
    ['d2', 'b', 'div', ''], ['p3', 'd2', 'p', ''], ['s5', 'p3', 'strong', 'E']];
  const mk = ([id, parent, tag, ownText]) => ({ id, parent, tag, ownText, attributes: {}, children: spec2.filter(s => s[1] === id).map(s => s[0]) });
  const m = { page: 's/r', url: 'u', compact: { roots: ['t', 'b'], nodes: spec2.map(mk) }, raw: { roots: ['t', 'b'], nodes: spec2.map(s => ({ ...mk(s), text: s[3] })) } };
  const c = L.pageIndex(m);
  assert.deepEqual(L.selectSimilar(c, ['s1'], 1), { ids: ['s1', 's2'], scopes: ['p1'], level: 1 });
  assert.deepEqual(L.selectSimilar(c, ['s1'], 2), { ids: ['s1', 's2', 's3'], scopes: ['d1'], level: 2 }, 'cousins in other <p>s, not the <li>');
  assert.deepEqual(L.selectSimilar(c, ['s1'], 3).ids, ['s1', 's2', 's3', 's5'], 'second cousins in the next div');
  assert.equal(L.selectSimilar(c, ['s1'], 9).level, 4, 'stops at the page root');
});
