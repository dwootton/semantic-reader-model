import { validateObservation, validateView, observationHash, stableStringify } from './validate.mjs';
import { encodeModelView } from './codec.mjs';

const POLICY = 'organizer-floor/0.1';
const CONTROLS = new Set('link button textField checkbox radio switch comboBox listBox tab slider spinButton treeItem menuItem'.split(' '));
const BOUNDARIES = new Set('document paragraph heading group form list listItem table row cell rowHeader columnHeader definitionList term definition image figure caption code math dialog alert status navigation main banner contentInfo complementary search tabPanel tree grid gridCell menu frame'.split(' '));
const COMPLETE = new Set('heading rowHeader columnHeader caption code math alert status'.split(' '));
const DEPENDENCIES = new Set('labelledBy describedBy errorMessage details headers captionedBy'.split(' '));
const INDIVISIBLE = new Set('paragraph heading listItem row cell gridCell option code math textField checkbox radio switch button link'.split(' '));
const clone = value => structuredClone(value);
const bytes = value => Buffer.byteLength(value, 'utf8');
const has = (obj, key) => Object.hasOwn(obj, key);

function settings(request) {
  const r = { profile: 'structure', maxBytes: 200000, maxCandidateEvaluations: 256, maxPartitionTrials: 512, maxRegions: 64, planRegions: true, ...request };
  if (!['structure', 'excerpt', 'budget'].includes(r.profile)) throw new TypeError('Unknown compaction profile');
  for (const [key, limit] of [['maxBytes', Number.MAX_SAFE_INTEGER], ['maxCandidateEvaluations', 256], ['maxPartitionTrials', 512], ['maxRegions', 64]]) {
    if (!Number.isSafeInteger(r[key]) || r[key] < 0 || r[key] > limit) throw new TypeError(`Invalid ${key}`);
  }
  for (const key of ['maxTokens', 'reservedOutputTokens']) if (r[key] !== undefined && (!Number.isSafeInteger(r[key]) || r[key] < 0)) throw new TypeError(`Invalid ${key}`);
  if (r.measureTokens !== undefined && (typeof r.measureTokens !== 'function' || !r.tokenizerId)) throw new TypeError('Token measurement requires callback and tokenizerId');
  if (r.maxTokens !== undefined && !r.measureTokens) throw new TypeError('maxTokens requires exact token measurement');
  for (const key of ['promptPrefix', 'promptSuffix']) if (r[key] !== undefined && typeof r[key] !== 'string') throw new TypeError(`Invalid ${key}`);
  return r;
}

function indexObservation(obs) {
  const parent = new Map(), order = [], rank = new Map(), relations = new Map(), endpoints = new Set(), inForm = new Map(), precedingHeading = new Map();
  const stack = [...obs.roots].reverse();
  while (stack.length) {
    const id = stack.pop(); rank.set(id, order.length); order.push(id); inForm.set(id, obs.nodes[parent.get(id)]?.role === 'form' || inForm.get(parent.get(id)) === true);
    const children = obs.nodes[id].children;
    let lastHeading; for (const child of children) { if (lastHeading !== undefined) precedingHeading.set(child, lastHeading); if (obs.nodes[child].role === 'heading') lastHeading = child; }
    for (let i = children.length - 1; i >= 0; i--) { parent.set(children[i], id); stack.push(children[i]); }
  }
  for (const relation of obs.relations) {
    if (!relations.has(relation.from)) relations.set(relation.from, []);
    relations.get(relation.from).push(relation); endpoints.add(relation.from);
    for (const target of relation.targets) if (target.node) endpoints.add(target.node);
  }
  const end = new Map(order.map(id => [id, rank.get(id) + 1]));
  for (const id of order.slice().reverse()) if (parent.has(id)) end.set(parent.get(id), Math.max(end.get(parent.get(id)), end.get(id)));
  return { parent, order, rank, end, relations, endpoints, inForm, precedingHeading };
}
function descendants(obs, ids) {
  const found = new Set(), stack = [...ids].reverse();
  while (stack.length) { const id = stack.pop(); if (found.has(id)) continue; found.add(id); const children = obs.nodes[id].children; for (let i = children.length - 1; i >= 0; i--) stack.push(children[i]); }
  return found;
}
function sourceRoots(obs, requested, index) {
  const input = requested ?? obs.roots;
  if (!Array.isArray(input) || !input.length || input.some(id => typeof id !== 'string' || !has(obs.nodes, id))) throw new TypeError('Invalid scope roots');
  const chosen = new Set(input);
  const belowSelection = new Set(), roots = [];
  for (const id of index.order) { const parent = index.parent.get(id); if (chosen.has(parent) || belowSelection.has(parent)) belowSelection.add(id); if (chosen.has(id) && !belowSelection.has(id)) roots.push(id); }
  return roots;
}
function nativeOptions(obs, index) {
  const options = new Set(), collections = new Map(), nativeChoiceRefs = new Set(), nearest = new Map();
  for (const relation of obs.relations) if (relation.kind === 'choices' && relation.basis === 'native-semantics') {
    nativeChoiceRefs.add(relation.from); for (const target of relation.targets) if (target.node) nativeChoiceRefs.add(target.node);
  }
  for (const id of index.order) {
    const node = obs.nodes[id];
    let collection = nearest.get(index.parent.get(id));
    if (['comboBox', 'listBox'].includes(node.role) && (node.actions?.some(a => a.kind === 'select' && a.basis === 'native-semantics') || nativeChoiceRefs.has(id))) { collection = id; collections.set(id, []); }
    nearest.set(id, collection);
    if (collection && node.role === 'option') { options.add(id); collections.get(collection).push(id); }
  }
  return { options, collections };
}

