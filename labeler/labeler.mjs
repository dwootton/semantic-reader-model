// Labeler UI. Phase 1: page picker, read-only page view (compressed tree linked to raw DOM),
// and the one-off corpus check (/?check). All page text is inserted as text, never as HTML.
import { visibleRows } from '/inspector/model.mjs';
import { compactFor, loadPage } from '/corpus.mjs';

const app = document.getElementById('app');
const crumb = document.getElementById('crumb');
const params = new URLSearchParams(location.search);

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

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

const pageHref = (page, group) => `/?page=${encodeURIComponent(page)}&group=${encodeURIComponent(group)}`;

async function main() {
  let queue;
  try {
    queue = await getJson('/corpus/queue.json');
  } catch (error) {
    app.replaceChildren(h('p', { class: 'error' }, `No queue: run python3 labeler/queue_order.py. (${error.message})`));
    return;
  }
  if (params.has('check')) return runCheck(queue);
  if (params.get('page')) return showPage(queue, params.get('page'), params.get('group'));
  return showPicker(queue);
}

// ---------------------------------------------------------------- picker

async function showPicker(queue) {
  const labels = await getJson('/api/labels').catch(() => ({}));
  const status = entry => labels[entry.page] || 'todo';
  let group = queue.groups[params.get('group')] ? params.get('group') : 'main';
  let query = '';
  crumb.textContent = 'Queue';
  const body = h('tbody');
  const count = h('span', { class: 'muted' });
  const tabs = Object.keys(queue.groups).map(name => h('button', { type: 'button', 'data-group': name, onclick: () => {
    group = name;
    history.replaceState(null, '', `/?group=${name}`);
    render();
  } }, `${name} (${queue.groups[name].length})`));
  const search = h('input', { type: 'search', placeholder: 'Search URL or category', 'aria-label': 'Search pages',
    oninput: event => { query = event.target.value.trim().toLowerCase(); render(); } });
  const next = h('button', { type: 'button', class: 'primary', onclick: () => {
    const entry = queue.groups[group].find(e => status(e) === 'todo');
    if (entry) location.href = pageHref(entry.page, group);
  } }, 'Next page');

  function render() {
    tabs.forEach(tab => tab.setAttribute('aria-pressed', String(tab.dataset.group === group)));
    const entries = queue.groups[group];
    const shown = entries.filter(e => !query || (e.url || '').toLowerCase().includes(query) || e.category.toLowerCase().includes(query));
    count.textContent = `${shown.length} shown · ${entries.filter(e => status(e) === 'todo').length} todo`;
    body.replaceChildren(...shown.map(e => h('tr', {},
      h('td', { class: 'num' }, String(e.order)),
      h('td', { class: 'url' }, h('a', { href: pageHref(e.page, group) }, e.url || e.page)),
      h('td', {}, e.category),
      h('td', {}, h('span', { class: `status ${status(e)}` }, status(e))))));
  }

  app.replaceChildren(
    h('div', { class: 'toolbar' }, ...tabs, search, next, count),
    h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, '#'), h('th', {}, 'URL'), h('th', {}, 'Category'), h('th', {}, 'Status'))), body),
    queue.excluded?.length ? h('p', { class: 'muted' }, `${queue.excluded.length} pages failed the corpus check and are not queued.`) : null);
  render();
}

// ---------------------------------------------------------------- page view

const shortText = node => node.ownText || node.attributes?.['aria-label'] || node.attributes?.alt ||
  node.attributes?.['data-destination'] || (node.children?.length ? '' : node.text) || '';

