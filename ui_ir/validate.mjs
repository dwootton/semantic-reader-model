import { createHash } from 'node:crypto';
import { ROLES, RELATIONS, ACTIONS, BOOLEAN_STATES, COVERAGE, PROFILE, NODE_KEYS, GAP_FIELDS } from './registries.mjs';

export class IRValidationError extends Error {
  constructor(message, code = 'invalid_ir') { super(message); this.name = 'IRValidationError'; this.code = code; }
}
const fail = (message, code) => { throw new IRValidationError(message, code); };
const object = (v, path) => { if (!v || typeof v !== 'object' || Array.isArray(v)) fail(`${path}: expected object`); };
const string = (v, path, empty = false) => { if (typeof v !== 'string' || (!empty && !v.length)) fail(`${path}: expected ${empty ? '' : 'nonempty '}string`); };
const array = (v, path) => { if (!Array.isArray(v)) fail(`${path}: expected array`); };
const member = (value, choices, path) => { if (!choices.has(value)) fail(`${path}: unsupported value`); };
const exactKeys = (value, keys, path) => { for (const key of Object.keys(value)) if (!keys.has(key)) fail(`${path}: unknown field ${key}`); };
const has = (o, k) => Object.hasOwn(o, k);
const finite = (v, path) => { if (typeof v !== 'number' || !Number.isFinite(v)) fail(`${path}: expected finite number`); };
const bool = (v, path) => { if (typeof v !== 'boolean') fail(`${path}: expected boolean`); };
const id = (v, path) => { string(v, path); if (v.length > 512) fail(`${path}: ID too long`); };
const unique = (a, path) => { if (new Set(a).size !== a.length) fail(`${path}: duplicate IDs`); };

export function stableStringify(value) {
  const active = new Set();
  function normalize(v, depth) {
    if (depth > 128) fail('JSON nesting limit exceeded', 'input_limit');
    if (v === null || typeof v === 'string' || typeof v === 'boolean') return v;
    if (typeof v === 'number') { finite(v, 'JSON number'); return v; }
    if (typeof v !== 'object') fail('Only JSON values are supported');
    if (active.has(v)) fail('Circular JSON value');
    active.add(v);
    let result;
    if (Array.isArray(v)) result = v.map(x => normalize(x, depth + 1));
    else {
      const proto = Object.getPrototypeOf(v);
      if (proto !== Object.prototype && proto !== null) fail('Only plain JSON objects are supported');
      result = Object.create(null);
      for (const key of Object.keys(v).sort()) result[key] = normalize(v[key], depth + 1);
    }
    active.delete(v); return result;
  }
  return JSON.stringify(normalize(value, 0));
}

export const observationHash = observation => createHash('sha256').update(stableStringify(observation)).digest('hex');
export function deepFreeze(value) {
  const stack = [value], seen = new Set();
  while (stack.length) {
    const v = stack.pop();
    if (!v || typeof v !== 'object' || seen.has(v)) continue;
    seen.add(v); for (const child of Object.values(v)) stack.push(child); Object.freeze(v);
  }
  return value;
}

function coverage(v, path, complete = false) {
  object(v, path); exactKeys(v, new Set(['children', 'names', 'actions', 'relations', 'text']), path);
  for (const key of ['children', 'names', 'actions', 'relations']) {
    if (complete || has(v, key)) member(v[key], COVERAGE, `${path}.${key}`);
  }
  if (has(v, 'text')) member(v.text, COVERAGE, `${path}.text`);
}

