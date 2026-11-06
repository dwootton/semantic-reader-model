import test from 'node:test';
import assert from 'node:assert/strict';
import { fold, nodeTexts, score, words } from './search-text.mjs';

const model = {
  compact: { nodes: [
    { id: 'src-1', tag: 'body', parent: null, ownText: '', children: ['src-2', 'src-4'] },
    { id: 'src-2', tag: 'nav', parent: 'src-1', ownText: '', children: ['src-3', 'src-5'] },
    { id: 'src-3', tag: 'a', parent: 'src-2', ownText: '', children: [] },
    { id: 'src-5', tag: 'a', parent: 'src-2', ownText: 'Docs', children: [] },
    { id: 'src-4', tag: 'div', parent: 'src-1', ownText: '', children: [] },
  ] },
  raw: { nodes: [
    { id: 'src-2', attributes: {}, text: 'AccountDocs' },
    { id: 'src-3', attributes: { href: 'https://x.org/account/signIn?next=/', class: 'navBtn', 'aria-label': 'Account' }, text: '' },
    { id: 'src-4', attributes: {}, text: '' },
  ] },
};

test('words splits camelCase, paths and punctuation', () => {
  assert.equal(words('nav__signIn /a-b'), 'nav sign in a b');
});

test('node text has kind, label, href words, class words and landmark; empty nodes are skipped', () => {
  const texts = nodeTexts(model);
  assert.deepEqual(texts.map(t => t.id), ['src-2', 'src-3', 'src-5']);
  assert.equal(texts[1].text, 'link Account (account sign in next) [nav btn] in navigation');
  assert.equal(texts[0].text, 'navigation Docs');
  assert.equal(texts[1].open, '<a href="https://x.org/account/signIn?next=/" class="navBtn" aria-label="Account">');
});

test('score adds the literal boost and fold nests results under result ancestors', () => {
  const node = nodeTexts(model)[1];
  const s = score('sign in to account', [1, 0], node, [0.5, 0]);
  assert.ok(Math.abs(s.score - (0.5 + 0.1 * 2 / 2)) < 1e-9);
  assert.deepEqual(s.hits, [{ word: 'sign', fields: ['href'] }, { word: 'account', fields: ['label', 'href'] }]);
  const parents = { 'src-3': 'src-2', 'src-2': 'src-1' };
  const out = fold([{ id: 'src-2', score: 0.6 }, { id: 'src-3', score: 0.8 }, { id: 'src-9', score: 0.7 }], id => parents[id]);
  assert.deepEqual(out.map(r => [r.id, r.best, r.nested.map(n => n.id)]), [['src-2', 0.8, ['src-3']], ['src-9', 0.7, []]]);
});
