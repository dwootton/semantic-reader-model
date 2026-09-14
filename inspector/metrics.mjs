/** Structural statistics and deliberately hypothetical navigation proxies, not AT benchmarks. */
export function summarize(values) {
  if (!values.length) return { median: null, p90: null, mean: null };
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return {
    median: sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2,
    p90: sorted[Math.ceil(sorted.length * 0.9) - 1],
    mean: sorted.reduce((sum, value) => sum + value, 0) / sorted.length,
  };
}

const fieldRoles = new Set(['checkbox', 'combobox', 'listbox', 'radio', 'searchbox', 'slider', 'spinbutton', 'switch', 'textbox']);
const otherRoles = new Set(['none', 'presentation', 'article', 'banner', 'cell', 'columnheader', 'complementary', 'contentinfo', 'definition', 'dialog', 'document', 'feed', 'figure', 'form', 'grid', 'gridcell', 'group', 'img', 'list', 'listitem', 'log', 'main', 'marquee', 'math', 'menu', 'menubar', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'navigation', 'note', 'option', 'progressbar', 'region', 'row', 'rowgroup', 'rowheader', 'scrollbar', 'search', 'separator', 'status', 'tab', 'table', 'tablist', 'tabpanel', 'term', 'timer', 'toolbar', 'tooltip', 'tree', 'treegrid', 'treeitem', 'alert', 'alertdialog']);
export function targetKind(node) {
  const attrs = node.attributes || {};
  for (const role of String(attrs.role || '').toLowerCase().split(/\s+/)) {
    if (role === 'heading' || role === 'link' || role === 'button') return role;
    if (fieldRoles.has(role)) return 'field';
    if (otherRoles.has(role)) return null;
  }
  const tag = String(node.tag || '').toLowerCase();
  if (/^h[1-6]$/.test(tag)) return 'heading';
  if ((tag === 'a' || tag === 'area') && Object.hasOwn(attrs, 'href')) return 'link';
  if (tag === 'button' || tag === 'summary') return 'button';
  if (tag === 'input') {
    const type = String(attrs.type || 'text').toLowerCase();
    if (type === 'hidden') return null;
    return ['button', 'submit', 'reset', 'image'].includes(type) ? 'button' : 'field';
  }
  return ['select', 'textarea'].includes(tag) ? 'field' : null;
}
export function isHidden(node) {
  const attrs = node.attributes || {};
  return ['script', 'style', 'noscript', 'template'].includes(String(node.tag).toLowerCase()) || node.hidden === true || Object.hasOwn(attrs, 'hidden') || Object.hasOwn(attrs, 'inert')
    || String(attrs['aria-hidden']).toLowerCase() === 'true'
    || (String(node.tag).toLowerCase() === 'input' && String(attrs.type).toLowerCase() === 'hidden');
}

