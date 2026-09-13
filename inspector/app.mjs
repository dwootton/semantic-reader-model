import { createNarrator, describeNode } from './narration.mjs';
import { indexDataset, ancestors, hierarchyRefs, domToHierarchy, visibleRows, screenshotBounds } from './model.mjs';
import { computeMetrics, summarize } from './metrics.mjs';

const $ = id => document.getElementById(id);
const panes = {
  semantic: { element: $('semantic-tree'), search: $('semantic-search'), expanded: new Set(), rows: [], focus: null },
  raw: { element: $('raw-tree'), search: $('raw-search'), expanded: new Set(), rows: [], focus: null },
  dom: { element: $('dom-tree'), search: $('dom-search'), expanded: new Set(), rows: [], focus: null },
};
let catalog = [], data, index, metrics, selected = null, hovered = null, view = 'dom', leftView = 'semantic', loadController;
let showAllMetricTargets = false;
const narrator = createNarrator(window.speechSynthesis, window.SpeechSynthesisUtterance);
function narrateNode(side, id) {
  const item = panes[side].rows.find(row => row.node.id === id);
  if (item) narrator.speak(describeNode(item, side));
}
const includeChildren = () => $('include-children').checked;
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const short = (text, max = 140) => String(text || '').replace(/\s+/g, ' ').slice(0, max);
const mapFor = side => side === 'semantic' ? index.hierarchy : index.dom;
const parentOf = side => side === 'semantic' ? id => index.hierarchyParents.get(id) : id => index.dom.get(id)?.parent;
const rootsFor = side => side === 'semantic' ? [index.rootId] : index.domRoots;

function sourceLabel(node) {
  const attrs = node.attributes || {};
  return [node.id, node.tag, attrs.id, attrs.role, attrs['aria-label'], attrs.alt,
    attrs.placeholder, node.ownText || (node.children.length === 0 ? node.text : '')].filter(Boolean).join(' ');
}

function renderTree(side) {
  if (!index) return;
  const pane = panes[side];
  const nodes = mapFor(side);
  pane.rows = visibleRows(nodes, rootsFor(side), pane.expanded, pane.search.value,
    side === 'semantic' ? n => `${n.label} ${n.id} ${n.sourceRefs.join(' ')}` : sourceLabel);
  if (!pane.rows.some(r => r.node.id === pane.focus)) pane.focus = pane.rows[0]?.node.id;
  const fragment = document.createDocumentFragment();
  for (const item of pane.rows) {
    const n = item.node;
    const row = el('div', null, 'tree-row');
    row.dataset.id = n.id;
    row.dataset.side = side;
    row.style.setProperty('--depth', item.depth);
    row.setAttribute('role', 'treeitem');
    row.setAttribute('aria-level', item.depth + 1);
    row.setAttribute('aria-posinset', item.position);
    row.setAttribute('aria-setsize', item.total);
    row.setAttribute('aria-selected', String(selected?.side === side && selected.id === n.id));
    if (item.hasChildren) row.setAttribute('aria-expanded', String(item.open));
    row.tabIndex = pane.focus === n.id ? 0 : -1;
    const expander = el(item.hasChildren ? 'button' : 'span', item.hasChildren ? (item.open ? '▾' : '▸') : '·', 'expander');
    if (item.hasChildren) {
      expander.type = 'button'; expander.tabIndex = -1;
      expander.setAttribute('aria-label', `${item.open ? 'Collapse' : 'Expand'} ${side === 'semantic' ? n.label : n.tag}`);
      expander.addEventListener('click', event => { event.stopPropagation(); toggleNode(side, n.id); });
    } else expander.setAttribute('aria-hidden', 'true');
    row.append(expander);
    if (side === 'semantic') {
      const badge = el('span', n.kind === 'group' ? 'G' : 'D', `node-kind ${n.kind}`);
      badge.setAttribute('aria-hidden', 'true');
      row.append(badge, el('span', n.label, 'row-label'), el('span', `${n.sourceRefs.length} ref${n.sourceRefs.length === 1 ? '' : 's'}`, 'row-id'));
      row.setAttribute('aria-label', `${n.label}, ${n.kind === 'group' ? 'semantic group' : 'DOM reference'}`);
    } else {
      const label = el('span', null, 'row-label');
      label.append(el('span', `<${n.tag}>`, 'dom-tag'));
      const a = n.attributes || {};
      if (a.id) label.append(el('span', `#${a.id}`, 'dom-identity'));
      else if (a.role) label.append(el('span', `role=${a.role}`, 'dom-identity'));
      const text = n.ownText || a['aria-label'] || a.alt || (n.children.length === 0 ? n.text : '');
      if (text) label.append(el('span', short(text), 'dom-text'));
      row.append(label, el('span', n.id, 'row-id'));
      row.setAttribute('aria-label', `${n.tag}${a.id ? `, ID ${a.id}` : ''}${text ? `, ${short(text, 220)}` : ''}, source ${n.id}`);
    }
    row.addEventListener('click', () => selectNode(side, n.id));
    row.addEventListener('focus', () => { pane.focus = n.id; updateTabStops(side); narrateNode(side, n.id); });
    row.addEventListener('mouseenter', () => { hovered = { side, id: n.id }; paint(); });
    row.addEventListener('mouseleave', () => { hovered = null; paint(); });
    fragment.append(row);
  }
  if (!pane.rows.length) fragment.append(el('p', 'No matching nodes. Try another term.', 'empty'));
  pane.element.replaceChildren(fragment);
  paintRows();
}

