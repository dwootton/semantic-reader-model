import test from 'node:test';
import assert from 'node:assert/strict';
import { navigationPacket, validateNavigationReferences } from './navigation.mjs';
import { modelPacket } from './codec.mjs';
import { compactIR } from './compact.mjs';
import { deepFreeze, observationHash } from './validate.mjs';

function fixture() {
  const nodes = {
    root: { role: 'document', children: [{ node: 'button' }, { node: 'hidden' }, { node: 'space' }, { node: 'code' }] },
    button: { role: 'button', children: [], name: { text: 'Pay', basis: 'explicit' }, states: { disabled: false }, actions: [{ kind: 'invoke', basis: 'native-semantics' }] },
    hidden: { role: 'group', children: [{ node: 'help' }, { node: 'inactive' }], exposure: { accessibilityIncluded: false } },
    help: { role: 'text', children: [], text: { kind: 'complete', value: 'Card help' } },
    inactive: { role: 'button', children: [], exposure: { accessibilityIncluded: true }, name: { text: 'Inactive', basis: 'explicit' } },
    space: { role: 'text', children: [], text: { kind: 'complete', value: '\n  ' } },
    code: { role: 'code', children: [{ node: 'codeSpace' }] },
    codeSpace: { role: 'text', children: [], text: { kind: 'complete', value: '  \n' } },
  };
  for (const n of Object.values(nodes)) n.membership = 'owned';
  return { version: 'ui-view/0.1', snapshotId: 'snapshot', observationHash: observationHash({ fixture: true }), policy: 'organizer-floor/0.1', profile: 'structure', scope: { roots: ['root'], context: [] }, roots: ['root'], contextRoots: [], nodes, relations: [{ from: 'button', kind: 'describedBy', targets: [{ node: 'help' }], basis: 'native-semantics' }], gaps: [], coverage: 'complete' };
}
const alias = (p, source) => Object.keys(p.aliases.nodes).find(id => p.aliases.nodes[id] === source);
const projected = p => new Map(JSON.parse(p.text).nodes.map(n => [p.aliases.nodes[n[0]], n]));
function boundObservation(v) {
  const nodes = {};
  for (const [id, node] of Object.entries(v.nodes)) {
    const { membership, ...n } = structuredClone(node);
    n.children = n.children.map(c => c.node);
    if (n.text) n.text = n.text.value;
    nodes[id] = n;
  }
  const roots = [...v.roots, ...v.contextRoots];
  const obs = { version: 'ui-observation/0.1', snapshotId: v.snapshotId, roots, documents: [{ id: 'd', roots, containmentBasis: 'synthetic' }], nodes, relations: v.relations,
    coverage: { children: 'complete', names: 'unknown', actions: 'unknown', relations: 'complete' } };
  v.observationHash = observationHash(obs);
  return obs;
}

test('projection is deterministic, immutable and uses the original aliases and source bindings', () => {
  const v = deepFreeze(fixture());
  const original = JSON.stringify(v);
  const p = navigationPacket(v);
  assert.deepEqual(p, navigationPacket(v));
  assert.equal(JSON.stringify(v), original);
  assert.deepEqual(p.aliases, modelPacket(v).aliases);
  assert.equal(p.viewHash, observationHash(v));
  assert.deepEqual(validateNavigationReferences(p, [alias(p, 'button')], { viewHash: observationHash(v) }), ['button']);
});

test('inherited hidden state cannot be undone by a child; hidden relationship text remains context', () => {
  const p = navigationPacket(fixture()), nodes = projected(p);
  assert.ok(!nodes.has('hidden'));
  assert.ok(!nodes.has('inactive'));
  assert.equal(nodes.get('help')[3].t, 'Card help');
  assert.equal(nodes.get('help')[3].ctx, true);
  assert.throws(() => validateNavigationReferences(p, [alias(p, 'help')]));
  assert.throws(() => validateNavigationReferences(p, [alias(p, 'inactive')]));
  const relation = JSON.parse(p.text).relations[0];
  assert.deepEqual(relation.slice(0, 3), [alias(p, 'button'), 'describedBy', [alias(p, 'help')]]);
});

