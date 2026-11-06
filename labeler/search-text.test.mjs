import test from 'node:test';
import assert from 'node:assert/strict';
import { findExact, fold, nodeTexts, score, speakable, words } from './search-text.mjs';

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
  assert.deepEqual(s.hits, [{ word: 'sign', fields: ['href'] }, { word: 'account', fields: ['href'] }]);
  const parents = { 'src-3': 'src-2', 'src-2': 'src-1' };
  const out = fold([{ id: 'src-2', score: 0.6 }, { id: 'src-3', score: 0.8 }, { id: 'src-9', score: 0.7 }], id => parents[id]);
  assert.deepEqual(out.map(r => [r.id, r.best, r.nested.map(n => n.id)]), [['src-2', 0.8, ['src-3']], ['src-9', 0.7, []]]);
});

// A minimal stand-in for a parsed document: elements in document order (their index is the src id).
function fakeDoc(spec) {
  const all = [];
  const make = ([tag, attrs, ...kids], parent) => {
    const el = { nodeType: 1, localName: tag, parentElement: parent, childNodes: [],
      getAttribute: k => attrs[k] ?? null, hasAttribute: k => k in attrs };
    all.push(el);
    el.childNodes = kids.map(k => typeof k === 'string' ? { nodeType: 3, data: k } : make(k, el));
    Object.defineProperty(el, 'textContent', { get: () => el.childNodes.map(c => c.nodeType === 3 ? c.data : c.textContent).join('') });
    return el;
  };
  const html = make(spec, null);
  return { body: html.childNodes.find(c => c.localName === 'body'), querySelectorAll: () => all };
}

test('speakable text reads names, skips hidden parts, and exact matches land on the smallest node holding them', () => {
  // html(0) > head(1) > title(2); body(3) > p(4) > [text, a(5)]; img(6); div(7, aria-hidden) ; span#n(8); button(9)
  const doc = fakeDoc(['html', {}, ['head', {}, ['title', {}, 'T']],
    ['body', {}, ['p', {}, 'Please   sign ', ['a', { href: '/in' }, 'in here']], ['img', { alt: 'Logo' }],
      ['div', { 'aria-hidden': 'true' }, 'secret'], ['span', { id: 'n' }, 'Account'],
      ['button', { 'aria-labelledby': 'n' }, ['svg', {}]]]]);
  const spoken = speakable(doc, new Set());
  assert.equal(spoken.text, 'Please sign in here Logo Account Account');
  assert.deepEqual([...spoken.hidden], ['src-7']);
  const node = (i, tag, parent) => ({ id: `src-${i}`, tag, parent: parent === null ? null : `src-${parent}`, attributes: {}, text: '' });
  const model = {
    raw: { nodes: [node(0, 'html', null), node(1, 'head', 0), node(2, 'title', 1), node(3, 'body', 0), node(4, 'p', 3),
      node(5, 'a', 4), node(6, 'img', 3), node(7, 'div', 3), node(8, 'span', 3), node(9, 'button', 3), node('a', 'svg', 9)] },
    compact: { nodes: ['3', '4', '5', '6', '8', '9'].map(i => ({ id: `src-${i}` })) },
  };
  assert.deepEqual(findExact('SIGN in', spoken, model).map(h => [h.id, h.count]), [['src-4', 1]]);  // spans p text + link
  assert.deepEqual(findExact('in here', spoken, model).map(h => h.id), ['src-5']);
  assert.deepEqual(findExact('account', spoken, model).map(h => [h.id, h.count]), [['src-8', 1], ['src-9', 1]]);
  assert.deepEqual(findExact('secret', spoken, model), []);
});
