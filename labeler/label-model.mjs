// The semantic tree being labeled, and every edit the labeler can make to it. Pure: no DOM, no fetch.
//
// A label is { rootId, nodes: {id: node}, skipped: {compactId: reason}, notes, next }.
// Nodes use the inspector's variant shape (as in examples/banana-bread): groups are
// { kind: 'group', label, summary, children, sourceRefs: [] } and leaves (reading units) are
// { kind: 'dom', sourceRefs: [compactId] }. A leaf covers its compact node's whole subtree.
// Compact node IDs are raw element IDs (`src-…`), so saved sourceRefs point at the raw DOM.
// Operations mutate the label and throw an Error with a readable message when refused;
// the UI snapshots before each operation and restores the snapshot on error.

const INTERACTIVE = new Set(['a', 'button', 'input', 'select', 'textarea', 'img', 'svg', 'iframe', 'video',
  'audio', 'canvas', 'summary', 'object', 'embed']);

export function pageIndex(model) {
  const byId = new Map(model.compact.nodes.map(n => [n.id, n]));
  const order = new Map(model.compact.nodes.map((n, i) => [n.id, i]));
  const raw = new Map(model.raw.nodes.map(n => [n.id, n]));
  const content = new Map();
  const hasContent = id => {
    if (!content.has(id)) {
      const n = byId.get(id);
      content.set(id, Boolean(n.ownText) || INTERACTIVE.has(n.tag) || n.children.some(hasContent));
    }
    return content.get(id);
  };
  const title = model.compact.nodes.find(n => n.tag === 'title');
  return { model, byId, order, raw, hasContent, titleId: title?.id ?? null };
}

export const isContent = (ctx, id) => { const n = ctx.byId.get(id); return Boolean(n.ownText) || INTERACTIVE.has(n.tag); };

export function unitText(ctx, id) {
  const n = ctx.byId.get(id), a = n.attributes || {};
  return n.ownText || a['aria-label'] || a.alt || a.title || a.placeholder || ctx.raw.get(id)?.text || `<${n.tag}>`;
}

function ancestorsOf(ctx, id) {
  const out = [];
  for (let p = ctx.byId.get(id)?.parent; p; p = ctx.byId.get(p)?.parent) out.push(p);
  return out;
}
const inside = (ctx, id, container) => id === container || ancestorsOf(ctx, id).includes(container);
const byOrder = ctx => (a, b) => ctx.order.get(a) - ctx.order.get(b);

export function newLabel(ctx) {
  const titleText = ctx.titleId ? unitText(ctx, ctx.titleId) : ctx.model.url;
  return { rootId: 'page', next: 1, skipped: {}, notes: '', nodes: {
    page: { id: 'page', kind: 'group', label: titleText, summary: '', children: [],
      sourceRefs: ctx.titleId ? [ctx.titleId] : [], origin: 'inferred', label_origin: 'source' } } };
}

export function parents(label) {
  const map = new Map();
  for (const n of Object.values(label.nodes)) for (const c of n.children) map.set(c, n.id);
  return map;
}

function leafMap(label) {
  const map = new Map();
  for (const n of Object.values(label.nodes)) if (n.kind === 'dom') map.set(n.sourceRefs[0], n.id);
  return map;
}

function group(label, id) {
  const node = label.nodes[id];
  if (!node || node.kind !== 'group') throw new Error('Choose a group to add to.');
  return node;
}

function detach(label, id) {
  const parent = parents(label).get(id);
  if (parent) label.nodes[parent].children = label.nodes[parent].children.filter(c => c !== id);
  return parent;
}

function makeLeaf(label, ctx, compactId) {
  const node = ctx.byId.get(compactId), raw = ctx.raw.get(compactId);
  const id = `leaf-${compactId}`;
  label.nodes[id] = { id, kind: 'dom', label: unitText(ctx, compactId).slice(0, 160), summary: '', children: [],
    sourceRefs: [compactId], origin: 'source', reading_text: (raw?.text || node.ownText || '').slice(0, 400),
    display_role: node.attributes?.role || node.tag };
  return id;
}

