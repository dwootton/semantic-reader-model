import test from 'node:test';
import assert from 'node:assert/strict';
import { createNarrator, describeNode } from './narration.mjs';

test('narration is opt-in, interrupts queued speech, and stops immediately when disabled', () => {
  const calls = [];
  const narrator = createNarrator({cancel: () => calls.push('cancel'), speak: u => calls.push(u.text)}, class {constructor(text) {this.text = text;}});
  narrator.speak('silent');
  assert.deepEqual(calls, []);
  narrator.setEnabled(true);
  narrator.speak('first'); narrator.speak('next'); narrator.setEnabled(false); narrator.speak('silent');
  assert.deepEqual(calls, ['cancel', 'first', 'cancel', 'next', 'cancel']);
});
test('unsupported speech remains safe and unavailable', () => {
  const narrator = createNarrator(undefined, undefined);
  assert.equal(narrator.supported, false);
  narrator.setEnabled(true); narrator.speak('silent'); narrator.stop();
});
test('narration reads current node and expansion state without descendant text', () => {
  const item = {node: {id:'e1', tag:'div', children:['e2'], text:'Entire page'}, depth:2, hasChildren:true, open:false};
  assert.equal(describeNode(item, 'dom'), 'e1. div. level 3. collapsed');
  item.node.attributes = {'aria-label':'Ingredients', role:'region'};
  assert.equal(describeNode(item, 'raw'), 'Ingredients. region. level 3. collapsed');
  item.node = {label:'Recipe', kind:'group'}; item.open = true;
  assert.equal(describeNode(item, 'semantic'), 'Recipe. group. level 3. expanded');
});