function whitespaceOnly(node) {
  return node.role === 'text' && node.structure?.textMode === 'normal' && typeof node.text === 'string' && !node.text.trim() && node.children.length === 0;
}

function build(obs, request, index) {
  const roots = sourceRoots(obs, request.roots, index), scopeRootSet = new Set(roots), owned = descendants(obs, roots);
  const required = new Set(request.requiredRefs ?? []);
  if ([...required].some(id => !has(obs.nodes, id))) throw new TypeError('Unknown required reference');
  const { options, collections } = nativeOptions(obs, index);
  const optionDescendants = descendants(obs, [...options]);
  const shell = new Set(), full = new Set(), visible = new Set(), context = new Set(), excluded = new Set(), diagnostics = [];
  const fullSubtrees = new Set();
  const addFull = id => { const stack = [id]; while (stack.length) { const child = stack.pop(); if (fullSubtrees.has(child)) continue; fullSubtrees.add(child); full.add(child); shell.add(child); for (const descendant of obs.nodes[child].children) stack.push(descendant); } };
  // An explicitly selected dormant root admits that subtree, not unrelated dormant siblings.
  const explicitlyVisible = request.roots === undefined ? new Set() : descendants(obs, roots.filter(id => obs.nodes[id].exposure?.dormant === true || obs.nodes[id].exposure?.inert === true));
  // Dormancy propagates; unknown exposure never means hidden.
  for (const id of index.order) {
    if (!owned.has(id)) continue;
    const node = obs.nodes[id], parent = index.parent.get(id);
    if (!explicitlyVisible.has(id) && (excluded.has(parent) || node.exposure?.dormant === true || node.exposure?.inert === true)) excluded.add(id);
    else visible.add(id);
  }
  for (const id of required) { for (const child of descendants(obs, [id])) { if (owned.has(child)) visible.add(child); else context.add(child); excluded.delete(child); } addFull(id); }
  if (obs.focusedNode && owned.has(obs.focusedNode)) {
    if (excluded.has(obs.focusedNode)) diagnostics.push({ kind: 'focus-exposure-conflict', node: obs.focusedNode });
    visible.add(obs.focusedNode); excluded.delete(obs.focusedNode); addFull(obs.focusedNode);
  }
  for (const id of visible) {
    const node = obs.nodes[id];
    if (optionDescendants.has(id)) {
      if (node.states?.current || node.states?.invalid || node.states?.expanded || node.states?.selected || node.states?.disabled || node.structure?.preserveScope || node.structure?.textMode === 'verbatim' || ['code', 'math'].includes(node.structure?.contentKind)) addFull(id);
      continue;
    }
    if (CONTROLS.has(node.role)) { if (['comboBox', 'listBox'].includes(node.role)) shell.add(id); else addFull(id); }
    if (BOUNDARIES.has(node.role) || node.structure?.boundary || node.structure?.preserveScope || node.structure?.opaqueContent || node.bounds || node.language || node.direction || node.children.filter(child => !whitespaceOnly(obs.nodes[child])).length > 1 || node.name || node.description || node.value || node.actions?.length || Object.keys(node.states ?? {}).length) shell.add(id);
    if (COMPLETE.has(node.role) || node.structure?.textMode === 'verbatim' || ['code', 'math'].includes(node.structure?.contentKind)) addFull(id);
    if (node.text !== undefined && (node.text.length <= 360 || node.structure?.textMode !== 'normal')) full.add(id);
    if (node.states?.selected || node.states?.current || node.states?.invalid || node.states?.expanded) addFull(id);
    if (node.name || node.description || node.labelHints?.length || Object.values(node.states ?? {}).some(Boolean)) shell.add(id);
    // Instructions in forms and first paragraph after each heading are complete.
    if (!['generic', 'form', 'group', 'comboBox', 'listBox'].includes(node.role) && index.inForm.get(id)) addFull(id);
    if (node.role === 'heading') {
      const siblings = obs.nodes[index.parent.get(id)]?.children ?? [];
      const next = siblings[siblings.indexOf(id) + 1];
      if (next && obs.nodes[next].role === 'paragraph') addFull(next);
    }
  }
  for (const [collection, ids] of collections) {
    if (!visible.has(collection)) continue;
    shell.add(collection);
    for (const [position, id] of ids.entries()) if (position < 2 || id === ids.at(-1) || obs.nodes[id].states?.selected || obs.nodes[id].states?.disabled || obs.nodes[id].structure?.preserveScope) addFull(id);
  }
  // Ancestor context and preceding headings give regional views their scope.
  const visitedContextEdges = new Set(), contextHeadings = new Set();
  for (const root of roots) {
    let childOnPath = root, id = index.parent.get(root);
    while (id !== undefined && !visitedContextEdges.has(childOnPath)) {
      visitedContextEdges.add(childOnPath);
      context.add(id); shell.add(id);
      const heading = index.precedingHeading.get(childOnPath);
      if (heading && !contextHeadings.has(heading)) { contextHeadings.add(heading); for (const child of descendants(obs, [heading])) context.add(child); addFull(heading); }
      childOnPath = id; id = index.parent.get(id);
    }
  }

  // Follow every known endpoint. Textual dependencies protect complete subtrees.
  const queue = [...visible, ...context, ...full], seen = new Set(), visitedPaths = new Set();
  const contextPath = id => { let ancestor = index.parent.get(id); while (ancestor !== undefined && !visitedPaths.has(ancestor)) { visitedPaths.add(ancestor); if (!visible.has(ancestor)) { context.add(ancestor); queue.push(ancestor); } ancestor = index.parent.get(ancestor); } };
  while (queue.length) {
    const id = queue.pop(); if (seen.has(id)) continue; seen.add(id);
    for (const relation of index.relations.get(id) ?? []) {
      shell.add(id);
      for (const target of relation.targets) {
        if (!target.node) continue;
        const completeTarget = DEPENDENCIES.has(relation.kind) || obs.nodes[target.node].role === 'option';
        const targets = completeTarget ? descendants(obs, [target.node]) : new Set([target.node]);
        for (const child of targets) {
          shell.add(child); if (completeTarget) full.add(child);
          if (!visible.has(child)) context.add(child);
          queue.push(child);
          contextPath(child);
        }
      }
    }
  }
  for (const id of full) if (!visible.has(id)) context.add(id);
  // Preserve paths to all retained nodes, without pulling unrelated siblings into context.
  const connectedPaths = new Set();
  for (const id of [...visible, ...context]) { let p = index.parent.get(id); while (p !== undefined && !connectedPaths.has(p)) { connectedPaths.add(p); if (owned.has(p) && !excluded.has(p)) visible.add(p); else context.add(p); p = index.parent.get(p); } }
  for (const id of visible) context.delete(id);
  const included = new Set([...visible, ...context]), nodes = Object.create(null), ledger = { nodes: [], fields: [], gaps: Object.create(null) }, gaps = [];
  for (const id of index.order) if (included.has(id)) {
    const { children, text, ...fields } = obs.nodes[id];
    nodes[id] = { ...clone(fields), membership: visible.has(id) && owned.has(id) ? 'owned' : 'context', children: children.filter(child => included.has(child) && ((visible.has(child) && owned.has(child)) === (visible.has(id) && owned.has(id)))).map(node => ({ node })) };
    if (text !== undefined) nodes[id].text = { kind: 'complete', value: text };
  }
  const view = { version: 'ui-view/0.1', snapshotId: obs.snapshotId, observationHash: observationHash(obs), policy: POLICY, profile: request.profile, scope: { roots, context: index.order.filter(id => context.has(id)) }, roots: [], contextRoots: [], nodes, relations: clone(obs.relations.filter(r => included.has(r.from))), gaps, coverage: obs.coverage.children };
  if (obs.focusedNode && included.has(obs.focusedNode)) view.focusedNode = obs.focusedNode;
  for (const id of index.order) if (included.has(id)) {
    const p = index.parent.get(id);
    if (!included.has(p) || nodes[p].membership !== nodes[id].membership) (nodes[id].membership === 'owned' ? view.roots : view.contextRoots).push(id);
  }
  for (const id of index.order) ledger.nodes.push({ id, disposition: included.has(id) ? (nodes[id].membership === 'context' ? 'reference-only' : 'retained') : 'excluded', representedBy: included.has(id) ? id : null, reason: included.has(id) ? 'source-evidence' : owned.has(id) ? 'dormant-or-inert' : 'outside_scope' });
  const ledgerIndex = new Map(ledger.nodes.map(entry => [entry.id, entry]));
  // Represent omitted owned branches at their original positions.
  for (const id of index.order) if (nodes[id] && nodes[id].membership === 'owned') {
    const children = [];
    for (const child of obs.nodes[id].children) {
      if (nodes[child]?.membership === 'owned') children.push({ node: child });
      else if (owned.has(child) && !context.has(child)) {
        const ids = [...descendants(obs, [child])];
        const gap = addGap(view, ledger, id, 'children', 'dormant-or-inert', { nodeIds: ids }); children.push({ gap });
        for (const omitted of ids) { const entry = ledgerIndex.get(omitted); if (entry.disposition === 'excluded') entry.representedBy = gap; }
      }
    }
    nodes[id].children = children;
  }
  for (const id of index.order) if (nodes[id] && (obs.nodes[id].structure?.opaqueContent || obs.nodes[id].coverage?.children === 'partial')) addGap(view, ledger, id, 'upstream', 'capture-unavailable', {}, 'unavailable');
  for (const [id, node] of Object.entries(nodes)) if (node.text && (obs.nodes[id].coverage?.text ?? obs.coverage.text) === 'partial') {
    const gap = addGap(view, ledger, id, 'text', 'source-text-incomplete', {}, 'unavailable');
    node.text = { kind: 'extract', parts: [{ text: obs.nodes[id].text }, { gap }] };
  }
  // Existing evidence gaps must keep their owner unless a later transform explicitly rehomes them.
  for (const gap of view.gaps) shell.add(gap.owner);
  const protectedNodes = new Set([...shell, ...full]), replacements = new Map();
  for (const id of index.order.slice().reverse()) {
    if (nodes[id]) nodes[id].children = nodes[id].children.flatMap(child => child.node && replacements.has(child.node) ? replacements.get(child.node) : [child]);
    if (!nodes[id] || protectedNodes.has(id) || required.has(id) || index.endpoints.has(id) || scopeRootSet.has(id) || context.has(id)) continue;
    const n = nodes[id];
    const parent = index.parent.get(id);
    if (!parent) continue;
    const redundantTextMode = n.structure && Object.keys(n.structure).length === 1 && n.structure.textMode === 'normal' && nodes[parent].structure?.textMode === 'normal';
    if (n.role !== 'generic' || n.children.filter(child => child.gap || !whitespaceOnly(obs.nodes[child.node])).length > 1 || n.text?.kind === 'extract' || n.text?.value?.trim() || Object.keys(n).some(key => !['role', 'children', 'text', 'membership', 'exposure', 'coverage', ...(redundantTextMode ? ['structure'] : [])].includes(key))) continue;
    if (n.exposure && Object.keys(n.exposure).length) continue;
    replacements.set(id, n.children);
    const entry = ledgerIndex.get(id); entry.disposition = 'collapsed'; entry.representedBy = n.children.find(child => child.node && !whitespaceOnly(obs.nodes[child.node]))?.node ?? parent; entry.reason = 'transparent-wrapper'; delete nodes[id];
  }
  const resolved = new Map();
  for (const entry of ledger.nodes) if (entry.disposition === 'collapsed') {
    const chain = []; let target = entry.id;
    while (ledgerIndex.get(target)?.disposition === 'collapsed' && !resolved.has(target)) { chain.push(target); target = ledgerIndex.get(target).representedBy; }
    target = resolved.get(target) ?? target;
    for (const id of chain) { resolved.set(id, target); ledgerIndex.get(id).representedBy = target; }
  }
  return { view, ledger, ledgerIndex, full, shell, options, collections, diagnostics, index };
}
function addGap(view, ledger, owner, field, reason, detail, expansion = 'local') {
  let ordinal = view.gaps.length; let id = `gap:${ordinal}`; while (has(view.nodes, id) || has(ledger.gaps, id)) id = `gap:${++ordinal}`;
  const gap = { id, owner, field, reason, expansion };
  if (detail.nodeIds) gap.omittedNodes = detail.nodeIds.length;
  if (detail.start !== undefined) gap.omittedCharacters = detail.end - detail.start;
  view.gaps.push(gap); ledger.gaps[id] = { owner, field, ...detail }; view.coverage = 'partial';
  return id;
}
function textCut(text, count) { let cut = Math.min(count, text.length); if (cut > 0 && cut < text.length && /[\uD800-\uDBFF]/.test(text[cut - 1]) && /[\uDC00-\uDFFF]/.test(text[cut])) cut--; return cut; }
function measure(view, request) {
  const encoded = encodeModelView(view), prompt = (request.promptPrefix ?? '') + encoded + (request.promptSuffix ?? '');
  const tokenCount = request.measureTokens ? request.measureTokens(prompt) : null;
  if (tokenCount !== null && (!Number.isSafeInteger(tokenCount) || tokenCount < 0)) throw new TypeError('Tokenizer must return an exact nonnegative integer synchronously');
  return { encodedBytes: bytes(encoded), completePromptBytes: bytes(prompt), inputTokens: tokenCount, reservedOutputTokens: request.reservedOutputTokens ?? 0, tokenizerId: request.tokenizerId ?? null, maxBytes: request.maxBytes, maxTokens: request.maxTokens ?? null, fits: bytes(prompt) <= request.maxBytes && (request.maxTokens === undefined || tokenCount + (request.reservedOutputTokens ?? 0) <= request.maxTokens) };
}
function removeNodes(state, ids, gap) {
  for (const id of ids) {
    delete state.view.nodes[id];
    const entry = state.ledgerIndex.get(id);
    if (entry) { entry.disposition = 'deferred'; entry.representedBy = gap; entry.reason = 'budget-or-choice-preview'; }
  }
}
function candidates(obs, state, request) {
  const result = [];
  const weight = (id, node) => {
    if (node.name || node.structure?.boundary) return 4;
    const focus = obs.focusedNode;
    if (focus && (id === focus || state.index.parent.get(id) === focus || state.index.parent.get(focus) === id || state.index.parent.get(state.index.parent.get(id)) === focus || state.index.parent.get(state.index.parent.get(focus)) === id || (state.index.parent.has(id) && state.index.parent.get(id) === state.index.parent.get(focus)))) return 2;
    return 1;
  };
  for (const id of state.index.order) {
    const n = state.view.nodes[id]; if (!n || n.membership !== 'owned') continue;
    if (!state.full.has(id) && n.text?.kind === 'complete' && n.text.value.length > (request.profile === 'budget' ? 180 : 360)) {
      result.push({ kind: 'text', id, saving: bytes(n.text.value), weight: weight(id, n) });
    }
    if (request.profile === 'budget' && n.children.length) {
      const ids = [...descendants(obs, obs.nodes[id].children)];
      if (ids.length && ids.every(child => !state.full.has(child) && !state.shell.has(child) && state.view.nodes[child]?.membership === 'owned') && !state.full.has(id)) result.push({ kind: 'children', id, ids, saving: ids.reduce((sum, child) => sum + bytes(JSON.stringify(state.view.nodes[child])), 0), weight: weight(id, n) });
    }
  }
  const optionCollection = new Map();
  for (const [collection, ids] of state.collections) if (state.view.nodes[collection]) for (const id of ids) optionCollection.set(id, collection);
  // Inspect current children once, after structural collapse; source option IDs stay stable.
  for (const [parent, node] of Object.entries(state.view.nodes)) {
    let run = [], collection;
    const flush = () => {
      if (run.length) {
        const omitted = run.flatMap(id => [...descendants(obs, [id])]);
        result.push({ kind: 'choices', id: parent, roots: run, ids: omitted, saving: omitted.reduce((sum, id) => sum + bytes(JSON.stringify(state.view.nodes[id] ?? {})), 0), weight: 1 });
        run = [];
      }
    };
    for (const child of node.children) {
      const owner = optionCollection.get(child.node);
      const eligible = owner && [...descendants(obs, [child.node])].every(id => !state.full.has(id) && !state.shell.has(id));
      if (!eligible || (collection !== undefined && owner !== collection)) flush();
      if (eligible) { collection = owner; run.push(child.node); }
    }
    flush();
  }
  return result.sort((a, b) => b.saving * a.weight - a.saving * b.weight || state.index.rank.get(a.id) - state.index.rank.get(b.id) || a.id.localeCompare(b.id) || a.kind.localeCompare(b.kind));
}
function applyCandidate(state, candidate, request) {
  const view = clone(state.view), ledger = clone(state.ledger), next = { ...state, view, ledger, ledgerIndex: new Map(ledger.nodes.map(entry => [entry.id, entry])) };
  const n = view.nodes[candidate.id];
  if (candidate.kind === 'text') {
    const text = n.text.value, cut = textCut(text, request.profile === 'budget' ? 180 : 360);
    const gap = addGap(view, ledger, candidate.id, 'text', 'prose-excerpt', { start: cut, end: text.length });
    n.text = { kind: 'extract', parts: [{ text: text.slice(0, cut) }, { gap }] };
    ledger.fields.push({ id: candidate.id, field: 'text', disposition: 'extract', gap });
  } else {
    const gap = addGap(view, ledger, candidate.id, 'children', candidate.kind === 'choices' ? 'choice-preview' : 'budget-fold', { nodeIds: candidate.ids });
    if (candidate.kind === 'choices') {
      view.gaps.at(-1).omittedItems = candidate.roots.length;
      let inserted = false;
      n.children = n.children.flatMap(child => candidate.roots.includes(child.node) ? (inserted ? [] : (inserted = true, [{ gap }])) : [child]);
    } else n.children = [{ gap }];
    removeNodes(next, candidate.ids, gap);
  }
  return next;
}
function verifyPreservation(obs, state) {
  validateView(state.view);
  const gapMap = new Map(state.view.gaps.map(gap => [gap.id, gap]));
  for (const [id, node] of Object.entries(state.view.nodes)) {
    const { children: _c, text: _t, membership: _m, ...fields } = node;
    const { children: _oc, text: _ot, ...expected } = obs.nodes[id];
    if (stableStringify(fields) !== stableStringify(expected)) throw new Error(`Changed source fields: ${id}`);
    if (state.full.has(id) && has(obs.nodes[id], 'text')) {
      const partialSource = (obs.nodes[id].coverage?.text ?? obs.coverage.text) === 'partial';
      const preserved = partialSource ? node.text?.kind === 'extract' && node.text.parts.length === 2 && node.text.parts[0].text === obs.nodes[id].text && gapMap.get(node.text.parts[1].gap)?.expansion === 'unavailable' && gapMap.get(node.text.parts[1].gap)?.reason === 'source-text-incomplete' : node.text?.kind === 'complete' && node.text.value === obs.nodes[id].text;
      if (!preserved) throw new Error(`Lost protected text: ${id}`);
    }
  }
  for (const id of [...state.full, ...state.shell]) if (!state.view.nodes[id]) throw new Error(`Lost protected node: ${id}`);
  const sourceRelations = obs.relations.filter(relation => has(state.view.nodes, relation.from));
  if (stableStringify(state.view.relations) !== stableStringify(sourceRelations)) throw new Error('Changed admitted relationships');
  for (const membership of ['owned', 'context']) {
    const actual = [], stack = [...(membership === 'owned' ? state.view.roots : state.view.contextRoots)].reverse();
    while (stack.length) { const id = stack.pop(); actual.push(id); const children = state.view.nodes[id].children; for (let i = children.length - 1; i >= 0; i--) if (children[i].node) stack.push(children[i].node); }
    const expected = state.index.order.filter(id => state.view.nodes[id]?.membership === membership);
    if (stableStringify(actual) !== stableStringify(expected)) throw new Error('Changed retained source order');
  }
  const gapNodeSets = new Map(Object.entries(state.ledger.gaps).map(([id, detail]) => [id, new Set(detail.nodeIds ?? [])]));
  for (const gap of state.view.gaps) {
    const detail = state.ledger.gaps[gap.id];
    if (!detail || detail.owner !== gap.owner || detail.field !== gap.field) throw new Error('Gap ledger mismatch');
    if (gap.expansion === 'local' && gap.field === 'text') {
      const text = obs.nodes[gap.owner].text, shown = state.view.nodes[gap.owner].text;
      if (typeof text !== 'string' || detail.end !== text.length || detail.start !== textCut(text, detail.start) || gap.omittedCharacters !== detail.end - detail.start || shown.kind !== 'extract' || shown.parts.length !== 2 || shown.parts[0].text !== text.slice(0, detail.start) || shown.parts[1].gap !== gap.id) throw new Error('Changed excerpt source ranges');
    }
    if (gap.field === 'children') {
      const ids = detail.nodeIds;
      if (!Array.isArray(ids) || gap.omittedNodes !== ids.length || new Set(ids).size !== ids.length) throw new Error('Gap node accounting mismatch');
      let previous = -1;
      for (const id of ids) {
        const rank = state.index.rank.get(id);
        if (has(state.view.nodes, id) || rank <= state.index.rank.get(gap.owner) || rank >= state.index.end.get(gap.owner) || rank <= previous) throw new Error('Gap does not represent omitted source descendants');
        previous = rank;
      }
    }
  }
  for (const [id, node] of Object.entries(state.view.nodes)) {
    let last = state.index.rank.get(id);
    for (const child of node.children) {
      const ids = child.node ? [child.node] : state.ledger.gaps[child.gap]?.nodeIds ?? [];
      if (!ids.length) continue;
      const first = state.index.rank.get(ids[0]), end = state.index.rank.get(ids.at(-1));
      if (first <= last || end >= state.index.end.get(id)) throw new Error('Child/gap position disagrees with source order');
      last = end;
    }
  }
  for (const entry of state.ledger.nodes) {
    if (entry.disposition === 'deferred' && (!gapMap.has(entry.representedBy) || !gapNodeSets.get(entry.representedBy)?.has(entry.id))) throw new Error('Deferred node is not accounted for');
  }
  if (state.ledger.nodes.length !== Object.keys(obs.nodes).length || new Set(state.ledger.nodes.map(n => n.id)).size !== Object.keys(obs.nodes).length) throw new Error('Incomplete ledger');
}