// Where a node sits in reading order: its earliest unit's position in the document.
function firstOrder(label, ctx, id) {
  const n = label.nodes[id];
  if (n.kind === 'dom') return ctx.order.get(n.sourceRefs[0]) ?? Infinity;
  return Math.min(Infinity, ...n.children.map(c => firstOrder(label, ctx, c)));
}

// New units and groups go where their content sits in the document; manual moves can change that later.
function insertSorted(label, ctx, parentId, id) {
  const list = label.nodes[parentId].children;
  const position = firstOrder(label, ctx, id);
  const at = list.findIndex(c => firstOrder(label, ctx, c) > position);
  list.splice(at < 0 ? list.length : at, 0, id);
}

// Put `id` into a group before its child `before`; null or a missing child appends at the end.
function insertBefore(label, parentId, id, before) {
  const list = label.nodes[parentId].children;
  const at = before == null ? -1 : list.indexOf(before);
  list.splice(at < 0 ? list.length : at, 0, id);
}

// Node IDs in the order they appear in the tree.
function treeOrder(label) {
  const out = [];
  const walk = id => { out.push(id); label.nodes[id].children.forEach(walk); };
  walk(label.rootId);
  return out;
}

const outermost = (ctx, ids) => ids.filter(id => !ids.some(other => other !== id && inside(ctx, id, other)));

// Replace a leaf with leaves for each content-bearing compact child, in place.
function splitInPlace(label, ctx, leafId) {
  const ref = label.nodes[leafId].sourceRefs[0];
  const kids = ctx.byId.get(ref).children.filter(ctx.hasContent);
  if (!kids.length) throw new Error(`"${label.nodes[leafId].label}" has nothing inside to split into.`);
  const parent = parents(label).get(leafId);
  const siblings = label.nodes[parent].children;
  delete label.nodes[leafId];
  siblings.splice(siblings.indexOf(leafId), 1, ...kids.map(k => makeLeaf(label, ctx, k)));
}

// Split the leaf covering `target` down the path until `target` is its own leaf.
function splitTo(label, ctx, leafId, target) {
  let current = leafId;
  for (;;) {
    const ref = label.nodes[current].sourceRefs[0];
    if (ref === target) return current;
    const next = [target, ...ancestorsOf(ctx, target)].find(id => ctx.byId.get(id)?.parent === ref);
    splitInPlace(label, ctx, current);
    current = `leaf-${next}`;
  }
}

function coveringLeaf(ctx, leaves, id) {
  for (const candidate of [id, ...ancestorsOf(ctx, id)]) if (leaves.has(candidate)) return leaves.get(candidate);
  return null;
}

function skippedBy(label, ctx, id) {
  return [id, ...ancestorsOf(ctx, id)].find(candidate => candidate in label.skipped) || null;
}

/**
 * Place compact nodes as reading units in a group. Existing units move; enclosing units are split.
 * `before` (a child of the group, or null for the end) places them exactly; omitted, they go in document order.
 */
export function addLeaves(label, ctx, compactIds, targetId, before) {
  group(label, targetId);
  const ids = outermost(ctx, [...new Set(compactIds)]).sort(byOrder(ctx));
  if (!ids.length) throw new Error('Select compressed nodes first.');
  for (const id of ids) {
    const skip = skippedBy(label, ctx, id);
    if (skip && skip !== id) throw new Error(`<${ctx.byId.get(id).tag}> is inside a skipped node; unskip it first.`);
    const leaves = leafMap(label);
    if (!leaves.has(id) && [...leaves.keys()].some(ref => ref !== id && inside(ctx, ref, id))) {
      throw new Error(`"${unitText(ctx, id).slice(0, 60)}" contains nodes already placed. Use "Make one unit" to merge them.`);
    }
  }
  for (const id of ids) {
    delete label.skipped[id];
    const leaves = leafMap(label);
    const cover = coveringLeaf(ctx, leaves, id);
    const leafId = cover ? splitTo(label, ctx, cover, id) : makeLeaf(label, ctx, id);
    if (before !== undefined) { if (leafId !== before) { detach(label, leafId); insertBefore(label, targetId, leafId, before); } }
    else if (parents(label).get(leafId) !== targetId) { detach(label, leafId); insertSorted(label, ctx, targetId, leafId); }
  }
}

