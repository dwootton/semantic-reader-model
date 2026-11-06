// Semantic search (docs/design/semantic-search-v0.md): one string per compressed-DOM node to embed and its score
// for a query (meaning), and the page's speakable text with Find-style exact matching (what a screen reader's
// Find searches). No fetch; speakable() walks a parsed document.
import { compactFor } from './corpus.mjs';

const LANDMARKS = { header: 'header', nav: 'navigation', footer: 'footer', main: 'main', aside: 'sidebar', form: 'form',
  dialog: 'dialog', search: 'search' };
const KINDS = { a: 'link', button: 'button', select: 'dropdown', textarea: 'text box', img: 'image', svg: 'icon',
  h1: 'heading', h2: 'heading', h3: 'heading', h4: 'heading', h5: 'heading', h6: 'heading', label: 'label', li: 'list item' };
const SKIP = new Set(['html', 'head', 'body', 'title', 'meta', 'link', 'script', 'style']);

// "loginBtn", "nav__sign-in", "/account/login?next=1" -> "login btn", "nav sign in", "account login next 1"
export const words = s => (s || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[^\p{L}\p{N}]+/gu, ' ').trim().toLowerCase();

function hrefWords(href) {
  try {
    const url = new URL(href, 'https://x.invalid/');
    return words(url.pathname + ' ' + url.search + ' ' + url.hash);
  } catch {
    return '';
  }
}

export const openTag = (tag, attributes) =>
  `<${tag}${Object.entries(attributes || {}).map(([k, v]) => v === '' ? ` ${k}` : ` ${k}="${v}"`).join('')}>`;

// [{id, open, text, literal}]: `open` is the element's opening tag with the attributes the capture kept, `text` is
// embedded, and `literal` holds, per field, the words a query can match exactly.
export function nodeTexts(model) {
  const byId = new Map(model.compact.nodes.map(n => [n.id, n]));
  const raw = new Map(model.raw.nodes.map(n => [n.id, n]));
  const byHtmlId = new Map(model.raw.nodes.filter(n => n.attributes?.id).map(n => [n.attributes.id, n]));
  const labelFor = new Map(model.raw.nodes.filter(n => n.tag === 'label' && n.attributes?.for).map(n => [n.attributes.for, n.text]));
  const held = n => n.children.flatMap(c => { const k = byId.get(c); return [k.ownText, ...held(k)].filter(Boolean); });
  const out = [];
  for (const n of model.compact.nodes) {
    if (SKIP.has(n.tag)) continue;
    const a = raw.get(n.id)?.attributes || {};
    const own = n.ownText || '';
    // Accessible-name sources: aria-labelledby (the referenced elements' text), aria-label, <label for>, alt, title, placeholder.
    const labelledBy = (a['aria-labelledby'] || '').split(/\s+/).map(ref => byHtmlId.get(ref)?.text).filter(Boolean).join(' ');
    const label = [labelledBy, a['aria-label'], a.id && labelFor.get(a.id), a.title, a.alt, a.placeholder,
      ['button', 'submit'].includes(a.type) ? a.value : null].filter(Boolean).join(' · ');
    // A container with no text of its own stands for what it holds (its nodes' text, kept apart: textContent runs words together).
    const holds = own || label ? '' : held(n).join(' · ');
    const body = holds.length > 200 ? `${holds.slice(0, 200)}…` : holds;  // kept short so the node's own words still count
    const href = a.href ? hrefWords(a.href) : '';
    const names = words([a.id, a.class, a.name].filter(Boolean).join(' '));
    if (!own && !label && !body && !href && !names) continue;
    const kind = a.role || (n.tag === 'input' ? `${a.type || 'text'} input` : KINDS[n.tag] || LANDMARKS[n.tag] || '');
    let context = '';
    for (let p = byId.get(n.parent); p; p = byId.get(p.parent)) {
      const role = raw.get(p.id)?.attributes?.role;
      if (LANDMARKS[p.tag] || ['navigation', 'banner', 'contentinfo', 'search', 'dialog', 'form'].includes(role)) {
        context = LANDMARKS[p.tag] || role;
        break;
      }
    }
    const text = [kind, own, label, body, href && `(${href})`, names && `[${names}]`, context && `in ${context}`]
      .filter(Boolean).join(' ').slice(0, 400);
    // Markup a screen reader never speaks; spoken text is covered by exact matching (findExact).
    const literal = Object.fromEntries(Object.entries({ href, id: a.id, class: a.class, name: a.name })
      .filter(([, v]) => v).map(([k, v]) => [k, ` ${words(v)} `]));
    out.push({ id: n.id, open: openTag(n.tag, a), text, literal });
  }
  return out;
}

// Cosine (vectors are unit length) plus up to `boost` for query words found literally in the node.
// {score, cosine, bonus, hits: [{word, fields}]}
export function score(query, queryVector, node, vector, boost = 0.1) {
  let cosine = 0;
  for (let i = 0; i < vector.length; i++) cosine += vector[i] * queryVector[i];
  const terms = words(query).split(' ').filter(t => t.length >= 3);
  const hits = terms.map(word => ({ word, fields: Object.keys(node.literal).filter(f => node.literal[f].includes(word)) }))
    .filter(hit => hit.fields.length);
  const bonus = terms.length ? boost * hits.length / terms.length : 0;
  return { score: cosine + bonus, cosine, bonus, hits };
}

