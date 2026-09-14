import { modelPacket } from './codec.mjs';
import { IRValidationError, observationHash, stableStringify, validateObservation } from './validate.mjs';

const keys = { text: 't', name: 'n', description: 'd', value: 'v', states: 's', actions: 'a', destination: 'u', labelHints: 'h', language: 'l', direction: 'dir', structure: 'st', exposure: 'e', bounds: 'b', coverage: 'cv' };

/** A source-bound organizer projection; never modifies the observation or compact view. */
export function navigationPacket(view, observation) {
  const source = modelPacket(view);
  const sourceHidden = new Map(), sourceVerbatim = new Map();
  if (observation) {
    validateObservation(observation);
    if (observation.snapshotId !== view.snapshotId || observationHash(observation) !== view.observationHash) {
      throw new IRValidationError('Navigation observation does not match view', 'stale_packet');
    }
    const stack = observation.roots.map(id => [id, false, false]);
    while (stack.length) {
      const [id, inheritedHidden, inheritedVerbatim] = stack.pop();
      const n = observation.nodes[id], e = n.exposure ?? {};
      const hidden = inheritedHidden || e.rendered === false || e.accessibilityIncluded === false || e.inert === true || e.dormant === true;
      const verbatim = inheritedVerbatim || ['code', 'math'].includes(n.role) || n.structure?.textMode === 'verbatim' || ['code', 'math'].includes(n.structure?.contentKind);
      sourceHidden.set(id, hidden); sourceVerbatim.set(id, verbatim);
      for (const child of n.children) stack.push([child, hidden, verbatim]);
    }
    for (const id of Object.values(source.aliases.nodes)) {
      if (!Object.hasOwn(observation.nodes, id)) throw new IRValidationError('Navigation view node absent from observation', 'stale_packet');
    }
  } else if (view.contextRoots.length || view.scope.context.length || view.scope.roots.some(id => view.nodes[id]?.role !== 'document')) {
    throw new IRValidationError('Scoped navigation requires its bound observation to recover original ancestry');
  }
  const model = JSON.parse(source.text);
  const nodes = new Map(model.nodes.map(n => [n.id, n]));
  const parents = new Map(), hidden = new Map(), verbatim = new Map();
  const relationTargets = new Set(model.relations.flatMap(r => r.targets.filter(t => t.node).map(t => t.node)));
  for (const n of model.nodes) {
    const parent = parents.get(n.id);
    const e = n.exposure ?? {};
    const sourceId = source.aliases.nodes[n.id];
    hidden.set(n.id, !!sourceHidden.get(sourceId) || !!hidden.get(parent) || e.rendered === false || e.accessibilityIncluded === false || e.inert === true || e.dormant === true);
    verbatim.set(n.id, !!sourceVerbatim.get(sourceId) || !!verbatim.get(parent) || ['code', 'math'].includes(n.role) || n.structure?.textMode === 'verbatim' || ['code', 'math'].includes(n.structure?.contentKind));
    for (const c of n.children) if (c.node) parents.set(c.node, n.id);
  }
  const gapOwners = new Set(model.gaps.map(g => g.owner));
  const relationSources = new Set(model.relations.map(r => r.from));
  const whitespaceCandidates = new Set(model.nodes.filter(n => n.role === 'text' && !verbatim.get(n.id)
    && n.text?.kind === 'complete' && /^\s+$/.test(n.text.value) && !n.children.length
    && !relationTargets.has(n.id) && !relationSources.has(n.id) && !gapOwners.has(n.id)
    && (!n.structure || Object.entries(n.structure).every(([k, v]) => (k === 'textMode' && v === 'normal') || (k === 'contentKind' && v === 'prose')))
    && !Object.keys(n).some(k => !['id', 'role', 'children', 'membership', 'text', 'language', 'direction', 'structure'].includes(k))).map(n => n.id));
  const blocks = new Set(['document', 'paragraph', 'heading', 'group', 'form', 'list', 'listItem', 'table', 'row', 'definitionList', 'figure', 'code', 'math', 'dialog', 'navigation', 'main', 'banner', 'contentInfo', 'complementary', 'search']);
  const whitespace = new Set();
  // Only drop indentation among known block-like roles. Unknown/generic wrappers
  // may be inline; keep their separators rather than concatenate adjacent words.
  for (const parent of model.nodes) {
    if (!blocks.has(parent.role)) continue;
    let previous;
    const nextMeaningful = new Map();
    let next;
    for (let i = parent.children.length - 1; i >= 0; i--) {
      const c = parent.children[i]; nextMeaningful.set(i, next);
      if (!c.node || !whitespaceCandidates.has(c.node)) next = c;
    }
    for (let i = 0; i < parent.children.length; i++) {
      const c = parent.children[i];
      if (c.node && whitespaceCandidates.has(c.node)) {
        const after = nextMeaningful.get(i);
        const blockOrAbsent = ref => !ref || (ref.node && blocks.has(nodes.get(ref.node).role));
        if (blockOrAbsent(previous) && blockOrAbsent(after)) whitespace.add(c.node);
      } else previous = c;
    }
  }
  const kept = new Set(model.nodes.filter(n => !hidden.get(n.id) && !whitespace.has(n.id)).map(n => n.id));
  // Relationship targets can carry essential hidden labels or help. Retain their
  // descendants and transitive relationships as evidence, never as active targets.
  const outgoing = new Map();
  const gapOwnersById = new Map(model.gaps.map(g => [g.id, g.owner]));
  const relationGaps = new Map();
  for (const r of model.relations) {
    if (!outgoing.has(r.from)) outgoing.set(r.from, []);
    if (!relationGaps.has(r.from)) relationGaps.set(r.from, []);
    for (const target of r.targets) {
      if (target.node) outgoing.get(r.from).push(target.node);
      if (target.gap) relationGaps.get(r.from).push(target.gap);
    }
  }
  const queue = [...kept];
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i];
    const n = nodes.get(id);
    const gapIds = [...n.children.filter(c => c.gap).map(c => c.gap), ...(n.text?.kind === 'extract' ? n.text.parts.filter(p => p.gap).map(p => p.gap) : []), ...(relationGaps.get(id) ?? [])];
    for (const next of [...n.children.filter(c => c.node && (hidden.get(id) || relationTargets.has(id))).map(c => c.node), ...(outgoing.get(id) ?? []), ...gapIds.map(g => gapOwnersById.get(g))]) {
      if (!kept.has(next)) { kept.add(next); queue.push(next); }
    }
  }
  const eligibleIds = model.nodes.filter(n => kept.has(n.id) && n.membership === 'owned' && !hidden.get(n.id)).map(n => n.id);
  const eligible = new Set(eligibleIds);
  const endpoint = ref => ref.node ?? ref.gap ?? ref.unresolved;
  const projected = model.nodes.filter(n => kept.has(n.id)).map(n => {
    const props = {};
    if (!eligible.has(n.id)) props.ctx = true;
    const parent = kept.has(parents.get(n.id)) ? nodes.get(parents.get(n.id)) : undefined;
    for (const key of ['language', 'direction']) if (Object.hasOwn(parent ?? {}, key) && !Object.hasOwn(n, key)) props[keys[key]] = null;
    for (const [key, short] of Object.entries(keys)) {
      if (!Object.hasOwn(n, key)) continue;
      if (['language', 'direction'].includes(key) && parent?.[key] === n[key]) continue;
      if (key === 'text') props.t = n.text.kind === 'complete' ? (whitespaceCandidates.has(n.id) ? ' ' : n.text.value) : n.text.parts.map(p => Object.hasOwn(p, 'text') ? p.text : { gap: p.gap });
      else if (key === 'structure') {
        const structure = { ...n.structure };
        for (const inherited of ['textMode', 'contentKind']) if (parent?.structure?.[inherited] === structure[inherited]) delete structure[inherited];
        if (Object.keys(structure).length) props[short] = structure;
      } else props[short] = n[key];
    }
    for (const inherited of ['textMode', 'contentKind']) {
      if (Object.hasOwn(parent?.structure ?? {}, inherited) && !Object.hasOwn(n.structure ?? {}, inherited)) {
        props.st ??= {}; props.st[inherited] = null;
      }
    }
    const tuple = [n.id, n.role, n.children.filter(c => !c.node || kept.has(c.node)).map(endpoint)];
    if (Object.keys(props).length) tuple.push(props);
    return tuple;
  });
  const roots = projected.filter(n => !kept.has(parents.get(n[0]))).map(n => n[0]);
  const text = stableStringify({
    version: 'ui-navigation/0.1',
    legend: { node: '[id,role,ordered children,optional properties]', properties: Object.fromEntries(Object.entries(keys).map(([long, short]) => [short, long])),
      ctx: 'true means context only; never assign', references: 'n=node, g=gap, u=unresolved; d=destination, s=coordinate space',
      text: 'string=complete; array=extract with explicit gaps', inherited: 'language,direction,textMode,contentKind inherit along children; null explicitly resets to unknown',
      exposure: 'Missing visibility is unknown, never evidence of visibility. Explicit rendered=false/accessibilityIncluded=false/inert=true/dormant=true excludes the entire descendant subtree from active navigation.',
      relations: '[from,kind,targets,basis]', filtering: 'Explicitly inactive subtrees omitted except relationship evidence; whitespace indentation between known block roles omitted. Other whitespace-only leaves become one space outside verbatim text; preserve these separators when reading inline text.' },
    roots, nodes: projected, coverage: model.coverage,
    ...(model.focusedNode && kept.has(model.focusedNode) ? { focusedNode: model.focusedNode } : {}),
    relations: model.relations.filter(r => kept.has(r.from)).map(r => [r.from, r.kind, r.targets.map(endpoint), r.basis]),
    gaps: model.gaps.filter(g => kept.has(g.owner)),
  });
  const base = { text, aliases: source.aliases, snapshotId: source.snapshotId, observationHash: source.observationHash, viewHash: source.viewHash,
    observedIds: projected.map(n => n[0]), eligibleIds, eligibleSourceIds: eligibleIds.map(id => source.aliases.nodes[id]),
    stats: { sourceNodes: model.nodes.length, projectedNodes: projected.length, eligibleNodes: eligibleIds.length, hiddenNodes: [...hidden.values()].filter(Boolean).length, whitespaceNodes: whitespace.size } };
  return { ...base, packetHash: observationHash(base) };
}