test('all explicit inactive exposure flags exclude descendants', () => {
  for (const exposure of [{ rendered: false }, { accessibilityIncluded: false }, { inert: true }, { dormant: true }]) {
    const v = fixture(); v.nodes.hidden.exposure = exposure;
    const p = navigationPacket(v);
    assert.ok(!p.eligibleSourceIds.includes('inactive'));
    assert.ok(!p.eligibleSourceIds.includes('help'));
  }
});

test('unknown visibility is retained as unknown, and false states remain false', () => {
  const p = navigationPacket(fixture());
  const n = projected(p).get('button');
  assert.ok(p.eligibleSourceIds.includes('button'));
  assert.equal(n[3].s.disabled, false);
  assert.ok(!Object.hasOwn(n[3], 'e'));
  assert.match(JSON.parse(p.text).legend.exposure, /Missing visibility is unknown/);
});

test('only non-reading whitespace leaves are omitted; code whitespace stays exact', () => {
  const p = navigationPacket(fixture()), nodes = projected(p);
  assert.ok(!nodes.has('space'));
  assert.equal(nodes.get('codeSpace')[3].t, '  \n');
  const v = fixture(); v.nodes.space.text.value = ' words  remain ';
  assert.equal(projected(navigationPacket(v)).get('space')[3].t, ' words  remain ');
});

test('partial text, child and relation gaps, values and unresolved endpoints survive', () => {
  const v = fixture();
  v.nodes.button.text = { kind: 'extract', parts: [{ text: 'Pay' }, { gap: 'text-gap' }] };
  v.nodes.button.children.push({ gap: 'children-gap' });
  v.nodes.button.value = { kind: 'number', current: 0, min: 0, max: 100 };
  v.gaps.push({ id: 'text-gap', owner: 'button', field: 'text', reason: 'budget', expansion: 'local', omittedCharacters: 20 },
    { id: 'children-gap', owner: 'button', field: 'children', reason: 'budget', expansion: 'local', omittedNodes: 3 },
    { id: 'relation-gap', owner: 'button', field: 'relation', reason: 'budget', expansion: 'unavailable' });
  v.relations[0].targets.push({ gap: 'relation-gap' }, { unresolved: 'not-captured' });
  const p = navigationPacket(v), model = JSON.parse(p.text), n = projected(p).get('button');
  assert.equal(n[3].v.current, 0);
  assert.ok(n[3].t[1].gap.startsWith('g'));
  assert.equal(model.gaps.length, 3);
  assert.equal(model.relations[0][2].length, 3);
  assert.match(model.relations[0][2][2], /^u/);
});

test('context stays unassignable even without known hidden exposure', () => {
  const v = fixture();
  v.nodes.root.children = v.nodes.root.children.filter(c => c.node !== 'code');
  v.contextRoots.push('code'); v.scope.context.push('code', 'codeSpace');
  v.nodes.code.membership = 'context'; v.nodes.codeSpace.membership = 'context';
  const p = navigationPacket(v, boundObservation(v));
  assert.throws(() => validateNavigationReferences(p, [alias(p, 'code')]));
});

test('reference validation rejects unknown, duplicates, stale bindings and packet corruption', () => {
  const p = navigationPacket(fixture()), ref = alias(p, 'button');
  assert.throws(() => validateNavigationReferences(p, ['not-real']));
  assert.throws(() => validateNavigationReferences(p, [ref, ref]));
  assert.throws(() => validateNavigationReferences(p, [ref], { snapshotId: 'old' }));
  const corrupt = structuredClone(p); corrupt.eligibleIds.push(alias(p, 'inactive'));
  assert.throws(() => validateNavigationReferences(corrupt, [ref]));
  const corruptText = structuredClone(p); corruptText.text += ' ';
  assert.throws(() => validateNavigationReferences(corruptText, [ref]));
});