// Results above the cut-off, each folded under its nearest ancestor that is also a result.
// Returns [{id, score, best, nested: [...]}], top level ordered by the best score in each branch.
export function fold(results, parentOf) {
  const byId = new Map(results.map(r => [r.id, { ...r, nested: [] }]));
  const top = [];
  for (const r of byId.values()) {
    let p = parentOf(r.id);
    while (p && !byId.has(p)) p = parentOf(p);
    (p ? byId.get(p).nested : top).push(r);
  }
  const best = r => (r.best = Math.max(r.score, ...r.nested.map(best)));
  top.forEach(best);
  const sort = list => { list.sort((x, y) => y.best - x.best); list.forEach(r => sort(r.nested)); return list; };
  return sort(top);
}

// ---- speakable text and exact matching

const UNSPOKEN = new Set(['head', 'script', 'style', 'noscript', 'template']);
const NAMED_BY_LABEL = new Set(['a', 'button', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']);
const squash = t => (t || '').replace(/\s+/g, ' ').trim();

// The page as a screen reader's browse mode would read it, as one string in document order:
// text, accessible names (aria-labelledby, aria-label, alt, button values, placeholders), minus aria-hidden,
// hidden and invisible (display:none / visibility:hidden in the capture) elements.
// ponytail: approximates the accessible-name rules (no CSS ::before/::after content, no role-specific naming
// beyond links, buttons and headings); use the browser's computed accessibility tree if exactness matters.
// Returns {text, spans: [{start, end, id}], hidden: Set of element ids skipped as hidden}.
export function speakable(doc, invisible = new Set()) {
  const all = [...doc.querySelectorAll('*')];
  const idOf = new Map(all.map((el, i) => [el, `src-${i.toString(36)}`]));
  const byHtmlId = new Map(all.filter(el => el.getAttribute('id')).map(el => [el.getAttribute('id'), el]));
  let text = '';
  const spans = [], hidden = new Set();
  const say = (piece, el) => {
    piece = squash(piece);
    if (!piece) return;
    if (text) text += ' ';
    spans.push({ start: text.length, end: text.length + piece.length, id: idOf.get(el) });
    text += piece;
  };
  const walk = node => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) { say(child.data, node); continue; }
      if (child.nodeType !== 1) continue;
      const tag = child.localName, attr = name => child.getAttribute(name);
      if (UNSPOKEN.has(tag)) continue;
      if (child.hasAttribute('hidden') || attr('aria-hidden') === 'true' || invisible.has(idOf.get(child))) {
        hidden.add(idOf.get(child));
        continue;
      }
      const labelledBy = (attr('aria-labelledby') || '').split(/\s+/).map(ref => byHtmlId.get(ref)?.textContent).filter(Boolean).join(' ');
      const name = labelledBy || attr('aria-label');
      if (tag === 'img' || tag === 'area') { say(attr('alt'), child); continue; }
      if (tag === 'input') {
        const type = (attr('type') || 'text').toLowerCase();
        say(name || (['button', 'submit', 'reset'].includes(type) ? attr('value') : attr('value') || attr('placeholder')), child);
        continue;
      }
      if (name) say(name, child);
      if (name && NAMED_BY_LABEL.has(tag)) continue; // the label replaces what's inside
      walk(child);
    }
  };
  if (doc.body) walk(doc.body);
  return { text, spans, hidden };
}

const escapeRegex = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Every case-insensitive occurrence of the query (whitespace-insensitive) in the speakable text, each pinned to the
// smallest compressed-DOM node holding the whole match. Returns [{id, count, matches: [{start, end}]}] in page order.
export function findExact(query, spoken, model) {
  const q = squash(query);
  if (!q) return [];
  const rawById = new Map(model.raw.nodes.map(n => [n.id, n]));
  const compactById = new Map(model.compact.nodes.map(n => [n.id, n]));
  const chain = id => { const out = []; for (let n = rawById.get(id); n; n = rawById.get(n.parent)) out.push(n.id); return out; };
  const pattern = new RegExp(q.split(' ').map(escapeRegex).join('\\s+'), 'giu');
  const byNode = new Map();
  let i = 0;
  for (const m of spoken.text.matchAll(pattern)) {
    const start = m.index, end = m.index + m[0].length;
    while (spoken.spans[i].end <= start) i++;
    const ids = [];
    for (let j = i; j < spoken.spans.length && spoken.spans[j].start < end; j++) ids.push(spoken.spans[j].id);
    // Lowest common ancestor of the elements the match spans, then its compressed-DOM node.
    const common = ids.map(chain).reduce((a, b) => a.filter(id => b.includes(id)));
    const id = compactFor(common[0], rawById, compactById);
    if (!id) continue;
    if (!byNode.has(id)) byNode.set(id, { id, count: 0, matches: [] });
    const hit = byNode.get(id);
    hit.count++;
    hit.matches.push({ start, end });
  }
  return [...byNode.values()];
}