/** Pure source-neutral compaction. Oversize results are never ready for dispatch. */
export function compactIR(observation, request = {}) {
  validateObservation(observation);
  const r = settings(request), index = indexObservation(observation);
  let state = build(observation, r, index), cost = measure(state.view, r), evaluations = 0, accepted = 0;
  const initialBytes = cost.encodedBytes, exhausted = new Set();
  if (r.profile !== 'structure') while (evaluations < r.maxCandidateEvaluations) {
    const choices = candidates(observation, state, r).filter(c => !exhausted.has(JSON.stringify(c)));
    if (!choices.length || (r.profile === 'budget' && cost.fits)) break;
    const candidate = choices[0]; exhausted.add(JSON.stringify(candidate)); evaluations++;
    const next = applyCandidate(state, candidate, r), nextCost = measure(next.view, r);
    if (nextCost.encodedBytes < cost.encodedBytes) { state = next; cost = nextCost; accepted++; exhausted.clear(); }
  }
  verifyPreservation(observation, state);
  const result = { view: state.view, ledger: state.ledger, report: { status: cost.fits ? 'ready' : 'requires_partition', ...cost, profile: r.profile, policy: POLICY, observationNodes: Object.keys(observation.nodes).length, viewNodes: Object.keys(state.view.nodes).length, initialBytes, savedBytes: initialBytes - cost.encodedBytes, candidateEvaluations: evaluations, acceptedCandidates: accepted, evaluationLimitReached: evaluations === r.maxCandidateEvaluations && !cost.fits, diagnostics: state.diagnostics, budgetContext: { promptPrefix: r.promptPrefix ?? '', promptSuffix: r.promptSuffix ?? '', maxBytes: r.maxBytes, maxTokens: r.maxTokens ?? null, reservedOutputTokens: r.reservedOutputTokens ?? 0, tokenizerId: r.tokenizerId ?? null, requiredRefs: [...(r.requiredRefs ?? [])].sort() } } };
  result.report.resultHash = observationHash({ view: result.view, ledger: result.ledger, budgetContext: result.report.budgetContext });
  if (!cost.fits && r.planRegions) {
    result.partition = planPartitions(observation, r, index);
    if (result.partition.status === 'unrepresentable_under_budget') result.report.status = 'unrepresentable_under_budget';
  }
  return result;
}
function planPartitions(obs, request, index) {
  const queue = sourceRoots(obs, request.roots, index).map(id => [id]), regions = [], unresolved = [], cache = new Map(); let trials = 0;
  function trial(roots) {
    const key = JSON.stringify(roots); if (cache.has(key)) return cache.get(key);
    if (trials >= request.maxPartitionTrials) return null;
    trials++; const value = compactIR(obs, { ...request, roots, planRegions: false }); cache.set(key, value); return value;
  }
  while (queue.length && regions.length < request.maxRegions) {
    const scope = queue.shift(), result = trial(scope);
    if (!result) { queue.unshift(scope); break; }
    if (result.report.fits) {
      // Greedily pack consecutive fitting siblings, recomputing closure.
      let roots = scope, packed = result;
      while (queue.length && index.parent.get(queue[0][0]) === index.parent.get(roots[0])) {
        const combined = trial([...roots, ...queue[0]]); if (!combined?.report.fits) break;
        roots = [...roots, ...queue.shift()]; packed = combined;
      }
      regions.push(packed); continue;
    }
    const id = scope[0], node = obs.nodes[id];
    if (scope.length === 1 && node.children.length && !INDIVISIBLE.has(node.role) && !node.text && !node.value && !node.structure?.opaqueContent && !['code', 'math'].includes(node.structure?.contentKind)) queue.unshift(...node.children.map(child => [child]));
    else unresolved.push({ roots: scope, reason: 'indivisible-evidence-exceeds-budget', encodedBytes: result.report.encodedBytes });
  }
  const status = unresolved.length ? 'unrepresentable_under_budget' : queue.length ? 'limit_reached' : 'planned';
  const sourceIds = descendants(obs, sourceRoots(obs, request.roots, index));
  const owned = new Set(), context = new Set();
  for (const region of regions) for (const [id, node] of Object.entries(region.view.nodes)) (node.membership === 'owned' ? owned : context).add(id);
  const contextOnlySourceIds = index.order.filter(id => sourceIds.has(id) && context.has(id) && !owned.has(id));
  const ownedCoverage = { sourceNodes: sourceIds.size, ownedNodes: [...owned].filter(id => sourceIds.has(id)).length, contextOnlyNodes: contextOnlySourceIds.length, unrepresentedNodes: [...sourceIds].filter(id => !owned.has(id) && !context.has(id)).length };
  return { status, trials, regions, contextOnlySourceIds, ownedCoverage, regionCount: regions.length, duplicatedContextNodes: regions.reduce((sum, region) => sum + region.view.scope.context.length, 0), unplannedScopes: [...unresolved, ...queue.map(roots => ({ roots, reason: 'partition-limit' }))] };
}

