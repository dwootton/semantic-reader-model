// Source identity and tree navigation, independent of rendering.
export function ancestorIds(nodes, id) {
  const result = [], seen = new Set([id]);
  let parent = nodes.get(id)?.parent;
  while (parent != null && nodes.has(parent) && !seen.has(parent)) {
    result.push(parent); seen.add(parent); parent = nodes.get(parent)?.parent;
  }
  return result;
}

function indexTree(tree) {
  const map = new Map();
  for (const node of tree.nodes) {
    if (map.has(node.id)) throw new Error(`Duplicate tree ID: ${node.id}`);
    map.set(node.id, node);
  }
  const reached = new Set();
  const pending = [...tree.roots];
  while (pending.length) {
    const id = pending.pop(), node = map.get(id);
    if (!node || reached.has(id)) throw new Error('Invalid tree: missing node, cycle or repeated membership');
    reached.add(id);
    for (const child of node.children) {
      if (map.get(child)?.parent !== id) throw new Error(`Inconsistent tree edge: ${id}`);
      pending.push(child);
    }
  }
  if (reached.size !== map.size) throw new Error('Tree has unreachable nodes');
  return map;
}

export function indexData(data, profile) {
  const selected = data.profiles[profile];
  if (!selected) throw new Error(`No ${profile} profile in this capture`);
  const source = indexTree(data.source), compressed = indexTree(selected.tree);
  const ledger = new Map(selected.sourceMap.map(item => [item.id, item]));
  if (ledger.size !== selected.sourceMap.length || ledger.size !== source.size) throw new Error('Source map does not cover the original tree');
  const compressedBySource = new Map();
  for (const item of ledger.values()) if (!source.has(item.id)) throw new Error('Unknown source-map ID');
  for (const node of compressed.values()) {
    if (node.sourceId == null) continue;
    if (!source.has(node.sourceId)) throw new Error(`Unknown compressed source reference: ${node.sourceId}`);
    if (!compressedBySource.has(node.sourceId)) compressedBySource.set(node.sourceId, []);
    compressedBySource.get(node.sourceId).push(node.id);
  }
  return {source, compressed, ledger, compressedBySource,
    sourceRoots: data.source.roots, compressedRoots: selected.tree.roots};
}

export function matchNode(index, side, rowId) {
  if (!['source', 'compressed'].includes(side)) throw new Error('Unknown tree side');
  const row = index[side].get(rowId);
  if (!row) throw new Error('Unknown tree node');
  const sourceId = side === 'source' ? rowId : row.sourceId;
  const sourceRowId = index.source.has(sourceId) ? sourceId : null;
  const entry = index.ledger.get(sourceId);
  const matches = index.compressedBySource.get(sourceId) || [];
  const base = {sourceId: sourceId ?? null, sourceRowId, compressedRowId: side === 'compressed' ? rowId : null,
    disposition: entry?.disposition ?? 'unknown', reason: ''};
  if (!sourceRowId) return {...base, kind:'absent', reason:'This output node has no verified source reference.'};
  if (matches.length > 1) return {...base,
    compressedRowId: side === 'compressed' ? rowId : null,
    kind:'ambiguous', reason:'Multiple output nodes reference this source. There is no unique compressed counterpart.'};
  if (matches.length === 1) return {...base, compressedRowId:matches[0], kind:'exact',
    reason: entry?.reasons?.length ? 'Same source element; inspect its text, attributes and compression rules below.' : 'Same source element in both trees.'};
  const representative = entry?.representedBy;
  const representatives = index.compressedBySource.get(representative) || [];
  if (representative !== sourceId && representatives.length === 1) return {...base,
    compressedRowId: representatives[0], kind:'representative',
    reason:`No exact counterpart: this element was ${entry?.disposition ?? 'omitted'}. Its containing compressed group is highlighted.`};
  return {...base, kind:'absent', reason: entry?.disposition === 'excluded'
    ? 'Excluded from model input. No compressed counterpart.'
    : 'No verified compressed counterpart is present.'};
}

const searchCache = new WeakMap();
function searchable(node) {
  if (!searchCache.has(node)) searchCache.set(node,
    [node.id, node.sourceId, node.tag, node.text, ...Object.entries(node.attributes || {}).flat()].join(' ').toLowerCase());
  return searchCache.get(node);
}

export function treeRows(nodes, roots, expanded, query = '') {
  const term = query.trim().toLowerCase(), included = new Set();
  if (term) for (const node of nodes.values()) if (searchable(node).includes(term)) {
    included.add(node.id); ancestorIds(nodes, node.id).forEach(id => included.add(id));
  }
  const rows = [], pending = roots.map(id => [id, 0]).reverse();
  while (pending.length) {
    const [id, depth] = pending.pop(), node = nodes.get(id);
    if (!node || (term && !included.has(id))) continue;
    const childIds = node.children.filter(id => nodes.has(id) && (!term || included.has(id)));
    const open = childIds.length > 0 && (Boolean(term) || expanded.has(id));
    rows.push({node, depth, open, hasChildren:childIds.length > 0});
    if (open) for (let i=childIds.length-1;i>=0;i--) pending.push([childIds[i], depth+1]);
  }
  return rows;
}