function commonNode(n, path, view) {
  object(n, path); exactKeys(n, new Set([...NODE_KEYS, ...(view ? ['membership'] : [])]), path);
  member(n.role, ROLES, `${path}.role`); array(n.children, `${path}.children`);
  for (const key of ['name', 'description']) if (has(n, key)) {
    object(n[key], `${path}.${key}`); exactKeys(n[key], new Set(['text', 'basis']), `${path}.${key}`);
    string(n[key].text, `${path}.${key}.text`, true); member(n[key].basis, new Set(['browser', 'explicit']), `${path}.${key}.basis`);
  }
  if (has(n, 'value')) {
    const v = n.value; object(v, `${path}.value`);
    if (v.kind === 'text') { exactKeys(v, new Set(['kind', 'text']), path); string(v.text, `${path}.value.text`, true); }
    else if (v.kind === 'number') {
      exactKeys(v, new Set(['kind', 'current', 'min', 'max', 'step', 'displayText']), path);
      for (const key of ['current', 'min', 'max', 'step']) if (has(v, key)) finite(v[key], `${path}.value.${key}`);
      if (has(v, 'step') && v.step <= 0) fail(`${path}: step must be positive`);
      if (has(v, 'min') && has(v, 'max') && v.min > v.max) fail(`${path}: inverted limits`);
      if (has(v, 'displayText')) string(v.displayText, path, true);
    } else fail(`${path}: unknown value kind`);
  }
  if (has(n, 'states')) {
    object(n.states, `${path}.states`);
    for (const [key, value] of Object.entries(n.states)) {
      if (BOOLEAN_STATES.has(key)) bool(value, `${path}.states.${key}`);
      else if (['checked', 'pressed'].includes(key)) { if (typeof value !== 'boolean' && value !== 'mixed') fail(`${path}: invalid ${key}`); }
      else if (key === 'invalid') { if (typeof value !== 'boolean' && !['grammar', 'spelling'].includes(value)) fail(`${path}: invalid invalid state`); }
      else if (key === 'current') { if (typeof value !== 'boolean' && !['page', 'step', 'location', 'date', 'time'].includes(value)) fail(`${path}: invalid current`); }
      else fail(`${path}: unknown state ${key}`);
    }
  }
  if (has(n, 'actions')) {
    array(n.actions, path);
    for (const action of n.actions) {
      object(action, path); exactKeys(action, new Set(['kind', 'basis']), path);
      member(action.kind, ACTIONS, path); member(action.basis, new Set(['reported', 'native-semantics']), path);
    }
  }
  if (has(n, 'destination')) {
    object(n.destination, path); exactKeys(n.destination, new Set(['id', 'label']), path);
    id(n.destination.id, path); if (has(n.destination, 'label')) string(n.destination.label, path, true);
  }
  if (has(n, 'labelHints')) {
    array(n.labelHints, path);
    for (const hint of n.labelHints) {
      object(hint, path); exactKeys(hint, new Set(['text', 'basis']), path); string(hint.text, path, true);
      member(hint.basis, new Set(['title', 'placeholder', 'source-label']), path);
    }
  }
  if (has(n, 'language')) string(n.language, path);
  if (has(n, 'direction')) member(n.direction, new Set(['ltr', 'rtl', 'auto']), path);
  if (has(n, 'coverage')) coverage(n.coverage, path);
  if (has(n, 'exposure')) {
    object(n.exposure, path); exactKeys(n.exposure, new Set(['accessibilityIncluded', 'rendered', 'intersectsViewport', 'inert', 'dormant']), path);
    for (const value of Object.values(n.exposure)) bool(value, path);
  }
  if (has(n, 'structure')) {
    object(n.structure, path);
    const positive = new Set(['level', 'positionInSet', 'rowIndex', 'columnIndex', 'rowSpan', 'columnSpan']);
    const counts = new Set(['setSize', 'rowCount', 'columnCount']);
    for (const [key, value] of Object.entries(n.structure)) {
      if (positive.has(key) || counts.has(key)) { if (!Number.isSafeInteger(value) || value < (positive.has(key) ? 1 : 0)) fail(`${path}: invalid structure.${key}`); }
      else if (key === 'boundary') member(value, new Set(['semantic', 'branching']), path);
      else if (key === 'preserveScope') bool(value, path);
      else if (key === 'textMode') member(value, new Set(['normal', 'verbatim']), path);
      else if (key === 'contentKind') member(value, new Set(['prose', 'code', 'math']), path);
      else if (key === 'opaqueContent') member(value, new Set(['frame', 'shadow', 'media']), path);
      else fail(`${path}: unknown structure.${key}`);
    }
  }
  if (has(n, 'bounds')) {
    object(n.bounds, path); exactKeys(n.bounds, new Set(['x', 'y', 'width', 'height', 'space']), path);
    for (const key of ['x', 'y', 'width', 'height']) finite(n.bounds[key], path);
    if (n.bounds.width < 0 || n.bounds.height < 0) fail(`${path}: negative bounds`);
    string(n.bounds.space, path);
  }
}