function createTree({ title, nodes, roots, extras = () => [], rowClass = () => '', onSelect }) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const expanded = new Set(roots.flatMap(r => [r, ...byId.get(r).children]));
  let query = '', selected = null, related = new Set();
  const searchText = n => `${n.tag} ${n.ownText || ''} ${Object.values(n.attributes || {}).join(' ')}`;
  const container = h('div', { class: 'tree', role: 'tree', 'aria-label': title, tabindex: 0 });
  const search = h('input', { type: 'search', placeholder: `Search ${title.toLowerCase()}`, 'aria-label': `Search ${title}`,
    oninput: event => { query = event.target.value; render(); } });

  function render() {
    const rows = visibleRows(byId, roots, expanded, query, searchText);
    container.replaceChildren(...rows.map(({ node, depth, open, hasChildren }) => h('div', {
      class: `row ${rowClass(node)} ${related.has(node.id) ? 'related' : ''}`, role: 'treeitem',
      'aria-level': depth + 1, 'aria-expanded': hasChildren ? String(open) : null,
      'aria-selected': String(node.id === selected), tabindex: node.id === selected ? 0 : -1,
      'data-id': node.id, style: `padding-left:${10 + depth * 14}px` },
    h('span', { class: 'toggle', 'aria-hidden': 'true' }, hasChildren ? (open ? '▾' : '▸') : ''),
    h('span', { class: 'tag' }, `<${node.tag}>`), ...extras(node),
    h('span', { class: 'text' }, shortText(node)))));
  }

  function reveal(id) {
    for (let p = byId.get(id)?.parent; p; p = byId.get(p)?.parent) expanded.add(p);
    render();
    container.querySelector(`[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' });
  }

  function toggle(id) {
    if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
    render();
  }

  container.addEventListener('click', event => {
    const row = event.target.closest('.row');
    if (!row) return;
    if (event.target.closest('.toggle')) toggle(row.dataset.id);
    else onSelect(row.dataset.id);
  });
  container.addEventListener('keydown', event => {
    const rows = [...container.querySelectorAll('.row')];
    const current = document.activeElement.closest?.('.row');
    const i = rows.indexOf(current);
    const focus = row => { if (row) { rows.forEach(r => r.tabIndex = -1); row.tabIndex = 0; row.focus(); } };
    const node = current && byId.get(current.dataset.id);
    if (event.key === 'ArrowDown') focus(rows[i + 1] || rows[0]);
    else if (event.key === 'ArrowUp') focus(rows[Math.max(0, i - 1)]);
    else if (node && event.key === 'ArrowRight' && node.children.length && !expanded.has(node.id)) { toggle(node.id); focus(container.querySelector(`[data-id="${CSS.escape(node.id)}"]`)); }
    else if (node && event.key === 'ArrowLeft') {
      if (expanded.has(node.id)) { toggle(node.id); focus(container.querySelector(`[data-id="${CSS.escape(node.id)}"]`)); }
      else if (node.parent) focus(container.querySelector(`[data-id="${CSS.escape(node.parent)}"]`));
    } else if (node && (event.key === 'Enter' || event.key === ' ')) onSelect(node.id);
    else return;
    event.preventDefault();
  });

  render();
  return {
    byId, element: h('section', { class: 'pane' }, h('h2', {}, `${title} · ${nodes.length} nodes`), search, container),
    select(id, relatedIds = []) { selected = id; related = new Set(relatedIds); if (id) reveal(id); else render(); },
  };
}

async function showPage(queue, page, groupName) {
  const group = queue.groups[groupName] ? groupName : 'main';
  const entries = queue.groups[group];
  const index = entries.findIndex(e => e.page === page);
  const entry = entries[index];
  crumb.textContent = entry ? `${group} #${entry.order} of ${entries.length}` : page;
  app.replaceChildren(h('p', { class: 'muted' }, 'Loading page…'));
  let model;
  try {
    model = await loadPage(page);
  } catch (error) {
    app.replaceChildren(h('p', { class: 'error' }, `Could not load ${page}: ${error.message}`), h('a', { href: `/?group=${group}` }, 'Back to queue'));
    return;
  }

  const collapsedInto = new Map();
  for (const n of model.raw.nodes) {
    const rep = n.compact.representedBy;
    if (n.compact.disposition !== 'retained' && rep) collapsedInto.set(rep, [...(collapsedInto.get(rep) || []), n.id]);
  }
  const detail = h('div', { class: 'detail' }, h('p', { class: 'muted' }, 'Select a node to see how the compressed view and the raw DOM relate.'));
  const compactTree = createTree({ title: 'Compressed DOM', nodes: model.compact.nodes, roots: model.compact.roots,
    onSelect: id => { compactTree.select(id); rawTree.select(id, collapsedInto.get(id) || []); describe(id, id); } });
  const rawTree = createTree({ title: 'Raw DOM', nodes: model.raw.nodes, roots: model.raw.roots,
    rowClass: n => n.compact.disposition === 'retained' ? '' : 'folded',
    extras: n => n.compact.disposition === 'retained' ? [] : [h('span', { class: 'badge' }, n.compact.disposition)],
    onSelect: id => {
      const match = compactFor(id, rawTree.byId, compactTree.byId);
      rawTree.select(id);
      compactTree.select(match);
      describe(id, match);
    } });

  function describe(rawId, compactId) {
    const n = rawTree.byId.get(rawId);
    const mapping = compactId === rawId ? 'shown as itself in the compressed view'
      : compactId && n.compact.representedBy === compactId ? `collapsed into ${compactId}`
        : compactId ? `${n.compact.disposition}; nearest compressed ancestor is ${compactId}` : 'not in the compressed view';
    const rows = [['ID', n.id], ['Tag', n.tag], ['Compressed', mapping],
      ['Box', n.rect ? `${Math.round(n.rect.x)}, ${Math.round(n.rect.y)} · ${Math.round(n.rect.width)}×${Math.round(n.rect.height)}` : 'no geometry'],
      ...Object.entries(n.attributes).map(([k, v]) => [k, v]),
      ['Text', n.text ? n.text.slice(0, 500) + (n.text.length > 500 || n.textTruncated ? '…' : '') : '']];
    detail.replaceChildren(h('dl', {}, ...rows.filter(([, v]) => v).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, String(v))])));
  }

  const nav = (target, label) => target ? h('a', { href: pageHref(target.page, group) }, label) : h('span', { class: 'muted' }, label);
  app.replaceChildren(
    h('div', { class: 'meta' },
      h('a', { href: `/?group=${group}` }, '← Queue'), nav(entries[index - 1], 'Previous'), nav(entries[index + 1], 'Next'),
      h('a', { class: 'url', href: model.url, target: '_blank', rel: 'noreferrer' }, model.url),
      h('span', { class: 'muted' }, model.category || ''),
      h('span', { class: 'muted' }, `${model.stats.elements} elements → ${model.stats.compactNodes} compressed · ${model.stats.geometry} with geometry`)),
    h('div', { class: 'panes' }, compactTree.element, rawTree.element));
  rawTree.element.append(detail);
}