/** Place each content-bearing compact child of the selected nodes as its own reading unit. */
export function addChildren(label, ctx, compactIds, targetId) {
  const leaves = leafMap(label);
  const kids = [];
  for (const id of compactIds) {
    if (leaves.has(id)) { detach(label, leaves.get(id)); delete label.nodes[leaves.get(id)]; }
    kids.push(...ctx.byId.get(id).children.filter(ctx.hasContent));
  }
  if (!kids.length) throw new Error('The selection has no children with content.');
  addLeaves(label, ctx, kids, targetId);
}

/** Make one compact node a single reading unit, absorbing any units inside it. */
export function makeUnit(label, ctx, compactId, targetId) {
  const leaves = leafMap(label);
  const absorbed = [...leaves.keys()].filter(ref => ref !== compactId && inside(ctx, ref, compactId)).sort(byOrder(ctx));
  if (!absorbed.length) return addLeaves(label, ctx, [compactId], targetId);
  const first = leaves.get(absorbed[0]);
  const parent = parents(label).get(first);
  const position = label.nodes[parent].children.indexOf(first);
  for (const ref of absorbed) { detach(label, leaves.get(ref)); delete label.nodes[leaves.get(ref)]; }
  for (const id of Object.keys(label.skipped)) if (inside(ctx, id, compactId)) delete label.skipped[id];
  const leafId = leaves.has(compactId) ? leaves.get(compactId) : makeLeaf(label, ctx, compactId);
  label.nodes[parent].children.splice(position, 0, leafId);
}

function siblingIds(ctx, id) {
  const parent = ctx.byId.get(id).parent;
  return parent ? ctx.byId.get(parent).children : ctx.model.compact.roots;
}
// Shape of a node: its tag and its children's tags, so cards built the same way match.
const shape = (ctx, id) => { const n = ctx.byId.get(id); return `${n.tag}>${n.children.map(c => ctx.byId.get(c).tag).join(',')}`; };

/** Every sibling of each node (including the nodes), in document order. */
export function selectSiblings(ctx, ids) {
  return [...new Set(ids.flatMap(id => siblingIds(ctx, id)))].sort(byOrder(ctx));
}

/** Siblings shaped like each node: same tag and the same child tags, e.g. the other cards of a card list. */
export function selectSimilar(ctx, ids) {
  return [...new Set(ids.flatMap(id => siblingIds(ctx, id).filter(s => shape(ctx, s) === shape(ctx, id))))].sort(byOrder(ctx));
}

// The first text inside a node, in document order (a card's title, usually).
function firstText(ctx, id) {
  const n = ctx.byId.get(id);
  if (n.ownText) return n.ownText;
  for (const c of n.children) { const t = firstText(ctx, c); if (t) return t; }
  return '';
}

/** One group per selected node, named from its first text, holding its children as units (or itself, if it has none). */
export function groupEach(label, ctx, compactIds, targetId) {
  const ids = outermost(ctx, [...new Set(compactIds)]).sort(byOrder(ctx));
  if (!ids.length) throw new Error('Select compressed nodes first.');
  return ids.map(id => {
    const kids = ctx.byId.get(id).children.filter(ctx.hasContent);
    const g = createGroup(label, targetId, (firstText(ctx, id) || unitText(ctx, id)).slice(0, 120));
    if (kids.length) addChildren(label, ctx, [id], g); else addLeaves(label, ctx, [id], g);
    detach(label, g);
    insertSorted(label, ctx, targetId, g);
    return g;
  });
}