export function validateNavigationReferences(packet, refs, expected = {}) {
  if (!packet || !Array.isArray(refs)) throw new IRValidationError('Expected a navigation packet and reference list');
  const { packetHash, ...base } = packet;
  if (packetHash !== observationHash(base)) throw new IRValidationError('Corrupt navigation packet', 'stale_packet');
  for (const key of ['snapshotId', 'observationHash', 'viewHash', 'packetHash']) {
    if (expected[key] !== undefined && expected[key] !== packet[key]) throw new IRValidationError(`Stale ${key}`, 'stale_packet');
  }
  if (new Set(refs).size !== refs.length) throw new IRValidationError('Duplicate navigation references');
  const model = JSON.parse(packet.text);
  if (model.version !== 'ui-navigation/0.1') throw new IRValidationError('Invalid navigation format');
  const nodes = new Map(model.nodes.map(n => [n[0], n]));
  const eligible = new Set(packet.eligibleIds);
  return refs.map(ref => {
    if (typeof ref !== 'string' || !Object.hasOwn(packet.aliases.nodes, ref) || !nodes.has(ref)) throw new IRValidationError('Unknown navigation reference');
    if (!eligible.has(ref) || nodes.get(ref)[3]?.ctx) throw new IRValidationError('Hidden or context node is not assignable');
    return packet.aliases.nodes[ref];
  });
}
