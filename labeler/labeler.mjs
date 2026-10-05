// Labeler UI: page picker, the editor (compressed DOM → semantic tree, with a wireframe and an
// optional raw DOM pane), and the one-off corpus check (/?check). Page text is inserted as text, never as HTML.
import { visibleRows } from '/inspector/model.mjs';
import { compactFor, loadPage } from '/corpus.mjs';
import * as M from '/label-model.mjs';
import { boxes, hitTest, pageSize, rectSelect, textLines } from '/wireframe.mjs';

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

// ---------------------------------------------------------------- editor

const shortText = node => node.ownText || node.attributes?.['aria-label'] || node.attributes?.alt ||
  node.attributes?.['data-destination'] || (node.children?.length ? '' : node.text) || '';
const isTyping = el => el && (el.matches('input, textarea, select') || el.isContentEditable);

// A tree pane with multi-select. Its data can be replaced; the semantic tree changes on every edit.
function noteIcon() {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', 'M2.5 3h11a1 1 0 0 1 1 1v6.5a1 1 0 0 1-1 1H7l-3 2.5v-2.5H2.5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM4.5 6h7M4.5 8.5h5');
  svg.append(path);
  return svg;
}

// The drag in progress, shared by all panes: { pane, ids }.
let dragging = null;

// A tree pane with multi-select, drag and drop, and optional rename in place.
// `drop`: { accepts(fromPane), inside(node) → may drop into it, onDrop(payload, { id, zone }) } where zone is
// 'before' | 'inside' | 'after', or 'end' for the empty area below the rows.
function createTree({ title, pane, label = shortText, tagOf = n => `<${n.tag}>`, extras = () => [], rowClass = () => '',
  onPick, onRename = null, drop = null, rowAction = null, onAction = () => {}, toggleOnClick = () => false,
  startExpanded = false, renamable = () => true, controls = [] }) {
  let byId = new Map(), roots = [], query = '', selected = new Set(), related = new Set(), focusId = null, anchor = null, order = [];
  let editing = null, dropAt = null;
  const expanded = new Set();
  const searchText = n => `${n.tag || ''} ${n.label || ''} ${n.ownText || ''} ${Object.values(n.attributes || {}).join(' ')}`;
  const count = h('span', { class: 'muted' });
  const container = h('div', { class: 'tree', role: 'tree', 'aria-label': title, 'aria-multiselectable': 'true' });
  const search = h('input', { type: 'search', placeholder: 'Search', 'aria-label': `Search ${title}`,
    oninput: event => { query = event.target.value; render(); } });
  const element = h('section', { class: 'pane' }, h('h2', {}, title, ' ', count), h('div', { class: 'pane-tools' }, search, ...controls), container);

  function render() {
    const rows = visibleRows(byId, roots, expanded, query, searchText);
    order = rows.map(r => r.node.id);
    if (!order.includes(focusId)) focusId = order.find(id => selected.has(id)) ?? order[0] ?? null;
    const hadFocus = container.contains(document.activeElement);
    container.replaceChildren(...rows.map(({ node, depth, open, hasChildren }) => h('div', {
      class: `row ${rowClass(node)}${related.has(node.id) ? ' related' : ''}`, role: 'treeitem',
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
    const second = lastClick.id === id && now - lastClick.at < 400 && !event.shiftKey && !event.metaKey && !event.ctrlKey;
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
    element,
    setData(nodes, newRoots) {
      byId = new Map(nodes.map(n => [n.id, { ...n }]));
      for (const n of byId.values()) for (const c of n.children) if (byId.has(c)) byId.get(c).parent = n.id;
      roots = newRoots.filter(r => byId.has(r));
      if (!expanded.size) {
        if (startExpanded) for (const n of byId.values()) { if (n.children.length) expanded.add(n.id); }
        else roots.forEach(r => { expanded.add(r); byId.get(r).children.forEach(c => expanded.add(c)); });
      }
      count.textContent = `· ${byId.size}`;
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
    matching() {
      const term = query.trim().toLowerCase();
      return term ? order.filter(id => searchText(byId.get(id)).toLowerCase().includes(term)) : [];
    },
    focus() { (rowEl(focusId) || container).focus?.(); },
  };
}

async function showPage(queue, page, groupName) {
  const group = queue.groups[groupName] ? groupName : 'main';
  const entries = queue.groups[group];
  const index = entries.findIndex(e => e.page === page);
  crumb.textContent = index >= 0 ? `${group} #${entries[index].order} of ${entries.length}` : page;
  app.replaceChildren(h('p', { class: 'muted' }, 'Loading page…'));
  let model, saved = null;
  try {
    model = await loadPage(page);
    saved = await getJson(`/api/labels/${page}`);
  } catch (error) {
    app.replaceChildren(h('p', { class: 'error' }, `Could not load ${page}: ${error.message}`), h('a', { href: `/?group=${group}` }, 'Back to queue'));
    return;
  }

  const ctx = M.pageIndex(model);
  let label = saved ? M.fromSaved(saved) : M.newLabel(ctx);
  let status = saved?.provenance?.status || 'new';
  let target = label.rootId;
  let selection = { pane: null, ids: [] };
  let hidePlaced = false;
  const undoStack = [], redoStack = [];
  const knownGroups = new Set();
  let saveTimer = null, pendingSave = false;

  // ---- panes
  const statusLine = h('span', { class: 'status-line', role: 'status' });
  const hideBox = h('label', { class: 'check' }, h('input', { type: 'checkbox', onchange: event => { hidePlaced = event.target.checked; update(); } }), ' Hide placed');
  const selectMatches = h('button', { type: 'button', title: 'Select every node matching the search',
    onclick: () => { const ids = compactTree.matching(); if (ids.length) choose('compact', ids); else say('Type a search first.', true); } }, 'Select matches');
  let compactOpen = true;
  const expandToggle = h('button', { type: 'button', title: 'Expand or collapse the whole compressed DOM', onclick: () => {
    compactOpen = !compactOpen;
    compactTree.setAllExpanded(compactOpen);
    expandToggle.textContent = compactOpen ? 'Collapse all' : 'Expand all';
  } }, 'Collapse all');
  const compactTree = createTree({ title: 'Compressed DOM', pane: 'compact', controls: [selectMatches, expandToggle, hideBox], startExpanded: true,
    // Dropping tree nodes back onto the compressed DOM removes them from the tree.
    drop: { accepts: from => from === 'semantic', inside: () => false,
      onDrop: payload => apply(() => { M.remove(label, payload.ids); selection = { pane: null, ids: [] }; }) },
    rowClass: n => ({ leaf: 'unit', placed: 'placed', skipped: 'skipped' })[placementOf(n.id)] || '',
    extras: n => placementOf(n.id) === 'leaf' ? [h('span', { class: 'badge' }, 'unit')]
      : placementOf(n.id) === 'skipped' && n.id in label.skipped ? [h('span', { class: 'badge' }, `skipped: ${label.skipped[n.id]}`)] : [],
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
  const rawTree = createTree({ title: 'Raw DOM', pane: 'raw',
    rowClass: n => n.compact.disposition === 'retained' ? '' : 'folded',
    extras: n => n.compact.disposition === 'retained' ? [] : [h('span', { class: 'badge' }, n.compact.disposition)],
    onPick: ids => { const match = compactFor(ids[0], rawById, ctx.byId); rawTree.setSelection([ids[0]]); if (match) choose('compact', [match], {}, 'raw'); } });
  const rawById = new Map(model.raw.nodes.map(n => [n.id, n]));
  rawTree.setData(model.raw.nodes, model.raw.roots);
  rawTree.element.hidden = true;

  const wire = createWireframe();
  const detail = h('div', { class: 'detail node-detail', hidden: true });
  let detailFor = null; // the tree node whose summary and notes are open
  const sourceDetail = h('div', { class: 'detail' });
  const coverage = h('details', { class: 'coverage', open: true });
  const problems = h('div', { class: 'problems' });
  compactTree.element.append(sourceDetail);
  semanticTree.element.append(detail, problems, coverage);

  // ---- toolbar
  const groupInput = h('input', { type: 'text', placeholder: 'Group label (blank: first element’s text)', 'aria-label': 'Group label',
    onkeydown: event => { if (event.key === 'Enter') { event.preventDefault(); groupSelection(event.shiftKey); } if (event.key === 'Escape') groupInput.blur(); } });
  const moveSelect = h('select', { 'aria-label': 'Move selection to group', onchange: event => {
    const to = event.target.value; event.target.value = '';
    if (to) apply(() => M.moveTo(label, selection.ids, to));
  } });
  const button = (text, title, run, kind) => h('button', { type: 'button', title, 'data-kind': kind, onclick: run }, text);
  const compactButtons = [
    button('Add', 'Add the selected nodes to the target group as units (A)', () => placeSelection('add'), 'compact'),
    button('Add children', 'Add each child of the selection as its own unit (C)', () => placeSelection('children'), 'compact'),
    button('Group', 'Group the selection, named by the label box or else the first element’s text (G)', () => groupSelection(false), 'compact'),
    button('Group children', 'New group with each child as a unit (Shift+Enter in the label box)', () => groupSelection(true), 'compact'),
    button('One unit', 'Make the selected node one unit, merging any units inside it (U)', () => placeSelection('unit'), 'compact-one'),
    button('Select similar', 'Select siblings shaped like the selection: same tag and child tags (e.g. the other cards)', () => choose('compact', M.selectSimilar(ctx, selection.ids)), 'compact'),
    button('Select siblings', 'Select every sibling of the selection', () => choose('compact', M.selectSiblings(ctx, selection.ids)), 'compact'),
    button('Group each', 'One group per selected node, named from its first text, holding its children as units', () => {
      let made = [];
      apply(() => { made = M.groupEach(label, ctx, selection.ids, target); });
      if (made.length) { made.forEach(id => semanticTree.expand(id)); selection = { pane: 'semantic', ids: made }; update(); }
    }, 'compact'),
    button('Skip', 'Mark as not content, with a reason (S)', () => skipSelection(), 'compact'),
    button('Unskip', 'Remove the skip', () => apply(() => M.unskip(label, selection.ids)), 'compact'),
  ];
  const treeButtons = [
    button('Group', 'Wrap the selected siblings in a new group, named by the label box or the first node (G)', () => groupSelection(false), 'tree'),
    button('Unwrap', 'Replace the group by its children', () => apply(() => selection.ids.forEach(id => M.unwrap(label, id))), 'tree'),
    button('Merge groups', 'Merge the selected groups into the first', () => apply(() => M.merge(label, selection.ids)), 'tree'),
    button('↑', 'Move up (Alt+↑)', () => apply(() => M.move(label, selection.ids, -1)), 'tree'),
    button('↓', 'Move down (Alt+↓)', () => apply(() => M.move(label, selection.ids, 1)), 'tree'),
    button('→', 'Into the group above (Alt+→)', () => apply(() => M.indent(label, selection.ids)), 'tree'),
    button('←', 'Out of the current group (Alt+←)', () => apply(() => M.outdent(label, selection.ids)), 'tree'),
    moveSelect,
    button('Split into children', 'Split a unit into its children', () => apply(() => selection.ids.forEach(id => M.splitLeaf(label, ctx, id))), 'tree'),
    button('Remove', 'Remove from the tree; units return to unplaced (Delete)', () => apply(() => { M.remove(label, selection.ids); selection = { pane: null, ids: [] }; }), 'tree'),
  ];
  const targetLine = h('span', { class: 'target-line' });
  const undoButton = button('Undo', 'Undo (⌘Z)', () => undo());
  const redoButton = button('Redo', 'Redo (⇧⌘Z)', () => redo());
  const submitButton = h('button', { type: 'button', class: 'primary', onclick: () => submit() }, 'Submit');
  const rawToggle = h('button', { type: 'button', onclick: () => { rawTree.element.hidden = !rawTree.element.hidden; layout(); } }, 'Raw DOM');
  const nav = (entry, text) => entry ? h('a', { href: pageHref(entry.page, group) }, text) : h('span', { class: 'muted' }, text);
  const panes = h('div', { class: 'panes' }, compactTree.element, semanticTree.element, wire.element, rawTree.element);

  app.replaceChildren(
    h('div', { class: 'meta' },
      h('a', { href: `/?group=${group}` }, '← Queue'), nav(entries[index - 1], 'Previous'), nav(entries[index + 1], 'Next'),
      h('a', { class: 'url', href: model.url, target: '_blank', rel: 'noreferrer' }, model.url),
      h('span', { class: 'muted' }, model.category || ''),
      h('span', { class: 'muted' }, `${model.stats.elements} elements → ${model.stats.compactNodes} compressed`), rawToggle),
    h('div', { class: 'editbar' },
      h('div', { class: 'editrow' }, targetLine, groupInput, undoButton, redoButton, statusLine, submitButton),
      h('div', { class: 'editrow' }, h('span', { class: 'muted' }, 'Compressed:'), ...compactButtons,
        h('span', { class: 'muted sep' }, 'Tree:'), ...treeButtons)),
    panes);
  function layout() {
    panes.style.setProperty('--cols', rawTree.element.hidden ? 3 : 4);
    rawToggle.setAttribute('aria-pressed', String(!rawTree.element.hidden));
  }
  layout();

  // ---- state helpers
  let placementMap = new Map();
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
    // The last tree node clicked sets where Add / Group put things: that group, or the unit's group.
    if (pane === 'semantic' && ids.length) {
      const last = label.nodes[ids[ids.length - 1]];
      if (last) target = last.kind === 'group' ? last.id : M.parents(label).get(last.id);
    }
    if (pane === 'compact' && next.length && from !== 'compact') { compactTree.reveal(next[0]); wire.scrollTo(next[0]); }
    if (pane === 'compact' && next.length && from === 'compact') wire.scrollTo(next[next.length - 1]);
    if (pane === 'compact' && next.length === 1 && !rawTree.element.hidden) { rawTree.setSelection([next[0]]); rawTree.reveal(next[0]); }
    update();
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
    if (status === 'submitted') status = 'draft';
    pendingSave = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save('draft'), 800);
  }

  async function save(asStatus) {
    clearTimeout(saveTimer);
    pendingSave = false;
    const body = M.toSaved(label, ctx, asStatus);
    try {
      const response = await fetch('/api/labels', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      status = asStatus;
      say(`${asStatus === 'submitted' ? 'Submitted' : 'Draft saved'} ${new Date().toLocaleTimeString()}`);
      return body;
    } catch (error) {
      say(`Save failed: ${error.message}`, true);
      throw error;
    }
  }
  window.addEventListener('pagehide', () => {
    if (pendingSave) fetch('/api/labels', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(M.toSaved(label, ctx, 'draft')) });
  });

  // ---- commands
  function placeSelection(kind) {
    if (selection.pane !== 'compact') return say('Select compressed nodes first.', true);
    apply(() => {
      if (kind === 'add') M.addLeaves(label, ctx, selection.ids, target);
      else if (kind === 'children') M.addChildren(label, ctx, selection.ids, target);
      else selection.ids.forEach(id => M.makeUnit(label, ctx, id, target));
      selection = { pane: null, ids: [] };
    });
  }
  // The label typed in the box, or else the first selected element's text (usually its heading).
  function groupSelection(children) {
    if (!selection.ids.length) return say('Select nodes to group first.', true);
    const text = groupInput.value.trim() || firstSelectedText();
    let created = null;
    apply(() => {
      created = selection.pane === 'compact' ? M.groupCompact(label, ctx, selection.ids, target, text, children)
        : M.groupNodes(label, selection.ids, text);
    });
    if (created && label.nodes[created]) { groupInput.value = ''; semanticTree.expand(created); choose('semantic', [created]); }
  }
  function firstSelectedText() {
    if (selection.pane === 'compact') {
      const first = [...selection.ids].sort((a, b) => ctx.order.get(a) - ctx.order.get(b))[0];
      return M.unitText(ctx, first).slice(0, 120);
    }
    const order = [];
    const walk = id => { order.push(id); label.nodes[id].children.forEach(walk); };
    walk(label.rootId);
    return label.nodes[order.find(id => selection.ids.includes(id))].label;
  }
  function skipSelection() {
    if (selection.pane !== 'compact') return say('Select compressed nodes to skip.', true);
    const reason = prompt('Why skip? (e.g. decorative, advertisement, hidden)', 'not content');
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

  async function submit() {
    const { errors } = M.validateLabel(label, ctx);
    if (errors.length) return say(`Fix ${errors.length} problem${errors.length > 1 ? 's' : ''} before submitting.`, true);
    try {
      const body = await save('submitted');
      await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(M.toDataset(model, body)) });
      const labels = await getJson('/api/labels');
      const next = entries.find(e => !labels[e.page]);
      say('Submitted. Opening the next page…');
      if (next) setTimeout(() => { location.href = pageHref(next.page, group); }, 700);
    } catch { /* save() already reported the error */ }
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
    const keys = { g: () => groupSelection(false), a: () => placeSelection('add'), c: () => placeSelection('children'),
      u: () => placeSelection('unit'), s: () => skipSelection(),
      Delete: () => tree && apply(() => { M.remove(label, selection.ids); selection = { pane: null, ids: [] }; }),
      Backspace: () => tree && apply(() => { M.remove(label, selection.ids); selection = { pane: null, ids: [] }; }),
      Escape: () => { if (selection.ids.length) selection = { pane: null, ids: [] }; else target = label.rootId; update(); } };
    const run = keys[event.key];
    if (run) { run(); event.preventDefault(); }
  });

  // ---- rendering
  function update() {
    placementMap = M.placement(label, ctx);
    for (const n of Object.values(label.nodes)) if (n.kind === 'group' && !knownGroups.has(n.id)) { knownGroups.add(n.id); semanticTree.expand(n.id); }

    // Compressed pane, optionally without nodes already placed or skipped.
    const visible = hidePlaced ? model.compact.nodes.filter(n => !placementMap.has(n.id)) : model.compact.nodes;
    const keep = new Set(visible.map(n => n.id));
    compactTree.setData(visible.map(n => ({ ...n, children: n.children.filter(c => keep.has(c)) })),
      model.compact.roots.filter(r => keep.has(r)));
    const relatedCompact = selection.pane === 'semantic' ? selection.ids.filter(id => label.nodes[id]).flatMap(leavesUnder) : [];
    compactTree.setSelection(selection.pane === 'compact' ? selection.ids : [], relatedCompact);
    semanticTree.setData(Object.values(label.nodes), [label.rootId]);
    const containing = selection.pane === 'compact' ? selection.ids.map(id => unitFor(id)).filter(Boolean) : [];
    semanticTree.setSelection(selection.pane === 'semantic' ? selection.ids : [], containing);
    wire.update(placementMap, selection.pane === 'compact' ? selection.ids : relatedCompact);

    const groups = Object.values(label.nodes).filter(n => n.kind === 'group');
    moveSelect.replaceChildren(h('option', { value: '' }, 'Move to…'), ...groups.map(g => h('option', { value: g.id }, g.label)));
    for (const b of [...compactButtons, ...treeButtons]) {
      const kind = b.dataset.kind;
      b.disabled = !selection.ids.length || (kind?.startsWith('compact') && selection.pane !== 'compact') || (kind?.startsWith('tree') && selection.pane !== 'semantic')
        || (kind === 'compact-one' && selection.ids.length !== 1);
    }
    undoButton.disabled = !undoStack.length;
    redoButton.disabled = !redoStack.length;
    const path = [];
    const parentMap = M.parents(label);
    for (let id = target; id; id = parentMap.get(id)) path.unshift(label.nodes[id].label);
    targetLine.replaceChildren('Adding to: ', h('strong', {}, path.join(' › ')));
    submitButton.textContent = status === 'submitted' ? 'Submitted ✓' : 'Submit';
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
    coverage.replaceChildren(h('summary', {}, missing.length ? `Unplaced DOM nodes: ${missing.length}` : 'Unplaced DOM nodes: none ✓'),
      missing.length ? h('button', { type: 'button', class: 'skip-all', title: 'Skip every node listed here, except ones holding a placed unit',
        onclick: () => {
          const reason = prompt('Why skip all of these?', 'not content');
          if (reason === null) return;
          let left = 0;
          apply(() => { left = M.skipUncovered(label, ctx, reason); });
          if (left) say(`${left} nodes hold placed units, so they can't be skipped; place or skip them individually.`, true);
        } }, 'Skip all') : null,
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
      page.append(h('div', { class: 'line', style: `left:${line.x}px;top:${line.y}px;height:${line.height}px;line-height:${line.height}px;` +
        `font-size:${line.fontSize}px;${line.bold ? 'font-weight:600;' : ''}transform:scaleX(${squeeze.toFixed(3)})` }, text));
    }
    const marquee = h('div', { class: 'marquee', hidden: true });
    const canvas = h('div', { class: 'wire-canvas' }, page, marquee);
    const scroller = h('div', { class: 'wire' }, canvas);
    let scale = 1, zoom = 'fit';
    const zoomSelect = h('select', { 'aria-label': 'Wireframe zoom', onchange: event => { zoom = event.target.value; fit(); } },
      h('option', { value: 'fit' }, 'Fit width'), h('option', { value: '0.5' }, '50%'), h('option', { value: '1' }, '100%'));
    const element = h('section', { class: 'pane' }, h('h2', {}, 'Wireframe ', h('span', { class: 'muted' }, `· ${list.length} boxes`)),
      h('div', { class: 'pane-tools' }, zoomSelect, h('span', { class: 'muted' }, 'Drag to select · Alt-click selects the parent')), scroller);
    function fit() {
      scale = zoom === 'fit' ? Math.max(0.1, (scroller.clientWidth - 4) / size.width) : Number(zoom);
      page.style.transform = `scale(${scale})`;
      canvas.style.width = `${size.width * scale}px`;
      canvas.style.height = `${size.height * scale}px`;
    }
    new ResizeObserver(fit).observe(scroller);
    const point = event => { const r = canvas.getBoundingClientRect(); return { x: (event.clientX - r.left) / scale, y: (event.clientY - r.top) / scale }; };
    let start = null;
    canvas.addEventListener('pointerdown', event => { if (event.button === 0) { start = point(event); canvas.setPointerCapture(event.pointerId); } });
    canvas.addEventListener('pointermove', event => {
      if (!start) return;
      const p = point(event);
      Object.assign(marquee.style, { left: `${Math.min(start.x, p.x) * scale}px`, top: `${Math.min(start.y, p.y) * scale}px`,
        width: `${Math.abs(p.x - start.x) * scale}px`, height: `${Math.abs(p.y - start.y) * scale}px` });
      marquee.hidden = false;
    });
    canvas.addEventListener('pointerup', event => {
      if (!start) return;
      const p = point(event), from = start;
      start = null;
      marquee.hidden = true;
      const how = { add: event.metaKey || event.ctrlKey || event.shiftKey };
      if (Math.abs(p.x - from.x) < 4 && Math.abs(p.y - from.y) < 4) {
        let id = hitTest(list, p.x, p.y);
        if (id && event.altKey) id = ctx.byId.get(id).parent || id;
        if (id) choose('compact', [id], how, 'wire');
      } else {
        const area = { x: Math.min(from.x, p.x), y: Math.min(from.y, p.y), width: Math.abs(p.x - from.x), height: Math.abs(p.y - from.y) };
        const ids = rectSelect(list, area, id => ctx.byId.get(id)?.parent);
        if (ids.length) choose('compact', ids, how, 'wire');
      }
    });
    return {
      element,
      update(placements, highlighted) {
        const lit = new Set(highlighted);
        for (const [id, el] of els) {
          const state = placements.get(id);
          el.className = `box${state ? ` ${state}` : ''}${lit.has(id) ? ' selected' : ''}`;
        }
      },
      scrollTo(id) {
        const r = list.find(b => b.id === id)?.rect;
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