export function createGroup(label, parentId, text, index = null) {
  group(label, parentId);
  const id = `g${label.next++}`;
  label.nodes[id] = { id, kind: 'group', label: text.trim() || 'Untitled group', summary: '', children: [],
    sourceRefs: [], origin: 'inferred', label_origin: 'human' };
  const siblings = label.nodes[parentId].children;
  siblings.splice(index === null ? siblings.length : index, 0, id);
  return id;
}

export function groupCompact(label, ctx, compactIds, targetId, text, children = false) {
  const id = createGroup(label, targetId, text);
  (children ? addChildren : addLeaves)(label, ctx, compactIds, id);
  detach(label, id);
  insertSorted(label, ctx, targetId, id);
  return id;
}

function siblings(label, ids) {
  if (!ids.length) throw new Error('Select tree nodes first.');
  if (ids.includes(label.rootId)) throw new Error('The page root cannot be moved.');
  const map = parents(label);
  const parent = map.get(ids[0]);
  if (!ids.every(id => map.get(id) === parent)) throw new Error('Select nodes that share one parent.');
  const list = label.nodes[parent].children;
  return { parent, list, indexes: ids.map(id => list.indexOf(id)).sort((a, b) => a - b) };
}

export function groupNodes(label, ids, text) {
  const { parent, list, indexes } = siblings(label, ids);
  const members = indexes.map(i => list[i]);
  const id = createGroup(label, parent, text, indexes[0]);
  label.nodes[parent].children = label.nodes[parent].children.filter(c => !members.includes(c));
  label.nodes[id].children = members;
  return id;
}

export function unwrap(label, id) {
  const node = label.nodes[id];
  if (id === label.rootId || node?.kind !== 'group') throw new Error('Select a group (not the page root) to unwrap.');
  const parent = parents(label).get(id);
  const list = label.nodes[parent].children;
  list.splice(list.indexOf(id), 1, ...node.children);
  delete label.nodes[id];
}

export function merge(label, ids) {
  if (ids.length < 2 || ids.some(id => label.nodes[id]?.kind !== 'group' || id === label.rootId)) {
    throw new Error('Select two or more groups to merge.');
  }
  const [keep, ...rest] = ids;
  for (const id of rest) {
    label.nodes[keep].children.push(...label.nodes[id].children);
    detach(label, id);
    delete label.nodes[id];
  }
}

export function move(label, ids, delta) {
  const { list, indexes } = siblings(label, ids);
  const chosen = new Set(indexes.map(i => list[i]));
  for (const i of delta < 0 ? indexes : [...indexes].reverse()) {
    const j = i + delta;
    if (j < 0 || j >= list.length || chosen.has(list[j])) continue;
    [list[i], list[j]] = [list[j], list[i]];
  }
}

export function indent(label, ids) {
  const { list, indexes } = siblings(label, ids);
  const previous = list[indexes[0] - 1];
  if (!previous || label.nodes[previous].kind !== 'group') throw new Error('Indent needs a group just above the selection.');
  moveTo(label, indexes.map(i => list[i]), previous);
}

export function outdent(label, ids) {
  const { parent, list, indexes } = siblings(label, ids);
  if (parent === label.rootId) throw new Error('Already at the top level.');
  const grand = parents(label).get(parent);
  const members = indexes.map(i => list[i]);
  label.nodes[parent].children = list.filter(c => !members.includes(c));
  const at = label.nodes[grand].children.indexOf(parent) + 1;
  label.nodes[grand].children.splice(at, 0, ...members);
}

