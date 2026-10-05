import assert from 'node:assert/strict';
import test from 'node:test';
import { boxes, hitTest, rectSelect } from './wireframe.mjs';

const rect = (x, y, width, height) => ({ x, y, width, height });
const model = {
  compact: { nodes: [{ id: 'card', tag: 'div', ownText: '' }, { id: 'title', tag: 'h3', ownText: 'Title' },
    { id: 'link', tag: 'a', ownText: 'More' }, { id: 'hidden', tag: 'div', ownText: '' }, { id: 'other', tag: 'p', ownText: 'x' }] },
  raw: { nodes: [{ id: 'card', rect: rect(0, 0, 200, 100) }, { id: 'title', rect: rect(10, 10, 100, 20) },
    { id: 'link', rect: rect(10, 60, 50, 20) }, { id: 'hidden', rect: rect(0, 0, 0, 0) }, { id: 'other', rect: rect(300, 0, 50, 50) }] },
};
const parent = { title: 'card', link: 'card' };
const list = boxes(model);

test('zero-size elements are not drawn', () => {
  assert.deepEqual(list.map(b => b.id), ['card', 'title', 'link', 'other']);
});

test('a rectangle around a card selects the card, not its parts', () => {
  assert.deepEqual(rectSelect(list, rect(-5, -5, 220, 120), id => parent[id]), ['card']);
  assert.deepEqual(rectSelect(list, rect(5, 5, 120, 30), id => parent[id]), ['title']);
  assert.deepEqual(rectSelect(list, rect(0, 0, 400, 120), id => parent[id]), ['card', 'other']);
});

test('a click picks the smallest box under the pointer', () => {
  assert.equal(hitTest(list, 20, 15), 'title');
  assert.equal(hitTest(list, 150, 50), 'card');
  assert.equal(hitTest(list, 600, 600), null);
});