export function computeMetrics(data, variantId) {
  const variant = data.variants[variantId];
  if (!variant) throw new Error('This capture has no selected hierarchy variant.');
  const dom = new Map(data.dom.nodes.map(node => [node.id, node]));
  const hierarchy = new Map(variant.nodes.map(node => [node.id, node]));
  const eligible = [];
  const seenDom = new Set();
  let domMaxDepth = null;
  const kindCounts = new Map();
  let formOrdinal = 0;
  function visitDom(id, depth, hidden) {
    const node = dom.get(id);
    if (!node || seenDom.has(id)) return;
    seenDom.add(id);
    domMaxDepth = Math.max(domMaxDepth ?? 0, depth);
    hidden ||= isHidden(node);
    const kind = !hidden && targetKind(node);
    if (kind) {
      const ordinal = (kindCounts.get(kind) || 0) + 1;
      kindCounts.set(kind, ordinal);
      if (kind === 'field' || kind === 'button') formOrdinal += 1;
      eligible.push({ sourceId: id, label: String(node.attributes?.['aria-label'] || node.text || node.ownText || node.attributes?.value || node.tag || id), kind,
        linearStops: eligible.length + 1, quickNavKeys: kind === 'field' ? formOrdinal : ordinal, quickNavStrategy: `Next ${kind === 'field' ? 'form control (including buttons)' : kind} from document start` });
    }
    (node.children || []).forEach(child => visitDom(child, depth + 1, hidden));
  }
  data.dom.roots.forEach(id => visitDom(id, 0, false));
  // Oracle choice among direct type scan and preceding-heading/type-scan routes.
  const precedingHeadings = [];
  const counts = new Map();
  for (const target of eligible) {
    counts.set(target.kind, (counts.get(target.kind) || 0) + 1);
    if (target.kind === 'field' || target.kind === 'button') counts.set('formControl', (counts.get('formControl') || 0) + 1);
    if (target.kind !== 'heading') for (const heading of precedingHeadings) {
      const scanKind = target.kind === 'field' ? 'formControl' : target.kind;
      const localSteps = counts.get(scanKind) - (heading.counts.get(scanKind) || 0);
      const cost = heading.ordinal + localSteps;
      if (cost < target.quickNavKeys) {
        target.quickNavKeys = cost;
        target.quickNavStrategy = `${heading.ordinal} heading commands, then ${localSteps} next-${target.kind === 'field' ? 'form-control (including buttons)' : target.kind} commands`;
      }
    }
    if (target.kind === 'heading') precedingHeadings.push({ ordinal: counts.get('heading'), counts: new Map(counts) });
  }
  const owners = new Map();
  const seenHierarchy = new Set();
  const leafDepths = [];
  let semanticMaxDepth = null;
  function visitHierarchy(id, depth, keys) {
    const node = hierarchy.get(id);
    if (!node || seenHierarchy.has(id)) return;
    seenHierarchy.add(id);
    semanticMaxDepth = Math.max(semanticMaxDepth ?? 0, depth);
    const children = (node.children || []).filter(child => hierarchy.has(child));
    if (!children.length) leafDepths.push(depth);
    if (node.kind === 'dom' && !children.length) {
      for (const ref of node.sourceRefs || []) {
        const previous = owners.get(ref);
        if (!previous || keys < previous.semanticKeys) owners.set(ref, { semanticDepth: depth, semanticKeys: keys });
      }
    }
    children.forEach((child, index) => visitHierarchy(child, depth + 1, keys + index + 1));
  }
  visitHierarchy(variant.rootId, 0, 0);
  const targets = eligible.filter(target => owners.has(target.sourceId)).map(target => ({ ...target, ...owners.get(target.sourceId) }));
  return {
    structure: {
      domNodes: dom.size, semanticNodes: hierarchy.size,
      reductionPercent: dom.size ? (1 - hierarchy.size / dom.size) * 100 : null,
      domMaxDepth, semanticMaxDepth, semanticMeanLeafDepth: summarize(leafDepths).mean,
    },
    coverage: { eligibleTargets: eligible.length, mappedTargets: targets.length, percent: eligible.length ? targets.length / eligible.length * 100 : null },
    navigation: { targetCount: targets.length, semantic: summarize(targets.map(t => t.semanticKeys)), linear: summarize(targets.map(t => t.linearStops)), quickNav: summarize(targets.map(t => t.quickNavKeys)) },
    targets,
    assumptions: [
      'Structural reduction compares all captured DOM elements with all semantic nodes, including source leaves. It is not an accessibility-tree or screen-reader-buffer reduction.',
      'Targets are inferred native/ARIA headings, links, buttons, and fields. Known hidden, inert, aria-hidden ancestors, hidden inputs, and script/style/noscript/template subtrees are excluded; disabled, off-screen, and zero-sized elements remain. Capture visibility and role inference are incomplete, not a browser accessibility computation.',
      'Coverage requires a direct source reference from a semantic DOM leaf. Referencing an ancestor or group does not count. All navigation summaries use the same unique covered targets; uncovered targets remain in the coverage denominator.',
      'Semantic cost models an ideal hierarchical picker from its focused collapsed root: enter each branch costs one and skip each preceding sibling costs one (sum of sibling index plus one). Cheapest directly mapped leaf wins. This is not the inspector keyboard implementation or a guaranteed human route.',
      'Linear scan is the target ordinal in captured DOM preorder, starting before the first target. It counts selectable target stops, not screen-reader reading units or Tab order.',
      'Quick navigation optimistically selects the cheapest same-kind scan from document start or heading scan followed by same-kind commands strictly after that heading. It assumes the relevant screen reader/mode supports those commands; field routes scan the union of fields and buttons, while button routes use next-button. This remains an approximation of each screen reader’s control taxonomy. Oracle route selection excludes heading recognition/search cost, landmarks, rotors, text search, and remembered locations.',
      'Depth starts at zero. Median uses the middle value or pair; p90 is nearest rank. Empty statistics are null. Every matched target has equal weight; distributions are not a task-frequency model.',
      'All estimates exclude final activation, listening time, cognition, discovery, and errors. Multiple captured roots are concatenated in stored root order; this does not establish actual cross-frame navigation behavior. Real assistive-technology/user testing is required.',
    ],
  };
}
