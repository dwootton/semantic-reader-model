// Labeler UI: page picker, the editor (compressed DOM → semantic tree, with a wireframe and an
// optional raw DOM pane), and the one-off corpus check (/?check). Page text is inserted as text, never as HTML.
import { visibleRows } from '/inspector/model.mjs';
import { loadPage } from '/corpus.mjs';
import * as M from '/label-model.mjs';
import { boxes, hitTest, pageSize, textLines } from '/wireframe.mjs';

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

// While screenshots are still being rendered, pages that have one come first (queue order kept within each set).
// ponytail: temporary ordering; once every page is rendered this is the plain queue order again.
const renderedPages = async () => new Set(await getJson('/api/renders').catch(() => []));
const renderedFirst = (list, rendered) => [...list.filter(e => rendered.has(e.page)), ...list.filter(e => !rendered.has(e.page))];

async function showPicker(queue) {
  const labels = await getJson('/api/labels').catch(() => ({}));
  const status = entry => labels[entry.page] || 'untouched';
  const rendered = await renderedPages();
  const ordered = Object.fromEntries(Object.entries(queue.groups).map(([name, list]) => [name, renderedFirst(list, rendered)]));
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
    const entry = ordered[group].find(e => status(e) === 'untouched');
    if (entry) location.href = pageHref(entry.page, group);
  } }, 'Next page');

  function render() {
    tabs.forEach(tab => tab.setAttribute('aria-pressed', String(tab.dataset.group === group)));
    const entries = ordered[group];
    const shown = entries.filter(e => !query || (e.url || '').toLowerCase().includes(query) || e.category.toLowerCase().includes(query));
    count.textContent = `${shown.length} shown · ${entries.filter(e => status(e) === 'untouched').length} untouched`;
    body.replaceChildren(...shown.map(e => h('tr', {},
      h('td', { class: 'num' }, String(e.order)),
      h('td', { class: 'url' }, h('a', { href: pageHref(e.page, group) }, e.url || e.page)),
      h('td', {}, e.category),
      h('td', {}, h('span', { class: `status ${status(e)}` }, status(e).replace('_', ' '))))));
  }

  app.replaceChildren(
    h('div', { class: 'toolbar' }, ...tabs, search, next, count),
    h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, '#'), h('th', {}, 'URL'), h('th', {}, 'Category'), h('th', {}, 'Status'))), body),
    queue.excluded?.length ? h('p', { class: 'muted' }, `${queue.excluded.length} pages failed the corpus check and are not queued.`) : null);
  render();
}

// ---------------------------------------------------------------- editor

const shortText = node => node.ownText || node.attributes?.['aria-label'] || node.attributes?.alt ||
  node.attributes?.['data-destination'] || (node.children?.length ? '' : node.text) || '';
const isTyping = el => el && (el.matches('input, textarea, select') || el.isContentEditable);

// A tree pane with multi-select. Its data can be replaced; the semantic tree changes on every edit.
// Small stroked 16×16 icons.
const ICONS = {
  note: 'M2.5 3h11a1 1 0 0 1 1 1v6.5a1 1 0 0 1-1 1H7l-3 2.5v-2.5H2.5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM4.5 6h7M4.5 8.5h5',
  up: 'M8 13.5V3M3.5 7.5 8 3l4.5 4.5',
  down: 'M8 2.5V13M3.5 8.5 8 13l4.5-4.5',
  indent: 'M2 3h12M7.5 6.5H14M7.5 9.5H14M2 13h12M2 6l3 2-3 2',   // into the group above: lines step in
  outdent: 'M2 3h12M7.5 6.5H14M7.5 9.5H14M2 13h12M5 6 2 8l3 2',  // out of the current group
  undo: 'M5.5 3.5 2.5 6.5l3 3M2.5 6.5h7a4 4 0 0 1 0 8H7',
  redo: 'M10.5 3.5l3 3-3 3M13.5 6.5h-7a4 4 0 0 0 0 8H9',
  right: 'M2.5 8h11M9 3.5 13.5 8 9 12.5',
};
function icon(name) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', ICONS[name]);
  svg.append(path);
  return svg;
}
const noteIcon = () => icon('note');

// The drag in progress, shared by all panes: { pane, ids }.
let dragging = null;