function updateTabStops(side) {
  for (const row of panes[side].element.querySelectorAll('.tree-row')) row.tabIndex = row.dataset.id === panes[side].focus ? 0 : -1;
}

function focusRow(side, id) {
  panes[side].focus = id;
  updateTabStops(side);
  const row = [...panes[side].element.querySelectorAll('.tree-row')].find(r => r.dataset.id === id);
  row?.focus({ preventScroll: true });
  row?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function toggleNode(side, id, open) {
  const set = panes[side].expanded;
  if (open ?? !set.has(id)) set.add(id); else set.delete(id);
  renderTree(side); focusRow(side, id);
}

function reveal(side, ids) {
  const pane = panes[side];
  pane.search.value = '';
  for (const id of ids) ancestors(id, parentOf(side)).forEach(parent => pane.expanded.add(parent));
  renderTree(side);
}

function scrollToMatch(side, ids) {
  const candidates = [...panes[side].element.querySelectorAll('.tree-row')].filter(row => ids.has(row.dataset.id));
  candidates[0]?.scrollIntoView({ block: 'center', inline: 'nearest' });
}

function selectNode(side, id) {
  if (!mapFor(side).has(id)) return;
  narrateNode(side, id);
  hovered = null; selected = { side, id };
  panes[side].focus = id;
  if (side === 'semantic') {
    const refs = hierarchyRefs(index, id, includeChildren());
    reveal('dom', refs); scrollToMatch('dom', refs);
    if (leftView === 'raw') { reveal('raw', refs); scrollToMatch('raw', refs); }
  } else {
    const owners = domToHierarchy(index, id, includeChildren());
    if (leftView === 'semantic') {
      reveal('semantic', owners.exact); scrollToMatch('semantic', owners.exact);
    } else if (side !== 'raw') {
      reveal('raw', new Set([id])); scrollToMatch('raw', new Set([id]));
    }
    if (side === 'raw') { reveal('dom', new Set([id])); scrollToMatch('dom', new Set([id])); }
  }
  updateTabStops(side); paint(); renderDetails();
  $('clear-selection').disabled = false;
  $('announcement').textContent = `${side === 'semantic' ? index.hierarchy.get(id).label : `Source ${id}`} selected. ${$('match-count').textContent}`;
}

function relation(selection) {
  const semantic = new Set(), dom = new Set(), context = new Set();
  if (!selection || !index) return { semantic, dom, raw: dom, context, via: false };
  if (selection.side === 'semantic') {
    semantic.add(selection.id);
    const refs = hierarchyRefs(index, selection.id, includeChildren());
    return { semantic, dom: refs, raw: refs, context, via: false };
  }
  dom.add(selection.id);
  const owners = domToHierarchy(index, selection.id, includeChildren());
  return { semantic: owners.exact, dom, raw: dom, context: owners.context, via: owners.viaAncestor };
}

function paintRows() {
  if (!index) return;
  const pinned = relation(selected), preview = hovered ? relation(hovered) : null;
  for (const side of ['semantic', 'raw', 'dom']) for (const row of panes[side].element.querySelectorAll('.tree-row')) {
    const id = row.dataset.id;
    const isSelected = selected?.side === side && selected.id === id;
    row.classList.toggle('selected', isSelected);
    row.setAttribute('aria-selected', String(isSelected));
    row.classList.toggle('match', pinned[side].has(id));
    row.classList.toggle('context', side === 'semantic' && pinned.context.has(id));
    row.classList.toggle('via', side === 'semantic' && pinned.via && pinned.semantic.has(id));
    row.classList.toggle('preview', Boolean(preview?.[side].has(id)));
  }
}

function renderScreenshot() {
  if (!data || view !== 'screenshot') return;
  const shot = data.screenshot;
  const stage = $('screenshot').parentElement;
  const focusedSource = document.activeElement?.closest('#overlays .bound')?.dataset.sourceId;
  stage.hidden = !shot;
  $('overlays').replaceChildren();
  if (!shot) { $('screenshot-note').textContent = 'No registered screenshot exists for this capture. All source elements are available in the DOM tree.'; return; }
  const source = new URL(shot.url, location.href);
  if ($('screenshot').src !== source.href) $('screenshot').src = source.href;
  $('screenshot').alt = `${data.label}, saved viewport`;
  const refs = relation(hovered || selected).dom;
  const boxes = screenshotBounds(index.dom, refs, shot);
  // Large containers first; smaller, more specific nodes remain clickable above them.
  boxes.sort((a, b) => b.width * b.height - a.width * a.height);
  for (const box of boxes) {
    const button = el('button', null, 'bound');
    button.type = 'button';
    button.dataset.sourceId = box.id;
    Object.assign(button.style, { left: `${box.x}%`, top: `${box.y}%`, width: `${box.width}%`, height: `${box.height}%` });
    const node = index.dom.get(box.id);
    button.setAttribute('aria-label', `Select source ${box.id}: ${node.tag} ${short(node.ownText || node.text, 60)}`);
    button.title = `${box.id} · <${node.tag}>`;
    button.addEventListener('click', () => selectNode('dom', box.id));
    $('overlays').append(button);
  }
  if (focusedSource) {
    [...$('overlays').children].find(button => button.dataset.sourceId === focusedSource)?.focus({ preventScroll: true });
  }
  $('screenshot-note').textContent = refs.size
    ? `${boxes.length} of ${refs.size} linked elements have bounds in this saved viewport. Bounds are approximate; dynamic content may have changed during capture.`
    : 'Select a hierarchy node to locate its source elements in the saved viewport.';
}

function paint() { paintRows(); renderScreenshot(); }

function renderDetails() {
  renderSelectionMetrics();
  if (!selected) {
    $('selection-type').textContent = 'SELECT A NODE'; $('match-count').textContent = '';
    $('selection-title').textContent = 'Follow the connection';
    $('selection-summary').textContent = 'Choose a group on the left or an element on the right. Both panes highlight their relationship.';
    $('source-path').textContent = ''; $('source-attributes').textContent = ''; $('selection-note').textContent = '';
    return;
  }
  const n = mapFor(selected.side).get(selected.id);
  const refs = selected.side === 'semantic' ? hierarchyRefs(index, n.id, includeChildren()) : new Set([n.id]);
  const owners = selected.side !== 'semantic' ? domToHierarchy(index, n.id, includeChildren()) : null;
  const source = index.dom.get([...refs][0]);
  $('selection-type').textContent = selected.side === 'semantic' ? `${n.kind.toUpperCase()} / ${n.id}` : `DOM / ${n.id}`;
  $('selection-title').textContent = selected.side === 'semantic' ? n.label : `<${n.tag}>${n.attributes?.id ? ` #${n.attributes.id}` : ''}`;
  $('selection-summary').textContent = short(selected.side === 'semantic' ? n.summary : n.text || n.ownText, 550);
  $('match-count').textContent = owners
    ? `${leftView === 'raw' ? 'Same DOM element · ' : ''}${owners.exact.size} ${owners.viaAncestor ? 'containing' : 'direct'} hierarchy match${owners.exact.size === 1 ? '' : 'es'}`
    : `${refs.size} linked DOM element${refs.size === 1 ? '' : 's'}`;
  $('source-path').textContent = refs.size > 1 ? [...refs].join(' · ') : source?.cssPath || source?.xpath || '';
  const attrs = source?.attributes || {};
  const allowed = ['role', 'aria-label', 'aria-disabled', 'disabled', 'aria-expanded', 'aria-selected', 'aria-checked', 'type', 'href'];
  $('source-attributes').textContent = refs.size === 1 ? allowed.filter(k => k in attrs).map(k => `${k}=${JSON.stringify(attrs[k])}`).join(' · ') : 'Select an individual DOM element to inspect its attributes and locator.';
  const notes = [];
  if (owners?.viaAncestor) notes.push(`No direct annotation for this node. Highlighting owners of ancestor ${owners.mappedSource}.`);
  else if (owners && !owners.exact.size) notes.push('This captured element has no hierarchy annotation.');
  if (selected.side === 'semantic' && n.notes) notes.push(typeof n.notes === 'string' ? n.notes : JSON.stringify(n.notes));
  if (source?.hidden && refs.size === 1) notes.push('The capture records hidden/excluded evidence; visual presence and accessibility exposure can differ.');
  $('selection-note').textContent = short(notes.join(' '), 420);
}

function setView(next) {
  view = next;
  $('dom-view').setAttribute('aria-pressed', String(view === 'dom'));
  $('screenshot-view').setAttribute('aria-pressed', String(view === 'screenshot'));
  $('dom-tree').hidden = view !== 'dom'; $('dom-tools').hidden = view !== 'dom';
  $('screenshot-panel').hidden = view !== 'screenshot';
  renderScreenshot();
}

function setLeftView(next) {
  leftView = next;
  hovered = null;
  const isSemantic = next === 'semantic';
  $('left-semantic-view').setAttribute('aria-pressed', String(isSemantic));
  $('left-raw-view').setAttribute('aria-pressed', String(!isSemantic));
  $('semantic-title').textContent = isSemantic ? 'Semantic hierarchy' : 'Raw DOM';
  for (const id of ['semantic-tools', 'semantic-scope', 'semantic-tree']) $(id).hidden = !isSemantic;
  for (const id of ['raw-tools', 'raw-scope', 'raw-tree']) $(id).hidden = isSemantic;
  if (!index) return;
  if (selected) {
    const matches = relation(selected);
    const refs = isSemantic ? matches.semantic : matches.raw;
    reveal(next, refs); scrollToMatch(next, refs);
  } else renderTree(next);
  paint(); renderDetails();
  $('announcement').textContent = `${isSemantic ? 'Semantic hierarchy' : 'Raw DOM'} in the left pane. Selection retained.`;
}

function applyVariant() {
  narrator.stop();
  index = indexDataset(data, $('variant').value);
  metrics = computeMetrics(data, $('variant').value);
  showAllMetricTargets = false;
  selected = hovered = null;
  for (const side of ['semantic', 'raw', 'dom']) {
    panes[side].expanded = new Set(rootsFor(side));
    panes[side].search.value = ''; panes[side].focus = rootsFor(side)[0];
  }
  $('semantic-count').textContent = `${index.hierarchy.size} nodes`;
  $('dom-count').textContent = `${index.dom.size.toLocaleString()} source elements`;
  $('raw-scope').textContent = `${index.dom.size.toLocaleString()} source elements · matched by original element ID`;
  $('clear-selection').disabled = true;
  renderTree('semantic'); renderTree('raw'); renderTree('dom'); renderDetails(); renderScreenshot();
  $('statistics-open').disabled = false;
  if ($('statistics-dialog').open) renderStatistics();
}

async function loadDataset(id) {
  loadController?.abort();
  const controller = new AbortController(); loadController = controller;
  $('workspace').setAttribute('aria-busy', 'true'); $('variant').disabled = true;
  $('statistics-open').disabled = true;
  $('workspace').inert = true;
  $('load-error').hidden = true;
  try {
    const response = await fetch(`data/${encodeURIComponent(id)}.json`, { signal: controller.signal });
    if (!response.ok) throw new Error(`Capture could not be loaded (${response.status}).`);
    const incoming = await response.json();
    if (controller.signal.aborted) return;
    data = incoming;
    $('variant').replaceChildren();
    for (const option of catalog.find(item => item.id === id).variants) {
      const item = el('option', option.label); item.value = option.id; $('variant').append(item);
    }
    $('variant').value = data.variants.revised ? 'revised' : Object.keys(data.variants)[0];
    $('variant').disabled = false;
    applyVariant();
    $('workspace').setAttribute('aria-busy', 'false');
    $('workspace').inert = false;
    const url = new URL(location.href); url.searchParams.set('site', id); history.replaceState(null, '', url);
    $('announcement').textContent = `${data.label} loaded. ${index.hierarchy.size} hierarchy nodes and ${index.dom.size} DOM elements.`;
  } catch (error) {
    if (error.name !== 'AbortError') {
      $('load-error').textContent = `${error.message} Run the local server and reload this page.`;
      $('load-error').hidden = false; $('workspace').setAttribute('aria-busy', 'false');
    }
  }
}

for (const side of ['semantic', 'raw', 'dom']) {
  const pane = panes[side];
  pane.search.addEventListener('input', () => renderTree(side));
  pane.element.addEventListener('keydown', event => {
    const row = event.target.closest('.tree-row');
    if (!row || !index) return;
    const id = row.dataset.id, at = pane.rows.findIndex(r => r.node.id === id), item = pane.rows[at];
    if (!item) return;
    const keys = ['ArrowUp', 'ArrowDown', 'ArrowRight', 'ArrowLeft', 'Home', 'End', 'Enter', ' '];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowRight' || (event.key === 'ArrowDown' && !item.hasChildren)) {
      const next = pane.rows.slice(at + 1).find(candidate => candidate.depth <= item.depth);
      if (next) focusRow(side, next.node.id);
    }
    if (event.key === 'ArrowLeft') {
      for (let previous = at - 1; previous >= 0; previous--) {
        const candidate = pane.rows[previous];
        if (candidate.depth < item.depth) break;
        if (candidate.depth === item.depth) { focusRow(side, candidate.node.id); break; }
      }
    }
    if (event.key === 'ArrowDown' && item.hasChildren) {
      if (!item.open) {
        pane.expanded.add(id);
        renderTree(side);
      }
      const current = pane.rows.findIndex(r => r.node.id === id);
      const child = pane.rows[current + 1];
      if (child?.depth === item.depth + 1) focusRow(side, child.node.id);
    }
    if (event.key === 'ArrowUp') {
      const parent = parentOf(side)(id);
      if (parent) focusRow(side, parent);
    }
    if (event.key === 'Home') focusRow(side, pane.rows[0].node.id);
    if (event.key === 'End') focusRow(side, pane.rows.at(-1).node.id);
    if (event.key === 'Enter' || event.key === ' ') selectNode(side, id);
  });
  $(`${side}-collapse`).addEventListener('click', () => {
    if (!index) return;
    pane.search.value = ''; pane.expanded = new Set(rootsFor(side)); renderTree(side);
  });
}
for (const side of ['semantic', 'raw', 'dom']) {
  $(`${side}-expand`).addEventListener('click', () => {
    if (!index) return;
    panes[side].search.value = '';
    panes[side].expanded = new Set(mapFor(side).keys());
    renderTree(side);
    $('announcement').textContent = `All ${side === 'semantic' ? 'hierarchy' : 'DOM'} levels expanded.`;
  });
}
const narrationToggle = $('narration-toggle');
if (!narrator.supported) {
  narrationToggle.disabled = true;
  narrationToggle.textContent = 'Narration unavailable';
}
narrationToggle.addEventListener('click', () => {
  const enabled = narrationToggle.getAttribute('aria-pressed') !== 'true';
  narrator.setEnabled(enabled);
  narrationToggle.setAttribute('aria-pressed', String(enabled));
  narrationToggle.textContent = `Narration: ${enabled ? 'on' : 'off'}`;
  if (enabled) narrator.speak('Narration on. Use arrow keys to explore a tree.');
});
window.addEventListener('pagehide', () => narrator.stop());
document.addEventListener('visibilitychange', () => { if (document.hidden) narrator.stop(); });
$('dataset').addEventListener('change', () => loadDataset($('dataset').value));
$('variant').addEventListener('change', applyVariant);
$('include-children').addEventListener('change', () => { if (selected) selectNode(selected.side, selected.id); else paint(); });
$('dom-view').addEventListener('click', () => setView('dom'));
$('screenshot-view').addEventListener('click', () => setView('screenshot'));
$('left-semantic-view').addEventListener('click', () => setLeftView('semantic'));
$('left-raw-view').addEventListener('click', () => setLeftView('raw'));
$('clear-selection').addEventListener('click', () => { selected = hovered = null; $('clear-selection').disabled = true; paint(); renderDetails(); });

