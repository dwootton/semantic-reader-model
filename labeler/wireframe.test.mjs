import assert from 'node:assert/strict';
import test from 'node:test';
import { boxes, hitTest, rectSelect, textLines } from './wireframe.mjs';

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

test('text is split across its rendered lines by character count, in position order', () => {
  const page = { raw: { nodes: [
    { id: 'p', ownText: 'Client Libraries and more', style: { fontSize: 14, bold: false },
      textBoxes: [{ x: 5, y: 40, width: 60, height: 16, length: 8 }, { x: 80, y: 20, width: 120, height: 16, length: 17 },
        { x: 0, y: 20, width: 3, height: 16, length: 1 }] },
    { id: 'a', ownText: 'Docs', style: { fontSize: 13, bold: true }, textBoxes: [{ x: 1, y: 2, width: 30, height: 15, length: 4 }] },
    { id: 'none', ownText: 'No geometry' },
    { id: 'faded', ownText: 'Hidden title', invisible: true, textBoxes: [{ x: 0, y: 0, width: 50, height: 10, length: 12 }] }] } };
  const lines = textLines(page);
  assert.deepEqual(lines.map(l => [l.x, l.text]), [[80, 'Client Libraries'], [5, 'and more'], [1, 'Docs']]);
  assert.equal(lines[2].bold, true);
});