// A tree pane with multi-select, drag and drop, and optional rename in place.
// `drop`: { accepts(fromPane), inside(node) → may drop into it, onDrop(payload, { id, zone }) } where zone is
// 'before' | 'inside' | 'after', or 'end' for the empty area below the rows.
function createTree({ title, pane, label = shortText, tagOf = n => `<${n.tag}>`, extras = () => [], rowClass = () => '',
  onPick, onRename = null, drop = null, rowAction = null, onAction = () => {}, toggleOnClick = () => false,
  startExpanded = false, renamable = () => true, band = () => null }) {
  let byId = new Map(), roots = [], selected = new Set(), related = new Set(), focusId = null, anchor = null, order = [];
  let editing = null, dropAt = null;
  const expanded = new Set();
  const container = h('div', { class: 'tree', role: 'tree', 'aria-label': title, 'aria-multiselectable': 'true' });

  function render() {
    const rows = visibleRows(byId, roots, expanded, '', () => '');
    order = rows.map(r => r.node.id);
    if (!order.includes(focusId)) focusId = order.find(id => selected.has(id)) ?? order[0] ?? null;
    const hadFocus = container.contains(document.activeElement);
    // A band is a run of rows that belong together (a placed unit and what it covers): mark its first and last row.
    const bands = rows.map(r => band(r.node));
    const edge = i => (bands[i] && bands[i] !== bands[i - 1] && !bands[i - 1] ? ' band-start' : '') + (bands[i] && bands[i] !== bands[i + 1] ? ' band-end' : '');
    container.replaceChildren(...rows.map(({ node, depth, open, hasChildren }, i) => h('div', {
      class: `row ${rowClass(node)}${edge(i)}${related.has(node.id) ? ' related' : ''}`, role: 'treeitem',
      'aria-level': depth + 1, 'aria-expanded': hasChildren ? String(open) : null,
      'aria-selected': String(selected.has(node.id)), tabindex: node.id === focusId ? 0 : -1,
      'data-id': node.id, style: `padding-left:${8 + depth * 14}px`, draggable: editing === node.id ? null : 'true' },
    h('span', { class: 'toggle', 'aria-hidden': 'true' }, hasChildren ? (open ? '▾' : '▸') : ''),
    h('span', { class: 'tag' }, tagOf(node)), ...extras(node),
    editing === node.id ? renameInput(node) : h('span', { class: 'text' }, label(node)), actionButton(node))));
    // Re-rendering replaces the rows; keep keyboard focus on the current row so arrow keys keep working.
    if (container.querySelector('.rename')) container.querySelector('.rename').focus();
    else if (hadFocus) rowEl(focusId)?.focus({ preventScroll: true });
  }
  // Optional button at the row's right edge: an ellipsis on hover, or a note icon kept visible when the row has notes.
  function actionButton(node) {
    const action = rowAction?.(node);
    if (!action) return null;
    return h('button', { type: 'button', class: `row-action${action.note ? ' has-note' : ''}`, tabindex: -1,
      title: action.note ? 'Summary and notes' : 'Add a summary or notes', 'aria-label': action.note ? 'Summary and notes' : 'Add a summary or notes' },
    action.note ? noteIcon() : '…');
  }
  function renameInput(node) {
    let done = false;
    const finish = save => {
      if (done) return;
      done = true;
      editing = null;
      if (save && input.value.trim() && input.value !== node.label) onRename(node.id, input.value.trim()); else render();
    };
    const input = h('input', { class: 'rename', type: 'text', value: node.label, 'aria-label': 'Rename',
      onkeydown: event => { event.stopPropagation(); if (event.key === 'Enter') finish(true); if (event.key === 'Escape') finish(false); },
      onblur: () => finish(true) });
    return input;
  }
  function startRename(id) {
    if (!onRename || !byId.has(id) || !renamable(byId.get(id))) return;
    editing = id;
    render();
    container.querySelector('.rename')?.select();
  }
  const rowEl = id => container.querySelector(`[data-id="${CSS.escape(id)}"]`);
  function reveal(id) {
    for (let p = byId.get(id)?.parent; p; p = byId.get(p)?.parent) expanded.add(p);
    render();
    rowEl(id)?.scrollIntoView({ block: 'nearest' });
  }
  function toggle(id) { if (expanded.has(id)) expanded.delete(id); else expanded.add(id); render(); }
  function pick(id, event) {
    const range = event.shiftKey && anchor && order.includes(anchor);
    const ids = range ? order.slice(Math.min(order.indexOf(anchor), order.indexOf(id)), Math.max(order.indexOf(anchor), order.indexOf(id)) + 1) : [id];
    if (!range) anchor = id;
    focusId = id;
    onPick(ids, { add: event.metaKey || event.ctrlKey || range, range });
  }

  // Rows are re-rendered on every click, so the browser's dblclick never fires; detect a second click here.
  let lastClick = { id: null, at: 0 };
  container.addEventListener('click', event => {
    const row = event.target.closest('.row');
    if (!row || event.target.closest('.rename')) return;
    if (event.target.closest('.toggle')) return toggle(row.dataset.id);
    if (event.target.closest('.row-action')) return onAction(row.dataset.id);
    const id = row.dataset.id, now = event.timeStamp;
    const second = Boolean(onRename) && renamable(byId.get(id)) && lastClick.id === id && now - lastClick.at < 400
      && !event.shiftKey && !event.metaKey && !event.ctrlKey;
    lastClick = { id, at: second ? 0 : now };
    // A plain click on a toggling row (a group) also opens or closes it; the second click of a double-click undoes that.
    const flips = !event.shiftKey && !event.metaKey && !event.ctrlKey && toggleOnClick(byId.get(id)) && byId.get(id).children.length;
    if (flips) { if (expanded.has(id)) expanded.delete(id); else expanded.add(id); }
    if (second) startRename(id); else pick(id, event);
  });

  // ---- drag and drop
  const clearDrop = () => { container.querySelectorAll('.drop-before, .drop-inside, .drop-after').forEach(r => r.classList.remove('drop-before', 'drop-inside', 'drop-after')); container.classList.remove('drop-end'); dropAt = null; };
  container.addEventListener('dragstart', event => {
    const row = event.target.closest('.row');
    if (!row) return;
    const id = row.dataset.id;
    dragging = { pane, ids: selected.has(id) ? order.filter(o => selected.has(o)) : [id] };
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', dragging.ids.join(' '));
  });
  container.addEventListener('dragend', () => { dragging = null; clearDrop(); });
  container.addEventListener('dragover', event => {
    if (!dragging || !drop?.accepts(dragging.pane)) return;
    event.preventDefault();
    const row = event.target.closest('.row');
    const id = row?.dataset.id;
    let zone = 'end';
    if (row && !(dragging.pane === pane && dragging.ids.includes(id))) {
      const box = row.getBoundingClientRect(), y = (event.clientY - box.top) / box.height;
      const into = drop.inside(byId.get(id));
      zone = !byId.get(id).parent ? 'inside' : into ? (y < 0.25 ? 'before' : y > 0.75 ? 'after' : 'inside') : (y < 0.5 ? 'before' : 'after');
    } else if (row) zone = null;
    clearDrop();
    if (!zone) return;
    dropAt = { id: zone === 'end' ? null : id, zone };
    if (zone === 'end') container.classList.add('drop-end'); else row.classList.add(`drop-${zone}`);
  });
  container.addEventListener('dragleave', event => { if (!container.contains(event.relatedTarget)) clearDrop(); });
  container.addEventListener('drop', event => {
    event.preventDefault();
    const payload = dragging, at = dropAt;
    dragging = null;
    clearDrop();
    if (payload && at) drop.onDrop(payload, at);
  });
  container.addEventListener('keydown', event => {
    if (event.target.closest('.rename')) return;
    if (event.key === 'F2' && focusId) { startRename(focusId); event.preventDefault(); return; }
    const i = order.indexOf(focusId);
    const node = byId.get(focusId);
    // Selection follows the arrow keys (Shift extends it), so keyboard commands act on the row you see focused.
    const go = j => { if (order[j]) { const id = order[j]; pick(id, event.shiftKey ? event : {}); rowEl(id)?.focus(); } };
    if (event.altKey) return; // Alt+arrows belong to the editor's move commands
    if (event.key === 'ArrowDown') go(i + 1);
    else if (event.key === 'ArrowUp') go(Math.max(0, i - 1));
    else if (event.key === 'ArrowRight' && node?.children?.length) { expanded.add(focusId); render(); rowEl(focusId).focus(); }
    else if (event.key === 'ArrowLeft' && node) {
      if (expanded.has(focusId)) { expanded.delete(focusId); render(); rowEl(focusId).focus(); } else if (node.parent && order.includes(node.parent)) go(order.indexOf(node.parent));
    } else if (event.key === ' ' && focusId) pick(focusId, { metaKey: true });
    else if (event.key === 'Enter' && focusId) pick(focusId, {});
    else return;
    event.preventDefault();
  });

  return {
    body: container,
    setData(nodes, newRoots) {
      byId = new Map(nodes.map(n => [n.id, { ...n }]));
      for (const n of byId.values()) for (const c of n.children) if (byId.has(c)) byId.get(c).parent = n.id;
      roots = newRoots.filter(r => byId.has(r));
      if (!expanded.size) {
        if (startExpanded) for (const n of byId.values()) { if (n.children.length) expanded.add(n.id); }
        else roots.forEach(r => { expanded.add(r); byId.get(r).children.forEach(c => expanded.add(c)); });
      }
      render();
    },
    setSelection(ids, relatedIds = []) { selected = new Set(ids); related = new Set(relatedIds); render(); },
    expand(id) { expanded.add(id); },
    // Open every node, or close everything below the roots.
    setAllExpanded(open) {
      expanded.clear();
      for (const n of byId.values()) if (open ? n.children.length : roots.includes(n.id)) expanded.add(n.id);
      render();
    },
    reveal, render,
    focus() { (rowEl(focusId) || container).focus?.(); },
  };
}