/** Move tree nodes into a group, before its child `before` (null: at the end), keeping their tree order. */
export function moveTo(label, ids, groupId, before = null) {
  group(label, groupId);
  const map = parents(label);
  for (let p = groupId; p; p = map.get(p)) if (ids.includes(p)) throw new Error('Cannot move a group into itself.');
  if (ids.includes(label.rootId)) throw new Error('The page root cannot be moved.');
  if (before != null && ids.includes(before)) {
    const list = label.nodes[map.get(before)].children;
    before = list.slice(list.indexOf(before) + 1).find(c => !ids.includes(c)) ?? null;
  }
  const order = treeOrder(label);
  for (const id of [...ids].sort((a, b) => order.indexOf(a) - order.indexOf(b))) {
    detach(label, id);
    insertBefore(label, groupId, id, before);
  }
}

export function remove(label, ids) {
  if (ids.includes(label.rootId)) throw new Error('The page root cannot be removed.');
  const drop = id => { label.nodes[id]?.children.forEach(drop); delete label.nodes[id]; };
  for (const id of ids) { if (label.nodes[id]) { detach(label, id); drop(id); } }
}

export function splitLeaf(label, ctx, id) {
  if (label.nodes[id]?.kind !== 'dom') throw new Error('Select a reading unit to split.');
  splitInPlace(label, ctx, id);
}

export function setField(label, id, field, value) {
  if (!['label', 'summary', 'notes'].includes(field)) throw new Error(`Unknown field ${field}.`);
  if (value) label.nodes[id][field] = value; else if (field === 'notes') delete label.nodes[id].notes; else label.nodes[id][field] = '';
  if (field === 'label') label.nodes[id].label_origin = 'human';
}

export function skip(label, ctx, compactIds, reason) {
  const leaves = leafMap(label);
  for (const id of compactIds) {
    const placed = [...leaves.keys()].find(ref => inside(ctx, ref, id) || inside(ctx, id, ref));
    if (placed) throw new Error(`"${unitText(ctx, id).slice(0, 60)}" overlaps a placed unit; remove that first.`);
  }
  for (const id of compactIds) {
    for (const other of Object.keys(label.skipped)) if (other !== id && inside(ctx, other, id)) delete label.skipped[other];
    label.skipped[id] = reason.trim() || 'skipped';
  }
}

/** Skip every unplaced content node that holds no placed unit, outermost first. Returns how many stay unplaced. */
export function skipUncovered(label, ctx, reason) {
  const units = [...leafMap(label).keys()];
  for (const id of uncovered(label, ctx)) {
    if (skippedBy(label, ctx, id) || units.some(ref => inside(ctx, ref, id))) continue;
    label.skipped[id] = reason.trim() || 'skipped';
  }
  return uncovered(label, ctx).length;
}

export function unskip(label, compactIds) {
  for (const id of compactIds) delete label.skipped[id];
}

/** Per compact node: 'leaf' (a unit itself), 'placed' (inside a unit), 'skipped', or absent. */
export function placement(label, ctx) {
  const state = new Map();
  const mark = (id, value) => { state.set(id, value); ctx.byId.get(id).children.forEach(c => mark(c, value === 'leaf' ? 'placed' : value)); };
  for (const id of Object.keys(label.skipped)) if (ctx.byId.has(id)) mark(id, 'skipped');
  for (const n of Object.values(label.nodes)) if (n.kind === 'dom' && ctx.byId.has(n.sourceRefs[0])) mark(n.sourceRefs[0], 'leaf');
  return state;
}

/** Content-bearing compact nodes that are neither in a unit nor skipped (the page title belongs to the root). */
export function uncovered(label, ctx) {
  const state = placement(label, ctx);
  return ctx.model.compact.nodes.filter(n => n.id !== ctx.titleId && isContent(ctx, n.id) && !state.has(n.id)).map(n => n.id);
}

