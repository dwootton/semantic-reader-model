import test from 'node:test';
import assert from 'node:assert/strict';
import { validateObservation, validateView, observationHash, stableStringify, deepFreeze } from './validate.mjs';
import { modelPacket, encodeModelView, validateModelReferences } from './codec.mjs';

const cover = { children: 'complete', names: 'unknown', actions: 'unknown', relations: 'complete' };
function observation() {
  return { version: 'ui-observation/0.1', snapshotId: 's1', documents: [{ id: 'd0', roots: ['d0:root'], containmentBasis: 'dom' }], roots: ['d0:root'], nodes: {
    'd0:root': { role: 'document', children: ['d0:button', 'd0:help'] },
    'd0:button': { role: 'button', children: [], name: { text: '', basis: 'browser' }, states: { disabled: false }, actions: [{ kind: 'invoke', basis: 'native-semantics' }] },
    'd0:help': { role: 'text', children: [], text: 'Help' },
  }, relations: [{ from: 'd0:button', kind: 'describedBy', targets: [{ node: 'd0:help' }, { unresolved: 'raw-private-id' }], basis: 'native-semantics' }], coverage: cover };
}
function view() {
  const obs = observation();
  return { version: 'ui-view/0.1', snapshotId: obs.snapshotId, observationHash: observationHash(obs), policy: 'organizer-floor/0.1', profile: 'structure', scope: { roots: ['d0:button'], context: ['d0:help'] }, roots: ['d0:button'], contextRoots: ['d0:help'], nodes: {
    'd0:button': { ...obs.nodes['d0:button'], membership: 'owned' },
    'd0:help': { role: 'text', children: [], text: { kind: 'complete', value: 'Help' }, membership: 'context' },
  }, relations: obs.relations, gaps: [], coverage: 'partial' };
}

test('observation preserves unknown, false and observed empty distinctly', () => {
  const obs = observation(); validateObservation(obs);
  assert.equal(obs.nodes['d0:button'].name.text, '');
  assert.equal(obs.nodes['d0:button'].states.disabled, false);
  assert.equal(Object.hasOwn(obs.nodes['d0:help'], 'name'), false);
});
test('rejects missing children, duplicate parents, cycles, unknown fields and invalid scalar types', () => {
  const mutate = fn => { const o = observation(); fn(o); return () => validateObservation(o); };
  assert.throws(mutate(o => o.nodes['d0:root'].children.push('missing')));
  assert.throws(mutate(o => o.nodes['d0:button'].children.push('d0:help')));
  assert.throws(mutate(o => o.nodes['d0:help'].children.push('d0:root')));
  assert.throws(mutate(o => o.nodes['d0:help'].nativeSecret = 'x'));
  assert.throws(mutate(o => o.nodes['d0:button'].states.disabled = 'false'));
  assert.throws(mutate(o => o.relations[0].targets.push({ node: 'missing' })));
});
test('relation cycles are valid while active descendant cardinality is checked', () => {
  const o = observation(); o.relations.push({ from: 'd0:help', kind: 'describedBy', targets: [{ node: 'd0:button' }], basis: 'reported' });
  validateObservation(o); o.relations[0].kind = 'activeDescendant'; assert.throws(() => validateObservation(o));
});
test('view validates explicit gap location and context membership', () => {
  const v = view(); validateView(v);
  v.nodes['d0:button'].children.push({ gap: 'g:middle' });
  v.gaps.push({ id: 'g:middle', owner: 'd0:button', field: 'children', reason: 'budget', expansion: 'local', omittedNodes: 2 });
  validateView(v); v.gaps[0].owner = 'd0:help'; assert.throws(() => validateView(v));
});
test('codec aliases source identity, unresolved keys and destinations; context never assignable', () => {
  const v = view(); v.nodes['d0:button'].destination = { id: 'private-destination', label: 'example.test/invoice' };
  const packet = modelPacket(v);
  assert.equal(packet.text, encodeModelView(v));
  assert.ok(!packet.text.includes('d0:') && !packet.text.includes('raw-private-id') && !packet.text.includes('private-destination'));
  assert.deepEqual(validateModelReferences(packet, ['n0'], { snapshotId: 's1' }), ['d0:button']);
  assert.throws(() => validateModelReferences(packet, ['n1']));
  assert.throws(() => validateModelReferences(packet, ['n0'], { snapshotId: 's2' }));
  const corrupt = structuredClone(packet); corrupt.aliases.nodes.n0 = 'wrong'; assert.throws(() => validateModelReferences(corrupt, ['n0']));
});
test('deterministic hashing ignores object insertion order but preserves child order', () => {
  assert.equal(stableStringify({ b: 2, a: 1 }), stableStringify({ a: 1, b: 2 }));
  const a = observation(), b = structuredClone(a); b.nodes['d0:root'].children.reverse();
  assert.notEqual(observationHash(a), observationHash(b));
  deepFreeze(a); assert.throws(() => a.roots.push('x'));
});
test('deep containment is validated iteratively', () => {
  const o = observation(); o.nodes = {};
  for (let i = 0; i < 12000; i++) o.nodes[`d0:${i}`] = { role: 'generic', children: i < 11999 ? [`d0:${i + 1}`] : [] };
  o.roots = ['d0:0']; o.documents[0].roots = ['d0:0']; o.relations = [];
  validateObservation(o);
});
