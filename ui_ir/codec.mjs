import { IRValidationError, validateView, stableStringify, observationHash } from './validate.mjs';

function packetFor(view) {
  validateView(view);
  const order = [], seen = new Set();
  const stack = [...view.roots, ...view.contextRoots].reverse();
  while (stack.length) {
    const key = stack.pop(); if (seen.has(key)) continue;
    seen.add(key); order.push(key);
    const children = view.nodes[key].children.filter(c => c.node).map(c => c.node);
    for (let i = children.length - 1; i >= 0; i--) stack.push(children[i]);
  }
  const aliases = { nodes: Object.create(null), gaps: Object.create(null), unresolved: Object.create(null), destinations: Object.create(null), spaces: Object.create(null) };
  const maps = Object.fromEntries(Object.keys(aliases).map(k => [k, new Map()]));
  function alias(kind, key, prefix) {
    if (!maps[kind].has(key)) {
      const short = prefix + maps[kind].size.toString(36);
      maps[kind].set(key, short); aliases[kind][short] = key;
    }
    return maps[kind].get(key);
  }
  order.forEach(key => alias('nodes', key, 'n'));
  // Gap order is the contract's deterministic array order, not raw source ID sort.
  view.gaps.forEach(g => alias('gaps', g.id, 'g'));
  const nodeAlias = key => {
    if (!maps.nodes.has(key)) throw new IRValidationError('Unexposed node cannot be serialized');
    return maps.nodes.get(key);
  };
  const gapAlias = key => {
    if (!maps.gaps.has(key)) throw new IRValidationError('Unknown gap cannot be serialized');
    return maps.gaps.get(key);
  };
  const endpoint = ref => ref.node ? { node: nodeAlias(ref.node) }
    : ref.gap ? { gap: gapAlias(ref.gap) } : { unresolved: alias('unresolved', ref.unresolved, 'u') };
  const nodes = order.map(key => {
    const n = structuredClone(view.nodes[key]);
    n.children = n.children.map(endpoint);
    if (n.text?.kind === 'extract') n.text.parts = n.text.parts.map(part => Object.hasOwn(part, 'text') ? part : { gap: gapAlias(part.gap) });
    if (n.destination) n.destination.id = alias('destinations', n.destination.id, 'd');
    if (n.bounds) n.bounds.space = alias('spaces', n.bounds.space, 's');
    return { id: nodeAlias(key), ...n };
  });
  const model = {
    version: 'ui-model/0.1', policy: view.policy, profile: view.profile, coverage: view.coverage,
    roots: view.roots.map(nodeAlias), contextRoots: view.contextRoots.map(nodeAlias), nodes,
    ...(view.focusedNode ? { focusedNode: nodeAlias(view.focusedNode) } : {}),
    relations: view.relations.map(r => ({ ...r, from: nodeAlias(r.from), targets: r.targets.map(endpoint) })),
    gaps: view.gaps.map(g => ({ ...g, id: gapAlias(g.id), owner: nodeAlias(g.owner) })),
  };
  const text = stableStringify(model);
  const base = { text, aliases, snapshotId: view.snapshotId, observationHash: view.observationHash, viewHash: observationHash(view) };
  return { ...base, packetHash: observationHash(base) };
}

export function encodeModelView(view) { return packetFor(view).text; }
export function modelPacket(view) { return packetFor(view); }

export function validateModelReferences(packet, refs, expected = {}) {
  if (!packet || !Array.isArray(refs)) throw new IRValidationError('Expected a model packet and reference list');
  const { packetHash, ...base } = packet;
  if (packetHash !== observationHash(base)) throw new IRValidationError('Corrupt model packet', 'stale_packet');
  for (const key of ['snapshotId', 'observationHash', 'viewHash', 'packetHash']) {
    if (expected[key] !== undefined && expected[key] !== packet[key]) throw new IRValidationError(`Stale ${key}`, 'stale_packet');
  }
  if (new Set(refs).size !== refs.length) throw new IRValidationError('Duplicate model references');
  const nodes = new Map(JSON.parse(packet.text).nodes.map(n => [n.id, n]));
  return refs.map(ref => {
    if (typeof ref !== 'string' || !Object.hasOwn(packet.aliases.nodes, ref) || !nodes.has(ref)) throw new IRValidationError('Unknown model reference');
    if (nodes.get(ref).membership !== 'owned') throw new IRValidationError('Context is not assignable');
    return packet.aliases.nodes[ref];
  });
}