export function validateLabel(label, ctx) {
  const errors = [], warnings = [];
  const nodes = label.nodes;
  const root = nodes[label.rootId];
  if (!root || root.kind !== 'group') errors.push('The page root is missing.');
  const seen = new Set(), parentCount = new Map();
  const visit = (id, path) => {
    if (path.has(id)) { errors.push(`Cycle at ${id}.`); return; }
    if (seen.has(id)) return;
    seen.add(id);
    const node = nodes[id];
    for (const child of node.children) {
      parentCount.set(child, (parentCount.get(child) || 0) + 1);
      if (!nodes[child]) errors.push(`${id} lists a missing child ${child}.`);
      else visit(child, new Set([...path, id]));
    }
  };
  if (root) visit(label.rootId, new Set());
  for (const id of Object.keys(nodes)) {
    const node = nodes[id];
    if (!seen.has(id)) errors.push(`"${node.label}" is not connected to the page.`);
    if ((parentCount.get(id) || 0) > 1) errors.push(`"${node.label}" has more than one parent.`);
    if (node.kind === 'group' && !node.label.trim()) errors.push(`A group (${id}) has no label.`);
    if (node.kind === 'group' && id !== label.rootId && !node.children.length) warnings.push(`Group "${node.label}" is empty.`);
    if (node.kind === 'dom' && (node.sourceRefs.length !== 1 || !ctx.byId.has(node.sourceRefs[0]))) errors.push(`Unit "${node.label}" points at no compressed node.`);
    for (const ref of node.sourceRefs) if (!ctx.raw.has(ref)) errors.push(`"${node.label}" references unknown element ${ref}.`);
  }
  const refs = Object.values(nodes).filter(n => n.kind === 'dom').map(n => n.sourceRefs[0]).filter(r => ctx.byId.has(r));
  const refSet = new Set(refs);
  if (refSet.size !== refs.length) errors.push('Two units reference the same element.');
  for (const ref of refSet) {
    if (ancestorsOf(ctx, ref).some(a => refSet.has(a))) errors.push(`Unit "${unitText(ctx, ref).slice(0, 60)}" sits inside another unit.`);
  }
  const missing = uncovered(label, ctx).length;
  if (missing) warnings.push(`${missing} compressed nodes with content are not placed or skipped.`);
  return { errors, warnings };
}

/** The saved form: the inspector variant shape plus provenance (see docs/design/gold-labeling-tool-v0.md). */
export function toSaved(label, ctx, status) {
  const ordered = [];
  const walk = id => { const { id: nodeId, ...rest } = label.nodes[id]; ordered.push({ id: nodeId, ...rest }); label.nodes[id].children.forEach(walk); };
  walk(label.rootId);
  const loose = Object.keys(label.nodes).filter(id => !ordered.some(n => n.id === id));
  loose.forEach(id => ordered.push(label.nodes[id]));
  return { page: ctx.model.page, rootId: label.rootId, nodes: ordered,
    provenance: { status, tool: 'labeler phase 2', skipped: label.skipped, notes: label.notes, next: label.next,
      capture: { url: ctx.model.url, document_sha256: ctx.model.documentSha256 || null } } };
}

export function fromSaved(saved) {
  const p = saved.provenance || {};
  const nodes = Object.fromEntries(saved.nodes.map(n => [n.id, structuredClone(n)]));
  const next = p.next || 1 + Math.max(0, ...Object.keys(nodes).filter(id => /^g\d+$/.test(id)).map(id => Number(id.slice(1))));
  return { rootId: saved.rootId, nodes, skipped: { ...(p.skipped || {}) }, notes: p.notes || '', next };
}

/** A full inspector dataset (banana-bread layout) for `inspector/build_data.py --import-datasets`. */
export function toDataset(model, saved) {
  const id = `label-${model.page.split('/')[1]}`;
  return { id, label: `${saved.nodes[0].label} · labeled`, url: model.url,
    dom: { roots: model.raw.roots, nodes: model.raw.nodes.map(({ compact, style, textBoxes, invisible, ...node }) => node) },
    variants: { gold: { rootId: saved.rootId, nodes: saved.nodes } },
    variantLabels: { gold: 'Labeler gold (human)' }, screenshot: null,
    limitations: ['Media-suppressed corpus capture; no screenshot.', 'Hand-labeled in the semantic labeler from the compressed DOM.'],
    provenance: { page: model.page, ...saved.provenance } };
}
