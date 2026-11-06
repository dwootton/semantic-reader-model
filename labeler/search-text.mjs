// Semantic search (docs/design/semantic-search-v0.md): one string per compressed-DOM node to embed, and the
// score for a query. Pure: no DOM, no fetch.

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

// [{id, open, text, literal}]: `open` is the element's opening tag with the attributes the capture kept, `text` is
// embedded, and `literal` holds, per field, the words a query can match exactly.
export function nodeTexts(model) {
  const byId = new Map(model.compact.nodes.map(n => [n.id, n]));
  const raw = new Map(model.raw.nodes.map(n => [n.id, n]));
  const held = n => n.children.flatMap(c => { const k = byId.get(c); return [k.ownText, ...held(k)].filter(Boolean); });
  const out = [];
  for (const n of model.compact.nodes) {
    if (SKIP.has(n.tag)) continue;
    const a = raw.get(n.id)?.attributes || {};
    const own = n.ownText || '';
    const label = [a['aria-label'], a.title, a.alt, a.placeholder, ['button', 'submit'].includes(a.type) ? a.value : null]
      .filter(Boolean).join(' · ');
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
    const literal = Object.fromEntries(Object.entries({ text: own, label, href, id: a.id, class: a.class, name: a.name })
      .filter(([, v]) => v).map(([k, v]) => [k, ` ${words(v)} `]));
    const open = `<${n.tag}${Object.entries(a).map(([k, v]) => v === '' ? ` ${k}` : ` ${k}="${v}"`).join('')}>`;
    out.push({ id: n.id, open, text, literal });
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
