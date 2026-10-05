// Capture files -> page model for the labeler. A JavaScript port of the DOM join in
// scripts/build_sft109_qualitative.py, run in the labeler's own browser instead of Playwright.
//
// IDs: every raw element is `src-<base36 document-order index>` of document.html, the same scheme
// as the published SFT-109 examples. The compact source map uses the same indexes, so a compact
// node shares its raw element's ID; a collapsed element points at its `representedBy` element.
// Geometry rows use the capture collector's `n<k>` IDs: document order, COLLECTOR_EXCLUDED tags last.
// parseDocument/parseCompact need a DOMParser (the browser); buildPage is pure.

export const CAPTURE_FILES = ['capture.json', 'environment.json', 'document.html', 'geometry.json',
  'compression/document-00000.html', 'compression/document-00000.source-map.json'];
const KEEP = new Set(['id', 'role', 'name', 'type', 'title', 'href', 'src', 'alt', 'placeholder', 'tabindex',
  'disabled', 'checked', 'selected', 'hidden', 'value', 'for', 'aria-label', 'aria-labelledby',
  'aria-describedby', 'aria-expanded', 'aria-selected', 'aria-checked', 'aria-disabled', 'aria-hidden',
  'aria-controls', 'aria-haspopup', 'aria-level', 'aria-current', 'lang', 'class']);