function forest(nodes, roots, childrenOf) {
  array(roots, 'roots'); unique(roots, 'roots');
  const parents = new Map();
  let edges = 0;
  for (const [key, n] of Object.entries(nodes)) {
    const children = childrenOf(n); unique(children, `${key}.children`);
    for (const child of children) {
      id(child, 'child'); if (!has(nodes, child)) fail(`Missing child ${child}`);
      if (parents.has(child)) fail(`Multiple parents for ${child}`);
      parents.set(child, key); edges++;
    }
  }
  if (edges > 250000) fail('Edge limit exceeded', 'input_limit');
  for (const root of roots) { id(root, 'root'); if (!has(nodes, root) || parents.has(root)) fail(`Invalid root ${root}`); }
  const seen = new Set(), stack = [...roots];
  while (stack.length) {
    const key = stack.pop(); if (seen.has(key)) fail(`Containment cycle at ${key}`);
    seen.add(key); for (const child of childrenOf(nodes[key])) stack.push(child);
  }
  if (seen.size !== Object.keys(nodes).length) fail('Unreachable or cyclic nodes');
  return parents;
}

function endpoint(target, nodes, gaps, path) {
  object(target, path); const keys = Object.keys(target);
  if (keys.length !== 1) fail(`${path}: exactly one endpoint type required`);
  const key = keys[0]; id(target[key], path);
  if (key === 'node') { if (!has(nodes, target.node)) fail(`${path}: missing node ${target.node}`); }
  else if (key === 'gap' && gaps) { if (!gaps.has(target.gap)) fail(`${path}: missing gap`); }
  else if (key !== 'unresolved') fail(`${path}: invalid endpoint kind`);
}

function relations(value, nodes, gaps) {
  array(value, 'relations'); if (value.length > 250000) fail('Relation limit exceeded', 'input_limit');
  let endpoints = 0;
  for (const r of value) {
    object(r, 'relation'); exactKeys(r, new Set(['from', 'kind', 'targets', 'basis']), 'relation');
    id(r.from, 'relation.from'); if (!has(nodes, r.from)) fail('Missing relation owner');
    member(r.kind, RELATIONS, 'relation.kind'); member(r.basis, new Set(['reported', 'native-semantics']), 'relation.basis');
    array(r.targets, 'relation.targets');
    if (r.kind === 'activeDescendant' && r.targets.length > 1) fail('activeDescendant is singular');
    for (const t of r.targets) { endpoint(t, nodes, gaps, 'relation target'); if (++endpoints > 250000) fail('Relation endpoint limit exceeded', 'input_limit'); }
  }
}

export function validateObservation(obs) {
  object(obs, 'observation');
  exactKeys(obs, new Set(['version', 'snapshotId', 'documents', 'roots', 'nodes', 'relations', 'coverage', 'focusedNode']), 'observation');
  if (obs.version !== 'ui-observation/0.1') fail('Unsupported observation version');
  id(obs.snapshotId, 'snapshotId'); object(obs.nodes, 'nodes');
  if (Object.keys(obs.nodes).length > 100000) fail('Node limit exceeded', 'input_limit');
  for (const [key, node] of Object.entries(obs.nodes)) { id(key, 'node ID'); commonNode(node, key, false); if (has(node, 'text')) string(node.text, `${key}.text`, true); }
  forest(obs.nodes, obs.roots, n => n.children); relations(obs.relations, obs.nodes);
  coverage(obs.coverage, 'coverage', true); array(obs.documents, 'documents');
  const documents = new Set(), roots = [];
  for (const doc of obs.documents) {
    object(doc, 'document'); id(doc.id, 'document.id');
    if (documents.has(doc.id)) fail('Duplicate document ID'); documents.add(doc.id);
    array(doc.roots, 'document.roots'); roots.push(...doc.roots);
    if (!['dom', 'ax', 'uia', 'native', 'synthetic'].includes(doc.containmentBasis)) fail('Unknown containment basis');
    if (doc.coverage) coverage(doc.coverage, 'document.coverage');
  }
  unique(roots, 'document roots');
  if (roots.length !== obs.roots.length || roots.some(r => !obs.roots.includes(r))) fail('Document roots disagree with observation roots');
  if (has(obs, 'focusedNode') && !has(obs.nodes, obs.focusedNode)) fail('Unknown focused node');
  stableStringify(obs); return obs;
}