async function showPage(queue, page, groupName) {
  const group = queue.groups[groupName] ? groupName : 'main';
  const entries = renderedFirst(queue.groups[group], await renderedPages());
  const index = entries.findIndex(e => e.page === page);
  app.replaceChildren(h('p', { class: 'muted' }, 'Loading page…'));
  let model, saved = null, render = null;
  try {
    model = await loadPage(page);
    saved = await getJson(`/api/labels/${page}`);
    render = await getJson(`/api/render/${page}`).catch(() => null); // a first-screen screenshot, if rendered
  } catch (error) {
    app.replaceChildren(h('p', { class: 'error' }, `Could not load ${page}: ${error.message}`), h('a', { href: `/?group=${group}` }, 'Back to queue'));
    return;
  }

  const ctx = M.pageIndex(model);
  let label = saved ? M.fromSaved(saved) : M.newLabel(ctx);
  // untouched (no label yet) → in_progress (edited) → complete (everything placed or skipped, no errors).
  const legacy = { draft: 'in_progress', submitted: 'complete' };
  let status = legacy[saved?.provenance?.status] || saved?.provenance?.status || 'untouched';
  let target = label.rootId;
  let selection = { pane: null, ids: [] };
  let hidePlaced = false;
  const undoStack = [], redoStack = [];
  const knownGroups = new Set();
  let saveTimer = null, pendingSave = false;

  // ---- panes
  const statusLine = h('span', { class: 'status-line', role: 'status' });
  const hideBox = h('label', { class: 'check' }, h('input', { type: 'checkbox', onchange: event => { hidePlaced = event.target.checked; update(); } }), ' Hide placed');
  const collapseBox = h('label', { class: 'check', title: 'Collapse or expand the whole compressed DOM' },
    h('input', { type: 'checkbox', onchange: event => compactTree.setAllExpanded(!event.target.checked) }), ' Collapse all');
  const compactTree = createTree({ title: 'Compressed DOM', pane: 'compact', startExpanded: true,
    // Dropping tree nodes back onto the compressed DOM removes them from the tree.
    drop: { accepts: from => from === 'semantic', inside: () => false,
      onDrop: payload => apply(() => { M.remove(label, payload.ids); selection = { pane: null, ids: [] }; }) },
    rowClass: n => ({ leaf: 'unit', placed: 'placed', skipped: 'skipped' })[placementOf(n.id)] || '',
    extras: n => placementOf(n.id) === 'skipped' && n.id in label.skipped ? [h('span', { class: 'badge' }, `ignored: ${label.skipped[n.id]}`)] : [],
    band: n => unitRoot.get(n.id) ?? null,
    onPick: (ids, how) => choose('compact', ids, how) });
  const semanticTree = createTree({ title: 'Semantic tree', pane: 'semantic',
    onRename: (id, text) => apply(() => M.setField(label, id, 'label', text)),
    toggleOnClick: n => n.kind === 'group',
    renamable: n => n.kind === 'group', // units keep their DOM text
    rowAction: n => ({ note: Boolean(n.summary?.trim() || n.notes?.trim() || (n.id === label.rootId && label.notes?.trim())) }),
    onAction: id => { detailFor = detailFor === id ? null : id; update(); },
    drop: { accepts: from => from === 'compact' || from === 'semantic', inside: n => n.kind === 'group', onDrop: dropOnTree },
    label: n => n.label, tagOf: n => n.kind === 'group' ? (n.id === label.rootId ? '▣' : '▤') : '•',
    rowClass: n => `${n.kind === 'group' ? 'group' : 'leaf'}${n.id === target ? ' target' : ''}`,
    extras: n => n.kind === 'dom' ? [h('span', { class: 'badge' }, n.display_role || '')] : [],
    onPick: (ids, how) => choose('semantic', ids, how) });
  const rawById = new Map(model.raw.nodes.map(n => [n.id, n]));

  const wire = createWireframe();
  const detail = h('div', { class: 'detail node-detail', hidden: true });
  let detailFor = null; // the tree node whose summary and notes are open
  const sourceDetail = h('div', { class: 'detail' });
  const coverage = h('div', { class: 'coverage' });
  const problems = h('div', { class: 'problems' });

  // ---- toolbar
  const button = (text, title, run, kind) => h('button', { type: 'button', title, 'data-kind': kind, onclick: run }, text);
  // Select similar: the nodes it started from, the current level, and the scope containers it searched.
  let similar = null;
  const similarInfo = h('span', { class: 'muted similar-info' });
  function runSimilar(level) {
    const result = M.selectSimilar(ctx, similar.anchor, Math.max(1, level));
    Object.assign(similar, { level: result.level, scopes: result.scopes });
    choose('compact', result.ids, {}, 'similar');
  }
  // Skip turns into Unskip when everything selected is already skipped; Group into Ungroup on a single group.
  const allSkipped = () => selection.pane === 'compact' && selection.ids.length && selection.ids.every(id => id in label.skipped);
  const skipButton = button('Ignore', 'Mark as not content, with a reason (S)', () => toggleSkip(), 'compact');
  const oneGroup = () => selection.pane === 'semantic' && selection.ids.length === 1 && label.nodes[selection.ids[0]]?.kind === 'group' && selection.ids[0] !== label.rootId;
  const groupButton = button('Group', 'Group the selected nodes, named after the first (G); on one group: ungroup it', () => toggleGroup(), 'tree');
  function toggleSkip() { if (allSkipped()) apply(() => M.unskip(label, selection.ids)); else skipSelection(); }
  function toggleGroup() { if (oneGroup()) apply(() => { M.unwrap(label, selection.ids[0]); selection = { pane: null, ids: [] }; }); else groupSelection(); }
  // Add and Add children move nodes into the semantic tree: blue, with an arrow, at the right end of the menu.
  const placeButton = (text, title, kind) => h('button', { type: 'button', class: 'primary place-button', title, 'data-kind': 'compact',
    onclick: () => placeSelection(kind) }, text, icon('right'));
  const placeButtons = [
    placeButton('Add', 'Add the selected nodes to the tree as units, each covering everything inside it (A)', 'add'),
    placeButton('Add children', 'Add each child of the selection to the tree as its own unit (C)', 'children'),
  ];
  const compactButtons = [
    button('Select similar', 'Select nodes on the same tag path as the selection; − and + narrow or widen the scope', () => {
      similar = { anchor: selection.ids, level: 1, scopes: [] };
      runSimilar(1);
    }, 'compact'),
    button('−', 'Narrow the similar scope by one level', () => runSimilar(similar.level - 1), 'similar-less'),
    button('+', 'Widen the similar scope by one level (siblings → cousins → second cousins)', () => runSimilar(similar.level + 1), 'similar'),
    similarInfo,
    button('Select siblings', 'Select every sibling of the selection', () => choose('compact', M.selectSiblings(ctx, selection.ids)), 'compact'),
    skipButton,
  ];
  const treeIcon = (name, title, run) => h('button', { type: 'button', class: 'icon-button', title, 'aria-label': title, 'data-kind': 'tree', onclick: run }, icon(name));
  const treeButtons = [
    groupButton,
    button('Merge groups', 'Merge the selected groups into the first', () => apply(() => M.merge(label, selection.ids)), 'tree'),
    treeIcon('up', 'Move up (Alt+↑)', () => apply(() => M.move(label, selection.ids, -1))),
    treeIcon('down', 'Move down (Alt+↓)', () => apply(() => M.move(label, selection.ids, 1))),
    treeIcon('indent', 'Move into the group above (Alt+→)', () => apply(() => M.indent(label, selection.ids))),
    treeIcon('outdent', 'Move out of its group (Alt+←)', () => apply(() => M.outdent(label, selection.ids))),
    button('Unpack', 'Replace a unit with a unit for each of its parts', () => apply(() => selection.ids.forEach(id => M.splitLeaf(label, ctx, id))), 'tree'),
    button('Remove', 'Remove from the tree; units return to unplaced (Delete)', () => apply(() => { M.remove(label, selection.ids); selection = { pane: null, ids: [] }; }), 'tree'),
  ];
  const iconButton = (name, title, run) => h('button', { type: 'button', class: 'icon-button', title, 'aria-label': title, onclick: run }, icon(name));
  const undoButton = iconButton('undo', 'Undo (⌘Z)', () => undo());
  const redoButton = iconButton('redo', 'Redo (⇧⌘Z)', () => redo());
  const clearSelection = () => { selection = { pane: null, ids: [] }; similar = null; update(); };
  // Clear appears in both menus.
  const clearButtons = [0, 1].map(() => h('button', { type: 'button', class: 'text-button', title: 'Esc', onclick: clearSelection }, 'Clear Selection'));
  const title = ctx.titleId ? M.unitText(ctx, ctx.titleId) : model.url;
  document.title = `${title} · Semantic labeler`;
  document.querySelector('.bar').hidden = true; // the page bar below replaces the app header here
  const navButton = (entry, text, name) => entry
    ? h('a', { class: 'nav-button', href: pageHref(entry.page, group), title: name, 'aria-label': name }, text)
    : h('span', { class: 'nav-button disabled', 'aria-hidden': 'true' }, text);
  // Draggable divider between the two columns (arrow keys too); the split is remembered per browser.
  let workspace = null;
  const splitter = h('div', { class: 'splitter', role: 'separator', 'aria-orientation': 'vertical', 'aria-label': 'Resize columns', tabindex: 0 });
  const setSplit = percent => {
    const value = Math.min(80, Math.max(30, percent));
    workspace.style.setProperty('--left', `${value}%`);
    splitter.setAttribute('aria-valuenow', String(Math.round(value)));
    try { localStorage.setItem('labeler.split', String(value)); } catch { /* storage unavailable */ }
  };
  splitter.addEventListener('pointerdown', event => { splitter.setPointerCapture(event.pointerId); splitter.dataset.dragging = '1'; });
  splitter.addEventListener('pointerup', () => { delete splitter.dataset.dragging; });
  splitter.addEventListener('pointermove', event => {
    if (!splitter.dataset.dragging) return;
    const box = workspace.getBoundingClientRect();
    setSplit((event.clientX - box.left) / box.width * 100);
  });
  splitter.addEventListener('keydown', event => {
    const now = Number(splitter.getAttribute('aria-valuenow')) || 60;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { setSplit(now + (event.key === 'ArrowLeft' ? -2 : 2)); event.preventDefault(); }
  });
  app.replaceChildren(
    h('header', { class: 'pagebar' },
      h('a', { class: 'nav-button', href: `/?group=${group}` }, '← Queue'),
      navButton(entries[index - 1], '‹', 'Previous page'), navButton(entries[index + 1], '›', 'Next page'),
      h('h1', { class: 'page-title' }, title),
      h('span', { class: 'page-category' }, model.category || ''),
      h('a', { class: 'page-url', href: model.url, target: '_blank', rel: 'noreferrer' }, model.url)),
    workspace = h('div', { class: 'workspace' },
      h('section', { class: 'window dom-window', 'aria-label': 'Compressed DOM and wireframe' },
        h('div', { class: 'menubar' }, collapseBox, hideBox,
          h('span', { class: 'menu-sep' }), ...compactButtons, clearButtons[0], h('span', { class: 'place-group' }, ...placeButtons)),
        h('div', { class: 'dom-split' },
          h('div', { class: 'split-col' }, h('div', { class: 'split-title' }, wire.title, wire.zoomBar), wire.view),
          h('div', { class: 'split-col' }, h('div', { class: 'split-title' }, 'Compressed DOM'), compactTree.body)),
        sourceDetail),
      splitter,
      h('div', { class: 'rightcol' },
        h('section', { class: 'window unplaced-window', 'aria-label': 'Unplaced DOM nodes' }, coverage),
        h('section', { class: 'window tree-window', 'aria-label': 'Semantic tree' },
          h('div', { class: 'menubar' }, undoButton, redoButton, h('span', { class: 'menu-sep' }), ...treeButtons, clearButtons[1],
            statusLine),
          semanticTree.body, detail, problems))));

  let savedSplit = 60;
  try { savedSplit = Number(localStorage.getItem('labeler.split')) || 60; } catch { /* storage unavailable */ }
  setSplit(savedSplit);

  // One-way scroll sync: scrolling the compressed DOM brings the first row on screen that has a box to the
  // top of the wireframe. Paused briefly after the editor scrolls things itself (selecting, revealing).
  let syncHeldUntil = 0, syncFrame = 0;
  const holdSync = () => { syncHeldUntil = performance.now() + 300; };
  compactTree.body.addEventListener('scroll', () => {
    if (syncFrame) return;
    syncFrame = requestAnimationFrame(() => {
      syncFrame = 0;
      if (performance.now() < syncHeldUntil) return;
      const top = compactTree.body.scrollTop;
      for (const row of compactTree.body.children) {
        if (row.offsetTop + row.offsetHeight > top && wire.alignTop(row.dataset.id)) break;
      }
    });
  });

  // ---- state helpers
  let placementMap = new Map(), unitRoot = new Map();
  function placementOf(id) { return placementMap.get(id); }
  function leavesUnder(id) {
    const node = label.nodes[id];
    return node.kind === 'dom' ? [node.sourceRefs[0]] : node.children.flatMap(leavesUnder);
  }

  function choose(pane, ids, how = {}, from = pane) {
    const current = selection.pane === pane ? selection.ids : [];
    let next = ids;
    if (how.add && !how.range) next = ids.every(id => current.includes(id)) ? current.filter(id => !ids.includes(id)) : [...new Set([...current, ...ids])];
    else if (how.range) next = [...new Set([...current, ...ids])];
    selection = { pane, ids: next };
    if (from !== 'similar') similar = null;
    // The last tree node clicked sets where Add / Group put things: that group, or the unit's group.
    if (pane === 'semantic' && ids.length) {
      const last = label.nodes[ids[ids.length - 1]];
      if (last) target = last.kind === 'group' ? last.id : M.parents(label).get(last.id);
    }
    if (pane === 'compact' && next.length) holdSync();
    if (pane === 'compact' && next.length && from !== 'compact') { compactTree.reveal(next[0]); wire.scrollTo(next[0]); }
    if (pane === 'compact' && next.length && from === 'compact') wire.scrollTo(next[next.length - 1]);
    update();
    // Open the semantic tree down to the unit holding the picked element, even inside closed groups.
    const unit = pane === 'compact' && next.length && unitFor(next[next.length - 1]);
    if (unit) semanticTree.reveal(unit);
  }

  function apply(operation) {
    const snapshot = JSON.stringify(label);
    try {
      operation();
      undoStack.push(snapshot);
      if (undoStack.length > 200) undoStack.shift();
      redoStack.length = 0;
      changed();
      say('');
    } catch (error) {
      label = JSON.parse(snapshot);
      say(error.message, true);
    }
    update();
  }
  function undo() { if (undoStack.length) { redoStack.push(JSON.stringify(label)); label = JSON.parse(undoStack.pop()); changed(); update(); } }
  function redo() { if (redoStack.length) { undoStack.push(JSON.stringify(label)); label = JSON.parse(redoStack.pop()); changed(); update(); } }
  function say(text, error = false) { statusLine.textContent = text; statusLine.classList.toggle('error', error); }

  function changed() {
    if (!label.nodes[target]) target = label.rootId;
    selection.ids = selection.pane === 'semantic' ? selection.ids.filter(id => label.nodes[id]) : selection.ids;
    pendingSave = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 800);
  }

  const currentStatus = () => (!M.validateLabel(label, ctx).errors.length && !M.uncovered(label, ctx).length ? 'complete' : 'in_progress');
  // Autosave is the only save. A complete label is re-checked by the server and exported for the inspector.
  async function save() {
    clearTimeout(saveTimer);
    pendingSave = false;
    const body = M.toSaved(label, ctx, currentStatus());
    try {
      const response = await fetch('/api/labels', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      status = result.status;
      if (status === 'complete') {
        body.provenance.status = status;
        await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(M.toDataset(model, body)) });
      }
      say(`Saved ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} · ${status.replace('_', ' ')}${result.note ? ` (${result.note})` : ''}`);
    } catch (error) {
      say(`Save failed: ${error.message}`, true);
    }
  }
  window.addEventListener('pagehide', () => {
    if (pendingSave) fetch('/api/labels', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(M.toSaved(label, ctx, currentStatus())) });
  });

  // ---- commands
  function placeSelection(kind) {
    if (selection.pane !== 'compact') return say('Select compressed nodes first.', true);
    apply(() => {
      if (kind === 'add') M.addLeaves(label, ctx, selection.ids, target);
      else if (kind === 'children') M.addChildren(label, ctx, selection.ids, target);
      selection = { pane: null, ids: [] };
    });
  }
  // The label typed in the box, or else the first selected element's text (usually its heading).
  // Grouping happens in the tree: place compressed nodes first (Add, drag), then group the tree nodes.
  function groupSelection() {
    if (selection.pane !== 'semantic' || !selection.ids.length) return say('Select tree nodes to group (place compressed nodes first).', true);
    const text = firstSelectedText();
    let created = null;
    apply(() => { created = M.groupNodes(label, selection.ids, text); });
    if (created && label.nodes[created]) { semanticTree.expand(created); choose('semantic', [created]); }
  }
  function firstSelectedText() {
    const order = [];
    const walk = id => { order.push(id); label.nodes[id].children.forEach(walk); };
    walk(label.rootId);
    return label.nodes[order.find(id => selection.ids.includes(id))].label;
  }
  function skipSelection() {
    if (selection.pane !== 'compact') return say('Select compressed nodes to ignore.', true);
    const reason = prompt('Why ignore? (e.g. decorative, advertisement, hidden)', 'not content');
    if (reason === null) return;
    apply(() => { M.skip(label, ctx, selection.ids, reason); selection = { pane: null, ids: [] }; });
  }
  // A drop on the tree: into a group, or before/after a node in its group. Compressed nodes become units there.
  function dropOnTree(payload, { id, zone }) {
    const parentMap = M.parents(label);
    let parent = label.rootId, before = null;
    if (zone === 'inside') parent = id;
    else if (zone !== 'end') {
      parent = parentMap.get(id);
      const siblings = label.nodes[parent].children;
      before = zone === 'before' ? id : siblings[siblings.indexOf(id) + 1] ?? null;
    }
    apply(() => {
      if (payload.pane === 'compact') { M.addLeaves(label, ctx, payload.ids, parent, before); selection = { pane: null, ids: [] }; }
      else M.moveTo(label, payload.ids, parent, before);
      target = parent;
      semanticTree.expand(parent);
    });
  }

  document.addEventListener('keydown', event => {
    if (isTyping(event.target)) return;
    const mod = event.metaKey || event.ctrlKey;
    if (mod && event.key.toLowerCase() === 'z') { event.shiftKey ? redo() : undo(); event.preventDefault(); return; }
    if (mod) return;
    const tree = selection.pane === 'semantic';
    if (event.altKey && tree) {
      const moves = { ArrowUp: () => M.move(label, selection.ids, -1), ArrowDown: () => M.move(label, selection.ids, 1),
        ArrowRight: () => M.indent(label, selection.ids), ArrowLeft: () => M.outdent(label, selection.ids) };
      if (moves[event.key]) { apply(moves[event.key]); event.preventDefault(); }
      return;
    }
    const keys = { g: () => toggleGroup(), a: () => placeSelection('add'), c: () => placeSelection('children'),
      s: () => toggleSkip(),
      Delete: () => tree && apply(() => { M.remove(label, selection.ids); selection = { pane: null, ids: [] }; }),
      Backspace: () => tree && apply(() => { M.remove(label, selection.ids); selection = { pane: null, ids: [] }; }),
      Escape: () => { if (selection.ids.length) selection = { pane: null, ids: [] }; else target = label.rootId; update(); } };
    const run = keys[event.key];
    if (run) { run(); event.preventDefault(); }
  });

  // ---- rendering
  function update() {
    placementMap = M.placement(label, ctx);
    unitRoot = new Map();
    const markUnit = (id, root) => { unitRoot.set(id, root); ctx.byId.get(id).children.forEach(c => markUnit(c, root)); };
    for (const n of Object.values(label.nodes)) if (n.kind === 'dom' && ctx.byId.has(n.sourceRefs[0])) markUnit(n.sourceRefs[0], n.sourceRefs[0]);
    for (const n of Object.values(label.nodes)) if (n.kind === 'group' && !knownGroups.has(n.id)) { knownGroups.add(n.id); semanticTree.expand(n.id); }

    // Compressed pane, optionally without nodes already placed or skipped.
    const visible = hidePlaced ? model.compact.nodes.filter(n => !placementMap.has(n.id)) : model.compact.nodes;
    const keep = new Set(visible.map(n => n.id));
    compactTree.setData(visible.map(n => ({ ...n, children: n.children.filter(c => keep.has(c)) })),
      model.compact.roots.filter(r => keep.has(r)));
    const relatedCompact = selection.pane === 'semantic' ? selection.ids.filter(id => label.nodes[id]).flatMap(leavesUnder) : [];
    compactTree.setSelection(selection.pane === 'compact' ? selection.ids : [], similar ? similar.scopes : relatedCompact);
    semanticTree.setData(Object.values(label.nodes), [label.rootId]);
    const containing = selection.pane === 'compact' ? selection.ids.map(id => unitFor(id)).filter(Boolean) : [];
    semanticTree.setSelection(selection.pane === 'semantic' ? selection.ids : [], containing);
    wire.update(placementMap, selection.pane === 'compact' ? selection.ids : relatedCompact, similar ? similar.scopes : []);
    similarInfo.textContent = similar ? `${similar.level} level${similar.level > 1 ? 's' : ''} up · ${selection.ids.length} node${selection.ids.length === 1 ? '' : 's'}` : '';

    for (const b of [...compactButtons, ...placeButtons, ...treeButtons]) {
      const kind = b.dataset.kind;
      b.disabled = !selection.ids.length || (kind?.startsWith('compact') && selection.pane !== 'compact') || (kind?.startsWith('tree') && selection.pane !== 'semantic')
        || (kind?.startsWith('similar') && !similar)
        || (kind === 'similar-less' && similar?.level <= 1);
    }
    undoButton.disabled = !undoStack.length;
    clearButtons.forEach(b => { b.disabled = !selection.ids.length; });
    skipButton.textContent = allSkipped() ? 'Unignore' : 'Ignore';
    groupButton.textContent = oneGroup() ? 'Ungroup' : 'Group';
    redoButton.disabled = !redoStack.length;
    renderDetail();
    renderProblems();
  }

  function unitFor(compactId) {
    for (let id = compactId; id; id = ctx.byId.get(id)?.parent) {
      const leaf = label.nodes[`leaf-${id}`];
      if (leaf) return leaf.id;
    }
    return null;
  }

  function renderDetail() {
    // Source detail for one compressed node.
    if (selection.pane === 'compact' && selection.ids.length === 1) {
      const n = rawById.get(selection.ids[0]);
      const rows = [['Element', `<${n.tag}> ${n.id}`], ['Placement', placementOf(n.id) || 'not placed'],
        ...Object.entries(n.attributes).map(([k, v]) => [k, v]), ['Text', (n.text || '').slice(0, 400)]];
      sourceDetail.replaceChildren(h('dl', {}, ...rows.filter(([, v]) => v).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, String(v))])));
    } else {
      sourceDetail.replaceChildren(h('p', { class: 'muted' }, selection.pane === 'compact' ? `${selection.ids.length} nodes selected.` : 'Click nodes here or draw a box on the wireframe.'));
    }
    // Summary and notes for the node whose row button was clicked; hidden otherwise.
    const node = label.nodes[detailFor];
    detail.hidden = !node;
    if (!node) { detailFor = null; return; }
    const field = (name, text, hint) => h('label', { class: 'field' }, text, h('textarea', { rows: 3, placeholder: hint,
      onchange: event => apply(() => M.setField(label, node.id, name, event.target.value)) }, node[name] || ''));
    const parts = [
      h('div', { class: 'detail-head' }, h('strong', {}, node.label),
        h('button', { type: 'button', class: 'link', 'aria-label': 'Close', onclick: () => { detailFor = null; update(); } }, '×')),
      field('summary', 'Summary', 'What this group contains, for a reader (optional).'),
      field('notes', 'Notes', 'Why you grouped or labeled it this way.')];
    if (node.id === label.rootId) parts.push(h('label', { class: 'field' }, 'Page notes', h('textarea', { rows: 2,
      onchange: event => apply(() => { label.notes = event.target.value; }) }, label.notes || '')));
    if (node.kind === 'dom') parts.push(h('p', { class: 'muted' }, `Unit <${ctx.byId.get(node.sourceRefs[0])?.tag}> ${node.sourceRefs[0]}: ${(node.reading_text || '').slice(0, 200)}`));
    detail.replaceChildren(...parts);
  }

  function renderProblems() {
    const { errors, warnings } = M.validateLabel(label, ctx);
    problems.replaceChildren(...errors.map(e => h('p', { class: 'error' }, e)), ...warnings.filter(w => !/not placed/.test(w)).map(w => h('p', { class: 'muted' }, w)));
    const missing = M.uncovered(label, ctx);
    coverage.replaceChildren(h('div', { class: 'window-head' },
      h('span', { class: 'window-title' }, missing.length ? `Unplaced DOM nodes · ${missing.length}` : 'Unplaced DOM nodes · none ✓'),
      missing.length ? h('button', { type: 'button', class: 'skip-all', title: 'Ignore every node listed here, except ones holding a placed unit',
        onclick: () => {
          const reason = prompt('Why ignore all of these?', 'not content');
          if (reason === null) return;
          let left = 0;
          apply(() => { left = M.skipUncovered(label, ctx, reason); });
          if (left) say(`${left} nodes hold placed units, so they can't be ignored; place or ignore them individually.`, true);
        } }, 'Ignore all') : null),
      // Entries can be clicked (select) or dragged onto the tree like compressed DOM rows.
      h('ul', {}, ...missing.slice(0, 200).map(id => h('li', {}, h('button', { type: 'button', class: 'link', draggable: 'true',
        onclick: () => choose('compact', [id], {}, 'coverage'),
        ondragstart: event => {
          const chosen = selection.pane === 'compact' && selection.ids.includes(id) ? selection.ids : [id];
          dragging = { pane: 'compact', ids: chosen };
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('text/plain', chosen.join(' '));
        },
        ondragend: () => { dragging = null; } }, `<${ctx.byId.get(id).tag}> ${shortText(ctx.byId.get(id)).slice(0, 80)}`)))));
  }

  // ---- wireframe
  function createWireframe() {
    const list = boxes(model);
    const size = pageSize(list, model.viewport || { width: 1365, height: 900 });
    const els = new Map();
    const page = h('div', { class: 'wire-page', style: `width:${size.width}px;height:${size.height}px` });
    // A first-screen screenshot (labeler/render_pages.py) sits under the boxes, in the same page coordinates.
    // It is moved up by the measured offset (how far the live page sits below the capture) so the two line up.
    const fold = (model.viewport || { height: 900 }).height;
    const shot = render && !render.error;
    if (shot) {
      page.append(h('img', { class: 'wire-shot', alt: '', src: `/corpus/renders/${model.page}.jpg`,
        style: `top:${-(render.offset || 0)}px;width:${size.width}px;height:${fold}px` }));
    }
    for (const b of [...list].sort((a, z) => z.rect.width * z.rect.height - a.rect.width * a.rect.height)) {
      const style = `left:${b.rect.x}px;top:${b.rect.y}px;width:${b.rect.width}px;height:${b.rect.height}px;`;
      const el = h('div', { class: 'box', style, 'data-id': b.id });
      els.set(b.id, el);
      page.append(el);
    }
    // Text sits on its recorded line boxes, squeezed or stretched to the recorded width so a different font
    // cannot push words out of place or cut them off.
    const measure = document.createElement('canvas').getContext('2d');
    for (const line of textLines(model)) {
      measure.font = `${line.bold ? 600 : 400} ${line.fontSize}px system-ui, sans-serif`;
      // Squeeze up to 40% (sites often use narrower fonts than ours); past that, drop trailing words.
      let text = line.text;
      while (text.includes(' ') && measure.measureText(text).width * 0.6 > line.width) text = text.slice(0, text.lastIndexOf(' '));
      const squeeze = Math.min(1.4, Math.max(0.6, line.width / (measure.measureText(text).width || 1)));
      page.append(h('div', { class: `line${line.y < fold ? ' fold' : ''}`, style: `left:${line.x}px;top:${line.y}px;height:${line.height}px;line-height:${line.height}px;` +
        `font-size:${line.fontSize}px;${line.bold ? 'font-weight:600;' : ''}transform:scaleX(${squeeze.toFixed(3)})` }, text));
    }
    const canvas = h('div', { class: 'wire-canvas' }, page);
    const scroller = h('div', { class: 'wire' }, canvas);
    // Zoom is relative to fit-width (1 = the whole page width fits the pane).
    let scale = 1, zoom = 1;
    const byBox = new Map(list.map(b => [b.id, b.rect]));
    function fit() {
      scale = Math.max(0.05, (scroller.clientWidth - 4) / size.width) * zoom;
      page.style.transform = `scale(${scale})`;
      canvas.style.width = `${size.width * scale}px`;
      canvas.style.height = `${size.height * scale}px`;
    }
    new ResizeObserver(fit).observe(scroller);
    const ZOOMS = [1, 1.5, 2, 3, 4, 6, 8];
    const zoomLabel = h('button', { type: 'button', class: 'text-button zoom-level', title: 'Back to fit width', onclick: () => setZoom(1) }, 'Fit');
    // Change zoom keeping the page point under the cursor (or the pane's centre) where it is.
    function setZoom(next, at = null) {
      const box = scroller.getBoundingClientRect();
      const ax = at ? at.clientX - box.left : scroller.clientWidth / 2, ay = at ? at.clientY - box.top : scroller.clientHeight / 2;
      const px = (scroller.scrollLeft + ax) / scale, py = (scroller.scrollTop + ay) / scale;
      zoom = Math.min(8, Math.max(1, next));
      fit();
      scroller.scrollLeft = px * scale - ax;
      scroller.scrollTop = py * scale - ay;
      zoomLabel.textContent = zoom === 1 ? 'Fit' : `${Math.round(zoom * 100)}%`;
    }
    // Screenshot | Wireframe toggle with the alignment score; the choice is remembered per browser.
    let mode = 'shot';
    try { mode = localStorage.getItem('labeler.wireMode') || 'shot'; } catch { /* storage unavailable */ }
    const modeButtons = ['shot', 'wire'].map(value => h('button', { type: 'button', class: 'segment', 'data-mode': value,
      onclick: () => setMode(value) }, value === 'shot' ? 'Screenshot' : 'Wireframe'));
    function setMode(value) {
      mode = value;
      scroller.classList.toggle('shot', shot && mode === 'shot');
      modeButtons.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
      try { localStorage.setItem('labeler.wireMode', mode); } catch { /* storage unavailable */ }
    }
    setMode(mode);
    const score = shot ? h('span', { class: 'shot-score', title: render.anchors
      ? `${render.aligned} of ${render.anchors} text anchors in the first screen line up with the capture` +
        ` · offset ${render.offset || 0} px · rendered ${(render.rendered_at || '').slice(0, 10)}`
      : 'No text in the first screen to compare with the capture' },
    render.score == null ? 'not measured' : `${Math.round(render.score * 100)}% aligned`) : null;
    const title = shot ? h('div', { class: 'shot-bar' }, h('div', { class: 'segmented' }, ...modeButtons), score) : h('span', {}, 'Wireframe');
    const zoomBar = h('div', { class: 'zoom-bar' },
      h('button', { type: 'button', class: 'icon-button', title: 'Zoom out', 'aria-label': 'Zoom out',
        onclick: () => setZoom([...ZOOMS].reverse().find(z => z < zoom) ?? 1) }, '−'),
      zoomLabel,
      h('button', { type: 'button', class: 'icon-button', title: 'Zoom in (⌘/Ctrl + scroll or pinch also zooms)', 'aria-label': 'Zoom in',
        onclick: () => setZoom(ZOOMS.find(z => z > zoom) ?? 8) }, '+'));
    scroller.addEventListener('wheel', event => {
      if (!event.ctrlKey && !event.metaKey) return; // plain scrolling pans
      event.preventDefault();
      setZoom(zoom * Math.exp(-event.deltaY * 0.003), event); // about ×1.35 per wheel notch; pinches are finer
    }, { passive: false });
    // Dragging pans; a click without movement selects the smallest box under the pointer
    // (Alt-click: its parent; ⌘/Ctrl/Shift-click adds to the selection).
    const point = event => { const r = canvas.getBoundingClientRect(); return { x: (event.clientX - r.left) / scale, y: (event.clientY - r.top) / scale }; };
    let drag = null;
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0 && event.button !== 1) return;
      drag = { x: event.clientX, y: event.clientY, left: scroller.scrollLeft, top: scroller.scrollTop, moved: false };
      canvas.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    canvas.addEventListener('pointermove', event => {
      if (!drag) return;
      const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      scroller.classList.add('panning');
      scroller.scrollLeft = drag.left - dx;
      scroller.scrollTop = drag.top - dy;
    });
    canvas.addEventListener('pointerup', event => {
      const was = drag;
      drag = null;
      scroller.classList.remove('panning');
      if (!was || was.moved) return;
      const p = point(event);
      let id = hitTest(list, p.x, p.y);
      if (id && event.altKey) id = ctx.byId.get(id).parent || id;
      if (id) choose('compact', [id], { add: event.metaKey || event.ctrlKey || event.shiftKey }, 'wire');
    });
    scroller.title = 'Click to select (Alt: parent) · drag or scroll to pan · ⌘/Ctrl+scroll or pinch to zoom';
    return {
      view: scroller, zoomBar, title,
      // Put a node's box at the top of the wireframe; false when it has no box.
      alignTop(id) {
        const r = byBox.get(id);
        if (!r) return false;
        scroller.scrollTop = Math.max(0, r.y * scale - 8);
        return true;
      },
      update(placements, highlighted, scopes = []) {
        const lit = new Set(highlighted), scoped = new Set(scopes);
        for (const [id, el] of els) {
          const state = placements.get(id);
          el.className = `box${state ? ` ${state}` : ''}${lit.has(id) ? ' selected' : ''}${scoped.has(id) ? ' scope' : ''}`;
        }
      },
      scrollTo(id) {
        const r = byBox.get(id);
        if (!r) return;
        const top = r.y * scale, bottom = (r.y + r.height) * scale;
        if (top < scroller.scrollTop || bottom > scroller.scrollTop + scroller.clientHeight) scroller.scrollTop = Math.max(0, top - 40);
      },
    };
  }

  update();
  if (saved) say(`Loaded ${status} label.`);
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