const INERT = new Set(['script', 'style', 'noscript', 'template']);
const COLLECTOR_EXCLUDED = new Set([...INERT, 'link', 'meta', 'base']);
const norm = s => s.replace(/\s+/g, ' ').trim();
const ownTextOf = el => norm([...el.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join(' '));

export function parseDocument(html, Parser = globalThis.DOMParser) {
  const doc = new Parser().parseFromString(html, 'text/html');
  const all = [...doc.querySelectorAll('*')];
  const index = new Map(all.map((el, i) => [el, i]));
  return all.map((el, i) => {
    const attributes = {};
    for (const a of el.attributes) if (KEEP.has(a.name)) attributes[a.name] = a.value.slice(0, 300);
    const inert = INERT.has(el.localName) || Boolean(el.closest('script,style,noscript,template'));
    const text = inert ? '' : norm(el.textContent);
    return { index: i, tag: el.localName, parent: el.parentElement ? index.get(el.parentElement) : null,
      children: [...el.children].map(c => index.get(c)), attributes,
      ownText: inert ? '' : ownTextOf(el).slice(0, 600), text: text.slice(0, 1800), textTruncated: text.length > 1800,
      hidden: el.hasAttribute('hidden') || attributes['aria-hidden'] === 'true' };
  });
}

// The compact HTML the model reads: elements carrying data-r, with their text as shown there.
export function parseCompact(html, Parser = globalThis.DOMParser) {
  const doc = new Parser().parseFromString(html, 'text/html');
  const owner = el => { for (let e = el.parentElement; e; e = e.parentElement) if (e.hasAttribute('data-r')) return e.getAttribute('data-r'); return null; };
  const ownText = el => {
    const parts = [];
    const walk = node => node.childNodes.forEach(c => {
      if (c.nodeType === 3) parts.push(c.data);
      else if (c.nodeType === 1 && !c.hasAttribute('data-r')) walk(c);
    });
    walk(el);
    return norm(parts.join(' '));
  };
  return [...doc.querySelectorAll('[data-r]')].map(el => {
    const attributes = {};
    for (const a of el.attributes) if (a.name !== 'data-r') attributes[a.name] = a.value.slice(0, 300);
    return { ref: el.getAttribute('data-r'), tag: el.localName, parentRef: owner(el), ownText: ownText(el).slice(0, 600), attributes };
  });
}

export function checkSourceMap(elements, sourceMap) {
  if (elements.length !== sourceMap.length) {
    throw new Error(`element count ${elements.length} differs from compact source map ${sourceMap.length}`);
  }
  elements.forEach((e, i) => {
    const entry = sourceMap[i];
    const parent = entry.parent === null ? null : parseInt(entry.parent, 36);
    if (parseInt(entry.id, 36) !== i || entry.tag.toLowerCase() !== e.tag || parent !== e.parent) {
      throw new Error(`compact source map diverges from parsed document at element ${i} (${e.tag})`);
    }
  });
}

export function collectorIds(elements) {
  const ordered = [...elements.filter(e => !COLLECTOR_EXCLUDED.has(e.tag)), ...elements.filter(e => COLLECTOR_EXCLUDED.has(e.tag))];
  return new Map(ordered.map((e, i) => [`n${i + 1}`, e.index]));
}

const srcId = index => `src-${Number(index).toString(36)}`;

export function buildPage({ page, capture, environment, elements, sourceMap, geometry, compact }) {
  checkSourceMap(elements, sourceMap);
  const nIndex = collectorIds(elements);
  const rects = new Map();
  for (const row of geometry.elements_and_text || []) {
    const index = nIndex.get(row.dom_id);
    if (index !== undefined && row.bounds) {
      const [x, y, width, height] = row.bounds;
      rects.set(index, { x, y, width, height });
    }
  }
  const raw = elements.map(e => {
    const entry = sourceMap[e.index];
    const node = { id: srcId(e.index), parent: e.parent === null ? null : srcId(e.parent), children: e.children.map(srcId),
      tag: e.tag, text: e.text, ownText: e.ownText, textTruncated: e.textTruncated, attributes: e.attributes, hidden: e.hidden,
      compact: { disposition: entry.disposition, representedBy: entry.representedBy == null ? null : `src-${entry.representedBy}` } };
    if (rects.has(e.index)) node.rect = rects.get(e.index);
    return node;
  });
  const byRef = new Map(sourceMap.map(entry => [entry.id, entry]));
  const compactNodes = compact.map(c => {
    const entry = byRef.get(c.ref);
    if (!entry) throw new Error(`compact element data-r="${c.ref}" is not in the source map`);
    if (entry.disposition !== 'retained') throw new Error(`compact element data-r="${c.ref}" is ${entry.disposition} in the source map`);
    return { id: `src-${c.ref}`, parent: c.parentRef === null ? null : `src-${c.parentRef}`, children: [],
      tag: c.tag, ownText: c.ownText, attributes: c.attributes };
  });
  const compactById = new Map(compactNodes.map(n => [n.id, n]));
  for (const n of compactNodes) if (n.parent !== null) compactById.get(n.parent).children.push(n.id);
  return {
    page, url: capture.final_url, category: capture.record?.category || null, capturedAt: capture.captured_at,
    viewport: environment.viewport,
    raw: { roots: raw.filter(n => n.parent === null).map(n => n.id), nodes: raw },
    compact: { roots: compactNodes.filter(n => n.parent === null).map(n => n.id), nodes: compactNodes },
    // The compactor never marks <html> and <head> with data-r; any other retained element missing is suspect.
    stats: { elements: elements.length, compactNodes: compactNodes.length, geometry: rects.size,
      missingRetained: sourceMap.filter(e => e.disposition === 'retained' && !['html', 'head'].includes(e.tag.toLowerCase())
        && !compactById.has(`src-${e.id}`)).length },
  };
}

// The compact node a raw element is shown as: itself, its representative, or its nearest compact ancestor.
export function compactFor(id, rawById, compactById) {
  for (let node = rawById.get(id); node; node = rawById.get(node.parent)) {
    if (compactById.has(node.id)) return node.id;
    const rep = node.compact?.representedBy;
    if (rep && compactById.has(rep)) return rep;
  }
  return null;
}

async function sha256(bytes) {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function loadPage(page, base = '/corpus/pages') {
  const files = await Promise.all(CAPTURE_FILES.map(async name => {
    const response = await fetch(`${base}/${page}/${name}`);
    if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
    return response.arrayBuffer();
  }));
  const decode = bytes => new TextDecoder().decode(bytes);
  const [capture, environment, html, geometry, compactHtml, sourceMap] = files.map(decode);
  const captureJson = JSON.parse(capture);
  const expected = captureJson.documents?.[0]?.sha256;
  if (expected && expected !== await sha256(files[2])) throw new Error('document.html does not match the capture hash');
  return buildPage({ page, capture: captureJson, environment: JSON.parse(environment), elements: parseDocument(html),
    sourceMap: JSON.parse(sourceMap), geometry: JSON.parse(geometry), compact: parseCompact(compactHtml) });
}
