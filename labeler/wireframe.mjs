// Wireframe of a page drawn from captured geometry, and selection over it.
// Boxes are compact nodes that have a captured rect; coordinates are page CSS pixels.

export function boxes(model) {
  const raw = new Map(model.raw.nodes.map(n => [n.id, n]));
  return model.compact.nodes.flatMap(n => {
    const r = raw.get(n.id);
    return r?.rect && r.rect.width > 0 && r.rect.height > 0 ? [{ id: n.id, tag: n.tag, text: n.ownText, rect: r.rect, style: r.style }] : [];
  });
}

/** Compact nodes lying wholly inside `area`, keeping only the outermost of nested matches. */
export function rectSelect(list, area, parentOf) {
  const inside = list.filter(({ rect: r }) => r.x >= area.x && r.y >= area.y &&
    r.x + r.width <= area.x + area.width && r.y + r.height <= area.y + area.height).map(b => b.id);
  const chosen = new Set(inside);
  return inside.filter(id => { for (let p = parentOf(id); p; p = parentOf(p)) if (chosen.has(p)) return false; return true; });
}

/** The smallest box under a point, or null. */
export function hitTest(list, x, y) {
  let best = null;
  for (const b of list) {
    const r = b.rect;
    if (x >= r.x && y >= r.y && x <= r.x + r.width && y <= r.y + r.height && (!best || r.width * r.height < best.rect.width * best.rect.height)) best = b;
  }
  return best?.id ?? null;
}

export function pageSize(list, viewport) {
  const bottom = Math.max(viewport.height, ...list.map(b => b.rect.y + b.rect.height));
  return { width: viewport.width, height: Math.min(Math.ceil(bottom), 30000) };
}