const number = value => value == null ? '—' : new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value);

function renderSelectionMetrics() {
  const output = $('selection-navigation');
  output.hidden = !selected || !metrics;
  if (output.hidden) return;
  const refs = selected.side === 'semantic' ? hierarchyRefs(index, selected.id, includeChildren()) : new Set([selected.id]);
  const targets = metrics.targets.filter(target => refs.has(target.sourceId));
  if (!targets.length) {
    output.textContent = 'No comparable navigation target in this selection. Estimates require a directly mapped heading, link, button, or field.';
    return;
  }
  const semantic = summarize(targets.map(t => t.semanticKeys)).median;
  const quick = summarize(targets.map(t => t.quickNavKeys)).median;
  output.textContent = `Modeled navigation${targets.length > 1 ? `, median over ${targets.length} targets` : ''}: hierarchy ${number(semantic)} ${semantic === 1 ? 'step' : 'steps'} · quick navigation ${number(quick)} ${quick === 1 ? 'key' : 'keys'}. Estimates exclude listening, search, and activation.`;
}

function metricCard(label, value, context) {
  const card = el('div', null, 'statistics-card');
  card.append(el('span', label), el('strong', value), el('p', context));
  return card;
}

function renderStatistics() {
  if (!metrics) return;
  const s = metrics.structure, c = metrics.coverage, nav = metrics.navigation;
  $('statistics-capture').textContent = `${data.label} · ${$('variant').selectedOptions[0].textContent}`;
  $('statistics-summary').replaceChildren(
    metricCard('Tree-size reduction', `${number(s.reductionPercent)}%`, `${number(s.domNodes)} DOM elements → ${number(s.semanticNodes)} hierarchy nodes`),
    metricCard('Maximum depth', `${number(s.domMaxDepth)} → ${number(s.semanticMaxDepth)}`, 'Raw DOM → semantic hierarchy; root depth = 0'),
    metricCard('Direct target coverage', `${number(c.percent)}%`, `${number(c.mappedTargets)} of ${number(c.eligibleTargets)} eligible source targets directly annotated`),
  );
  $('statistics-coverage').textContent = `All three distributions use the same ${nav.targetCount} directly mapped targets. ${c.eligibleTargets - c.mappedTargets} other eligible targets are excluded from navigation averages, but remain in the coverage denominator. These captures have incomplete visibility and accessibility information.`;
  const rows = document.createDocumentFragment();
  for (const [label, values] of [['Hierarchy branch traversal (steps)', nav.semantic], ['Modeled quick navigation (keys)', nav.quickNav], ['Linear target scan (stops)', nav.linear]]) {
    const row = el('tr'); row.append(el('th', label));
    for (const key of ['median', 'p90', 'mean']) row.append(el('td', number(values[key])));
    rows.append(row);
  }
  $('statistics-navigation').replaceChildren(rows);
  $('statistics-assumptions').replaceChildren(...metrics.assumptions.map(text => el('li', text)));
  const limit = showAllMetricTargets ? metrics.targets.length : 40;
  $('statistics-target-note').textContent = `Showing ${Math.min(limit, metrics.targets.length)} of ${metrics.targets.length} matched destinations in source order. Select a destination to inspect its source.`;
  $('statistics-all-targets').textContent = showAllMetricTargets ? 'Show first 40' : 'Show all targets';
  $('statistics-all-targets').hidden = metrics.targets.length <= 40;
  const targets = document.createDocumentFragment();
  for (const target of metrics.targets.slice(0, limit)) {
    const row = el('tr');
    const label = el('td');
    const inspect = el('button', short(target.label, 90), 'statistics-target-link');
    inspect.type = 'button'; inspect.title = target.label;
    inspect.addEventListener('click', () => {
      $('statistics-dialog').close(); setView('dom');
      reveal('dom', new Set([target.sourceId])); selectNode('dom', target.sourceId); focusRow('dom', target.sourceId);
    });
    label.append(inspect, el('code', `${target.sourceId} · ${target.kind}`));
    row.append(label, el('td', number(target.semanticKeys)));
    const quick = el('td', number(target.quickNavKeys)); quick.title = target.quickNavStrategy;
    row.append(quick, el('td', number(target.linearStops))); targets.append(row);
  }
  $('statistics-targets').replaceChildren(targets);
}

$('statistics-open').addEventListener('click', () => { renderStatistics(); $('statistics-dialog').showModal(); });
$('statistics-close').addEventListener('click', () => $('statistics-dialog').close());
$('statistics-all-targets').addEventListener('click', () => { showAllMetricTargets = !showAllMetricTargets; renderStatistics(); });

try {
  const response = await fetch('data/catalog.json');
  if (!response.ok) throw new Error('Capture catalog is missing. Run build_data.py first.');
  catalog = (await response.json()).datasets;
  $('dataset').replaceChildren();
  for (const item of catalog) { const option = el('option', item.label); option.value = item.id; $('dataset').append(option); }
  const requested = new URL(location.href).searchParams.get('site');
  const initial = catalog.some(item => item.id === requested) ? requested : catalog[0]?.id;
  $('dataset').value = initial; $('dataset').disabled = false;
  await loadDataset(initial);
} catch (error) {
  $('load-error').textContent = error.message; $('load-error').hidden = false;
  $('workspace').setAttribute('aria-busy', 'false');
}