export function validateView(view) {
  object(view, 'view');
  exactKeys(view, new Set(['version', 'snapshotId', 'observationHash', 'policy', 'profile', 'scope', 'roots', 'contextRoots', 'nodes', 'relations', 'gaps', 'coverage', 'focusedNode']), 'view');
  if (view.version !== 'ui-view/0.1' || view.policy !== 'organizer-floor/0.1') fail('Unsupported view version/policy');
  id(view.snapshotId, 'snapshotId'); if (!/^[a-f0-9]{64}$/.test(view.observationHash)) fail('Invalid observation hash');
  member(view.profile, PROFILE, 'profile'); member(view.coverage, COVERAGE, 'coverage');
  object(view.scope, 'scope'); exactKeys(view.scope, new Set(['roots', 'context']), 'scope');
  array(view.scope.roots, 'scope.roots'); array(view.scope.context, 'scope.context');
  unique(view.scope.roots, 'scope.roots'); unique(view.scope.context, 'scope.context');
  for (const key of view.scope.roots) id(key, 'scope root');
  object(view.nodes, 'nodes'); if (Object.keys(view.nodes).length > 100000) fail('Node limit exceeded', 'input_limit');
  array(view.gaps, 'gaps'); const gaps = new Map();
  for (const g of view.gaps) {
    object(g, 'gap'); exactKeys(g, new Set(['id', 'owner', 'field', 'reason', 'expansion', 'omittedNodes', 'omittedItems', 'omittedCharacters']), 'gap');
    id(g.id, 'gap.id'); if (gaps.has(g.id) || has(view.nodes, g.id)) fail('Duplicate or colliding gap ID'); gaps.set(g.id, g);
    id(g.owner, 'gap.owner'); if (!has(view.nodes, g.owner)) fail('Gap owner absent from view');
    string(g.reason, 'gap.reason'); member(g.field, GAP_FIELDS, 'gap.field'); member(g.expansion, new Set(['local', 'unavailable']), 'gap.expansion');
    for (const k of ['omittedNodes', 'omittedItems', 'omittedCharacters']) if (has(g, k) && (!Number.isSafeInteger(g[k]) || g[k] < 0)) fail('Invalid omitted count');
  }
  const context = [], referencedGaps = new Set();
  for (const [key, n] of Object.entries(view.nodes)) {
    id(key, 'node ID'); commonNode(n, key, true); member(n.membership, new Set(['owned', 'context']), 'membership');
    if (n.membership === 'context') context.push(key);
    for (const c of n.children) {
      endpoint(c, view.nodes, gaps, 'view child');
      if (has(c, 'unresolved')) fail('Unresolved child must be an explicit gap');
      if (c.gap) { referencedGaps.add(c.gap); const g = gaps.get(c.gap); if (g.owner !== key || !['children', 'upstream', 'media'].includes(g.field)) fail('Child gap owner/field mismatch'); }
    }
    if (has(n, 'text')) {
      object(n.text, 'view text');
      if (n.text.kind === 'complete') { exactKeys(n.text, new Set(['kind', 'value']), 'text'); string(n.text.value, 'text.value', true); }
      else if (n.text.kind === 'extract') {
        exactKeys(n.text, new Set(['kind', 'parts']), 'text'); array(n.text.parts, 'text.parts'); let hasGap = false;
        for (const p of n.text.parts) {
          object(p, 'text part'); if (Object.keys(p).length !== 1) fail('Invalid text part');
          if (has(p, 'text')) string(p.text, 'text part', true);
          else if (has(p, 'gap') && gaps.has(p.gap)) {
            const g = gaps.get(p.gap); if (g.owner !== key || g.field !== 'text') fail('Text gap owner/field mismatch');
            hasGap = true; referencedGaps.add(p.gap);
          } else fail('Unknown text part/gap');
        }
        if (!hasGap) fail('Extract without a gap');
      } else fail('Unknown view text kind');
    }
  }
  array(view.roots, 'roots'); array(view.contextRoots, 'contextRoots');
  const parents = forest(view.nodes, [...view.roots, ...view.contextRoots], n => n.children.filter(c => c.node).map(c => c.node));
  for (const r of view.contextRoots) if (view.nodes[r].membership !== 'context') fail('Context root cannot be owned');
  for (const [child, parent] of parents) if (view.nodes[parent].membership === 'context' && view.nodes[child].membership !== 'context') fail('Context subtree cannot own children');
  const contextSet = new Set(view.scope.context);
  if (context.length !== contextSet.size || context.some(k => !contextSet.has(k))) fail('Context membership disagrees with scope');
  relations(view.relations, view.nodes, gaps);
  if (has(view, 'focusedNode') && !has(view.nodes, view.focusedNode)) fail('Unknown focused view node');
  for (const r of view.relations) for (const t of r.targets) if (t.gap) referencedGaps.add(t.gap);
  for (const g of gaps.values()) if (!referencedGaps.has(g.id) && !['upstream', 'media', 'relation'].includes(g.field)) fail('Unreferenced view gap');
  stableStringify(view); return view;
}