test('repeated inherited metadata is omitted only when its parent remains', () => {
  const v = fixture(); v.nodes.root.language = 'en'; v.nodes.button.language = 'en'; v.nodes.help.language = 'en';
  const nodes = projected(navigationPacket(v));
  assert.equal(nodes.get('root')[3].l, 'en');
  assert.ok(!Object.hasOwn(nodes.get('button')[3], 'l'));
  assert.equal(nodes.get('help')[3].l, 'en');
});

test('missing metadata resets to unknown instead of acquiring parent evidence', () => {
  const v = fixture(); v.nodes.root.language = 'en'; v.nodes.root.direction = 'ltr';
  v.nodes.root.structure = { textMode: 'normal', contentKind: 'prose' };
  const n = projected(navigationPacket(v)).get('button');
  assert.equal(n[3].l, null); assert.equal(n[3].dir, null);
  assert.deepEqual(n[3].st, { contentKind: null, textMode: null });
});

test('adapter-style indentation is removed while mixed inline word separators survive', () => {
  const v = fixture(); v.nodes.space.structure = { textMode: 'normal' };
  assert.ok(!projected(navigationPacket(v)).has('space'));
  v.nodes.root.role = 'paragraph';
  v.nodes.hidden.role = 'generic'; v.nodes.hidden.exposure = {};
  const n = projected(navigationPacket(v, boundObservation(v))).get('space');
  assert.equal(n[3].t, ' ');
});

test('hidden relationship subtree and transitive labels remain context evidence', () => {
  const v = fixture(); v.relations[0].targets = [{ node: 'hidden' }];
  v.relations.push({ from: 'inactive', kind: 'labelledBy', targets: [{ node: 'help' }], basis: 'reported' });
  const p = navigationPacket(v), nodes = projected(p);
  assert.equal(nodes.get('inactive')[3].ctx, true);
  assert.equal(nodes.get('help')[3].t, 'Card help');
  assert.equal(JSON.parse(p.text).relations.length, 2);
  assert.ok(p.observedIds.includes(alias(p, 'inactive')));
  assert.ok(!p.eligibleIds.includes(alias(p, 'inactive')));
});

test('a retained relation gap keeps its otherwise hidden owner and gap record', () => {
  const v = fixture();
  v.gaps.push({ id: 'hidden-gap', owner: 'hidden', field: 'relation', reason: 'budget', expansion: 'unavailable' });
  v.relations[0].targets.push({ gap: 'hidden-gap' });
  const p = navigationPacket(v), model = JSON.parse(p.text);
  assert.equal(model.gaps.length, 1);
  assert.equal(projected(p).get('hidden')[3].ctx, true);
  assert.ok(model.relations[0][2].includes(model.gaps[0].id));
});

test('scoped hidden controls use original ancestry even when their context ancestor is detached', () => {
  const v = fixture(), obs = boundObservation(v);
  const scoped = compactIR(obs, { roots: ['inactive'], profile: 'structure' }).view;
  assert.throws(() => navigationPacket(scoped), /bound observation/);
  const p = navigationPacket(scoped, obs);
  assert.ok(!p.eligibleSourceIds.includes('inactive'));
  assert.throws(() => validateNavigationReferences(p, [alias(p, 'inactive')]));
});

test('scoped text preserves whitespace from its original code ancestor', () => {
  const v = fixture(), obs = boundObservation(v);
  const scoped = compactIR(obs, { roots: ['codeSpace'], profile: 'structure' }).view;
  const p = navigationPacket(scoped, obs);
  assert.equal(projected(p).get('codeSpace')[3].t, '  \n');
});

test('bound observation rejects wrong snapshots and stale content without changing full-view output', () => {
  const v = fixture(), obs = boundObservation(v);
  assert.deepEqual(navigationPacket(v), navigationPacket(v, obs));
  const changed = structuredClone(obs); changed.nodes.button.states.disabled = true;
  assert.throws(() => navigationPacket(v, changed), /does not match/);
  changed.snapshotId = 'different';
  assert.throws(() => navigationPacket(v, changed), /does not match/);
});
