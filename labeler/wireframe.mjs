// Wireframe of a page drawn from captured geometry, and selection over it.
// Boxes are compact nodes that have a captured rect; coordinates are page CSS pixels.

export function boxes(model) {
  const raw = new Map(model.raw.nodes.map(n => [n.id, n]));
  return model.compact.nodes.flatMap(n => {
    const r = raw.get(n.id);
    return r?.rect && r.rect.width > 0 && r.rect.height > 0 && !r.invisible ? [{ id: n.id, tag: n.tag, text: n.ownText, rect: r.rect, style: r.style }] : [];
  });
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

/**
 * Text drawn where the page rendered it: each element's own text split across its recorded line boxes
 * (in reading position order) by each line's character count. Elements without line boxes draw nothing.
 */
export function textLines(model) {
  return model.raw.nodes.flatMap(node => {
    if (!node.textBoxes?.length || !node.ownText || node.invisible) return [];
    const words = node.ownText.split(' ');
    const boxes = [...node.textBoxes].sort((a, b) => a.y - b.y || a.x - b.x);
    return boxes.flatMap((box, i) => {
      const taken = [];
      let used = 0;
      // A line takes words while they fit its character count (the last line takes the rest); a tiny box,
      // such as the space before a link, takes none.
      while (words.length && (i === boxes.length - 1 || used + words[0].length <= box.length)) {
        used += words[0].length + 1;
        taken.push(words.shift());
      }
      return taken.length ? [{ x: box.x, y: box.y, width: box.width, height: box.height, text: taken.join(' '),
        fontSize: node.style?.fontSize || Math.max(8, box.height * 0.8), bold: Boolean(node.style?.bold) }] : [];
    });
  });
}