/** Expand only admitted same-snapshot evidence and pin it through subsequent reductions. */
export function expandIR(observation, priorResult, gapIds, request = {}) {
  validateObservation(observation); validateView(priorResult?.view);
  if (priorResult.report?.resultHash !== observationHash({ view: priorResult.view, ledger: priorResult.ledger, budgetContext: priorResult.report?.budgetContext ?? null })) throw new TypeError('Expansion accounting integrity mismatch');
  if (priorResult.view.snapshotId !== observation.snapshotId || priorResult.view.observationHash !== observationHash(observation)) throw new TypeError('Stale expansion snapshot');
  if (!Array.isArray(gapIds) || !gapIds.length) throw new TypeError('Expansion requires gap IDs');
  const previousBudget = priorResult.report?.budgetContext;
  if (!previousBudget && priorResult.report?.completePromptBytes !== priorResult.report?.encodedBytes) throw new TypeError('Expansion requires the original prompt budget context');
  for (const key of ['promptPrefix', 'promptSuffix']) if (has(request, key) && typeof request[key] !== 'string') throw new TypeError(`Invalid expansion ${key}`);
  for (const key of ['maxBytes', 'maxTokens', 'reservedOutputTokens']) if (has(request, key) && (!Number.isSafeInteger(request[key]) || request[key] < 0)) throw new TypeError(`Invalid expansion ${key}`);
  const priorMaxTokens = previousBudget?.maxTokens ?? priorResult.report?.maxTokens;
  const priorTokenizerId = previousBudget?.tokenizerId ?? priorResult.report?.tokenizerId;
  const tokenBudgeted = priorMaxTokens !== null && priorMaxTokens !== undefined;
  if (tokenBudgeted && !request.measureTokens) throw new TypeError('Token-budgeted expansion requires the exact tokenizer callback');
  if (tokenBudgeted && has(request, 'tokenizerId') && request.tokenizerId !== priorTokenizerId) throw new TypeError('Expansion tokenizerId must match the original token budget');
  const required = new Set([...(request.requiredRefs ?? []), ...(previousBudget?.requiredRefs ?? [])]);
  if (new Set(gapIds).size !== gapIds.length) throw new TypeError('Duplicate expansion gaps');
  for (const gapId of gapIds) {
    const gap = priorResult.view.gaps.find(g => g.id === gapId), detail = priorResult.ledger?.gaps?.[gapId];
    if (!gap || gap.expansion !== 'local' || !detail || detail.owner !== gap.owner || detail.field !== gap.field) throw new TypeError('Unknown or unavailable expansion gap');
    if (detail.nodeIds) {
      const permitted = descendants(observation, observation.nodes[gap.owner].children);
      if (detail.nodeIds.length !== gap.omittedNodes || new Set(detail.nodeIds).size !== detail.nodeIds.length) throw new TypeError('Invalid expansion node accounting');
      for (const id of detail.nodeIds) { if (!permitted.has(id) || has(priorResult.view.nodes, id)) throw new TypeError('Invalid expansion node'); required.add(id); }
    }
    else if (gap.field === 'text') {
      const text = observation.nodes[gap.owner]?.text;
      if (typeof text !== 'string' || !Number.isInteger(detail.start) || !Number.isInteger(detail.end) || detail.start < 0 || detail.end > text.length || detail.start >= detail.end) throw new TypeError('Invalid expansion range');
      if (detail.end - detail.start !== gap.omittedCharacters || textCut(text, detail.start) !== detail.start || textCut(text, detail.end) !== detail.end) throw new TypeError('Invalid expansion range accounting');
      const shown = priorResult.view.nodes[gap.owner].text;
      if (shown?.kind !== 'extract' || shown.parts.length !== 2 || shown.parts[0].text !== text.slice(0, detail.start) || shown.parts[1].gap !== gapId || detail.end !== text.length) throw new TypeError('Expansion does not match admitted source excerpt');
      required.add(gap.owner);
    } else throw new TypeError('Unsupported expansion field');
  }
  const result = compactIR(observation, {
    profile: priorResult.view.profile, roots: priorResult.view.scope.roots,
    maxBytes: previousBudget?.maxBytes ?? priorResult.report?.maxBytes ?? 200000,
    promptPrefix: previousBudget?.promptPrefix ?? '', promptSuffix: previousBudget?.promptSuffix ?? '',
    reservedOutputTokens: previousBudget?.reservedOutputTokens ?? priorResult.report?.reservedOutputTokens ?? 0,
    ...(tokenBudgeted ? { maxTokens: priorMaxTokens, tokenizerId: priorTokenizerId } : {}),
    ...request, requiredRefs: [...required],
  });
  result.report.expandedRefs = [...required].sort();
  return result;
}