// ---------------------------------------------------------------- corpus check

async function runCheck(queue) {
  crumb.textContent = 'Corpus check';
  const pages = [...new Set([...Object.values(queue.groups).flat(), ...(queue.excluded || [])].map(e => e.page))];
  const total = pages.length;
  const failures = [], warnings = [];
  let done = 0;
  const progress = h('p', {}, `0 / ${total} checked`);
  const list = h('ul');
  app.replaceChildren(h('h1', {}, 'Corpus check'), progress, list);
  async function worker() {
    while (pages.length) {
      const page = pages.shift();
      try {
        // A dropped local connection is not a data problem; retry before failing the page.
        const model = await loadPage(page).catch(() => loadPage(page)).catch(() => loadPage(page));
        if (!model.stats.geometry) throw new Error('no geometry');
        if (model.stats.missingRetained) {
          warnings.push({ page, warning: `${model.stats.missingRetained} retained elements missing from compact HTML` });
        }
      } catch (error) {
        failures.push({ page, error: error.message });
        list.append(h('li', {}, `${page}: ${error.message}`));
      }
      progress.textContent = `${++done} / ${total} checked · ${failures.length} failed · ${warnings.length} warnings`;
    }
  }
  await Promise.all(Array.from({ length: 4 }, worker));
  const report = { checked: total, failed: failures.length, at: new Date().toISOString(), pages: failures, warnings };
  const response = await fetch('/api/corpus-check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(report) });
  app.append(h('p', { id: 'check-done' }, response.ok
    ? `Saved runs/corpus/excluded.json (${failures.length} failed). Rebuild the queue: python3 labeler/queue_order.py`
    : `Could not save the report: HTTP ${response.status}`));
}

main();
