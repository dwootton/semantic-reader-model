// Semantic search over one page (docs/design/semantic-search-v0.md). Two tiers per query:
//   exact    every occurrence in the page's speakable text (what a screen reader's Find searches), always shown
//   meaning  compressed-DOM nodes whose embedded text is close to the query, above the cut-off
// On open, every node's text is embedded by the server; the vectors live only in this page. Page text is
// inserted as text, never as HTML.
import { loadPage } from '/corpus.mjs';
import { findExact, fold, nodeTexts, openTag, score, speakable } from '/search-text.mjs';

const app = document.getElementById('app');
const params = new URLSearchParams(location.search);
const TOP = 20, MAX_EXACT = 200, CONTEXT = 40;

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'class') el.className = value;
    else if (value !== false && value != null) el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) if (child != null && child !== false) el.append(child);
  return el;
}

async function getJson(url, body) {
  const response = await fetch(url, body && { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error || `${url}: HTTP ${response.status}`);
  return data;
}

async function embed(texts, query = false) {
  const started = performance.now();
  const out = await getJson('/api/embed', { texts, query });
  const bytes = Uint8Array.from(atob(out.vectors), c => c.charCodeAt(0));
  const all = new Float32Array(bytes.buffer);
  const vectors = texts.map((_, i) => all.subarray(i * out.dim, (i + 1) * out.dim));
  return { vectors, serverMs: out.ms, ms: performance.now() - started, model: out.model };
}

const ms = x => `${Math.round(x)} ms`;

async function main() {
  const queue = await getJson('/corpus/queue.json');
  const pages = [...queue.groups.main, ...(queue.groups.pro || [])].map(e => e.page);
  const page = params.get('page') || pages[0];
  const at = pages.indexOf(page);
  const link = (i, text) => i >= 0 && i < pages.length
    ? h('a', { class: 'nav-button', href: `/search?page=${encodeURIComponent(pages[i])}` }, text)
    : h('span', { class: 'nav-button disabled' }, text);

  app.replaceChildren(h('p', { class: 'muted' }, 'Loading page and embedding its nodes…'));
  const started = performance.now();
  const model = await loadPage(page);
  const loadMs = performance.now() - started;
  const nodes = nodeTexts(model);
  // The speakable text is read from the document itself: element ids are document-order indexes, as in loadPage.
  const html = await (await fetch(`/corpus/pages/${page}/document.html`)).text();
  const invisible = new Set(model.raw.nodes.filter(n => n.invisible).map(n => n.id));
  const spoken = speakable(new DOMParser().parseFromString(html, 'text/html'), invisible);
  const snap = await getJson(`/api/snapshot/${page}`).catch(() => null);
  let pageVectors;
  try {
    pageVectors = await embed(nodes.map(n => n.text));
  } catch (error) {
    app.replaceChildren(h('p', { class: 'error' }, error.message));
    return;
  }
  const byId = new Map(model.compact.nodes.map(n => [n.id, n]));
  const parentOf = id => byId.get(id)?.parent;
  const nodeOf = new Map(nodes.map(n => [n.id, n]));
  const rawById = new Map(model.raw.nodes.map(n => [n.id, n]));
  const unspoken = id => { for (let n = rawById.get(id); n; n = rawById.get(n.parent)) if (spoken.hidden.has(n.id)) return true; return false; };
  const tagOf = id => nodeOf.get(id)?.open || openTag(byId.get(id).tag, rawById.get(id)?.attributes);

  // ---- page copy (sandboxed, no scripts), as in the labeler
  let frameDoc = null, stamped = new Map(), marked = null;
  const copy = h('div', { class: 'search-copy' });
  const frame = snap && h('iframe', { class: 'snap-frame', title: 'Page copy', tabindex: -1, sandbox: 'allow-same-origin',
    src: `/corpus/snapshots/${page}.html`, style: `width:${model.viewport?.width || 1365}px;height:${snap.height}px` });
  const zoom = () => frame && (frame.style.zoom = copy.clientWidth / (model.viewport?.width || 1365));
  if (frame) {
    copy.append(frame);
    frame.addEventListener('load', () => {
      frameDoc = frame.contentDocument;
      frameDoc.head.append(Object.assign(frameDoc.createElement('style'), { textContent:
        '[data-sr-sel]{outline:3px solid #2563eb!important;outline-offset:2px;background-color:rgba(37,99,235,.18)!important}' }));
      stamped = new Map([...frameDoc.querySelectorAll('[data-sr-id]')].map(el => [el.dataset.srId, el]));
      frame.style.height = `${Math.max(snap.height, frameDoc.documentElement.scrollHeight)}px`;
    });
    new ResizeObserver(zoom).observe(copy);
  } else copy.append(h('p', { class: 'muted search-pad' }, 'No page copy for this page; results only.'));

  const show = id => {
    marked?.removeAttribute('data-sr-sel');
    const el = stamped.get(id);
    note.textContent = el || !frame ? '' : `${id} is not in the page copy (not matched to today's page).`;
    if (!el) return;
    el.setAttribute('data-sr-sel', '');
    marked = el;
    const scale = parseFloat(frame.style.zoom) || 1;
    copy.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top * scale - 80), behavior: 'smooth' });
  };

  // ---- search
  const input = h('input', { type: 'search', placeholder: 'Search this page by meaning, e.g. login', 'aria-label': 'Query', class: 'search-query' });
  const cutoff = h('input', { type: 'number', min: 0, max: 1.2, step: 0.01, value: localStorage.getItem('search.cutoff') || 0.72, 'aria-label': 'Score cut-off' });
  const timing = h('div', { class: 'status-line search-timing' });
  const note = h('div', { class: 'error search-note' });
  const list = h('div', { class: 'search-results' });
  let last = null, pending = 0;

  const snippet = ({ start, end }) => h('span', { class: 'search-snippet' },
    (start > CONTEXT ? '…' : '') + spoken.text.slice(Math.max(0, start - CONTEXT), start),
    h('mark', {}, spoken.text.slice(start, end)),
    spoken.text.slice(end, end + CONTEXT) + (end + CONTEXT < spoken.text.length ? '…' : ''));
  const exactRow = (hit, meaning) => h('button', { class: 'search-row', onclick: () => show(hit.id) },
    h('span', { class: 'search-score' }, `exact ×${hit.count}`,
      h('span', { class: 'muted' }, meaning ? ` · meaning ${meaning.score.toFixed(3)}` : '')),
    h('span', { class: 'tag' }, tagOf(hit.id)),
    ...hit.matches.slice(0, 3).map(snippet), hit.matches.length > 3 ? h('span', { class: 'muted' }, `+${hit.matches.length - 3} more`) : null);
  const row = (r, depth) => [
    h('button', { class: 'search-row', style: `padding-left:${8 + depth * 16}px`, onclick: () => show(r.id) },
      h('span', { class: 'search-score' }, r.score.toFixed(3),
        h('span', { class: 'muted' }, ` = ${r.cosine.toFixed(3)} meaning` + (r.bonus ? ` + ${r.bonus.toFixed(3)} exact: ` +
          r.hits.map(hit => `"${hit.word}" in ${hit.fields.join(', ')}`).join('; ') : ''))),
      h('span', { class: 'tag' }, nodeOf.get(r.id).open, unspoken(r.id) ? h('span', { class: 'search-flag' }, ' not spoken') : null),
      h('span', { class: 'search-text' }, nodeOf.get(r.id).text)),
    ...r.nested.flatMap(n => row(n, depth + 1)),
  ];
  const render = () => {
    if (!last) return list.replaceChildren();
    const min = Number(cutoff.value);
    const t = performance.now();
    const scored = nodes.map((n, i) => ({ id: n.id, ...score(last.query, last.vector, n, pageVectors.vectors[i]) }));
    const scoreMs = performance.now() - t;
    const t2 = performance.now();
    const exact = findExact(last.query, spoken, model);
    const exactMs = performance.now() - t2;
    const exactIds = new Set(exact.map(hit => hit.id));
    const scoreOf = new Map(scored.map(r => [r.id, r]));
    const above = scored.filter(r => r.score >= min && !exactIds.has(r.id));
    const top = fold(above, parentOf).slice(0, TOP);
    const best = Math.max(...scored.map(r => r.score));
    const occurrences = exact.reduce((sum, hit) => sum + hit.count, 0);
    timing.textContent = `query embed ${ms(last.ms)} (server ${ms(last.serverMs)}) · score ${ms(scoreMs)} · exact ${ms(exactMs)} · ` +
      `${above.length} more above ${min} · best ${best.toFixed(3)}`;
    list.replaceChildren(...[
      h('div', { class: 'search-tier' }, exact.length ? `Exact · ${occurrences} in ${exact.length} nodes` : 'Exact · none in the spoken text'),
      ...exact.slice(0, MAX_EXACT).map(hit => exactRow(hit, scoreOf.get(hit.id))),
      exact.length > MAX_EXACT ? h('p', { class: 'muted search-pad' }, `${exact.length - MAX_EXACT} more nodes not shown.`) : null,
      h('div', { class: 'search-tier' }, `Meaning · ${min} and up`),
      ...(top.length ? top.flatMap(r => row(r, 0))
        : [h('p', { class: 'muted search-pad' }, `Nothing else at or above ${min}. Lower the cut-off to see weaker matches.`)]),
    ].filter(Boolean));
  };
  const search = async () => {
    const query = input.value.trim();
    const mine = ++pending;
    if (!query) { last = null; return render(); }
    const q = await embed([query], true);
    if (mine !== pending) return; // a newer query was typed meanwhile
    last = { query, vector: q.vectors[0], ms: q.ms, serverMs: q.serverMs };
    render();
  };
  let timer;
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => search().catch(e => { note.textContent = e.message; }), 250); });
  cutoff.addEventListener('input', () => { try { localStorage.setItem('search.cutoff', cutoff.value); } catch { /* private window */ } render(); });

  app.replaceChildren(
    h('div', { class: 'pagebar' }, link(at - 1, '‹'), link(at + 1, '›'),
      h('span', { class: 'page-title' }, model.compact.nodes.find(n => n.tag === 'title')?.ownText || page),
      h('a', { class: 'page-url', href: model.url, target: '_blank', rel: 'noreferrer' }, model.url)),
    h('div', { class: 'search-workspace' },
      h('section', { class: 'window' },
        h('div', { class: 'menubar' }, input, h('label', { class: 'check' }, 'cut-off ', cutoff)),
        h('div', { class: 'status-line search-timing' },
          `${nodes.length} nodes · ${spoken.text.length.toLocaleString()} spoken characters · page load ${ms(loadMs)} · embed ${ms(pageVectors.ms)} (server ${ms(pageVectors.serverMs)}) · ${pageVectors.model}`),
        timing, note, list),
      h('section', { class: 'window' }, copy)));
  zoom();
  input.focus();
}

main().catch(error => app.replaceChildren(h('p', { class: 'error' }, error.message)));
