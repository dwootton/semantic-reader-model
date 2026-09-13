export function indexDataset(data, variantId) {
  const variant = data.variants[variantId];
  if (!variant) throw new Error('This capture has no selected hierarchy variant.');
  const hierarchy = new Map(variant.nodes.map(node => [node.id, node]));
  const dom = new Map(data.dom.nodes.map(node => [node.id, node]));
  const hierarchyParents = new Map();
  const directOwners = new Map();
  for (const node of hierarchy.values()) {
    for (const child of node.children) hierarchyParents.set(child, node.id);
    for (const ref of node.sourceRefs) {
      if (!dom.has(ref)) throw new Error(`Missing source element: ${ref}`);
      if (!directOwners.has(ref)) directOwners.set(ref, new Set());
      directOwners.get(ref).add(node.id);
    }
  }
  return { hierarchy, dom, hierarchyParents, directOwners, rootId: variant.rootId, domRoots: data.dom.roots };
}

export function ancestors(id, parentOf) {
  const result = [];
  const seen = new Set([id]);
  let parent = parentOf(id);
  while (parent && !seen.has(parent)) {
    result.push(parent);
    seen.add(parent);
    parent = parentOf(parent);
  }
  return result;
}

export function hierarchyRefs(index, id, includeChildren = true) {
  const refs = new Set();
  const visited = new Set();
  function visit(key) {
    if (visited.has(key)) return;
    visited.add(key);
    const node = index.hierarchy.get(key);
    if (!node) return;
    node.sourceRefs.forEach(ref => refs.add(ref));
    if (includeChildren) node.children.forEach(visit);
  }
  visit(id);
  return refs;
}

export function domToHierarchy(index, id, includeChildren = true) {
  let source = id;
  let direct = index.directOwners.get(source);
  const seen = new Set();
  while (!direct && source && !seen.has(source)) {
    seen.add(source);
    source = index.dom.get(source)?.parent;
    direct = index.directOwners.get(source);
  }
  const exact = new Set(direct || []);
  const context = new Set();
  if (includeChildren) {
    for (const owner of exact) {
      for (const parent of ancestors(owner, key => index.hierarchyParents.get(key))) {
        if (!exact.has(parent)) context.add(parent);
      }
    }
  }
  return { exact, context, viaAncestor: Boolean(source && source !== id), mappedSource: source || null };
}

export function visibleRows(nodes, roots, expanded, query, searchText) {
  const term = query.trim().toLowerCase();
  const retained = new Set();
  const parents = new Map();
  for (const n of nodes.values()) n.children.forEach(c => parents.set(c, n.id));
  if (term) for (const n of nodes.values()) {
    if (searchText(n).toLowerCase().includes(term)) {
      retained.add(n.id);
      ancestors(n.id, id => parents.get(id)).forEach(id => retained.add(id));
    }
  }
  const rows = [];
  const seen = new Set();
  function walk(id, depth, position, total) {
    const node = nodes.get(id);
    if (!node || seen.has(id) || (term && !retained.has(id))) return;
    seen.add(id);
    const children = node.children.filter(c => nodes.has(c) && (!term || retained.has(c)));
    const open = children.length > 0 && (Boolean(term) || expanded.has(id));
    rows.push({ node, depth, open, hasChildren: children.length > 0, position, total });
    if (open) children.forEach((child, i) => walk(child, depth + 1, i + 1, children.length));
  }
  const visibleRoots = roots.filter(r => !term || retained.has(r));
  visibleRoots.forEach((root, i) => walk(root, 0, i + 1, visibleRoots.length));
  return rows;
}

export function screenshotBounds(dom, refs, screenshot) {
  if (!screenshot) return [];
  const width = screenshot.width, height = screenshot.height;
  return [...refs].flatMap(id => {
    const r = dom.get(id)?.rect;
    if (!r || r.width <= 0 || r.height <= 0) return [];
    // Captured getBoundingClientRect coordinates already refer to that viewport.
    const x = Math.max(0, r.x), y = Math.max(0, r.y);
    const right = Math.min(width, r.x + r.width), bottom = Math.min(height, r.y + r.height);
    if (right <= x || bottom <= y) return [];
    return [{ id, x: x / width * 100, y: y / height * 100,
      width: (right - x) / width * 100, height: (bottom - y) / height * 100 }];
  });
}
