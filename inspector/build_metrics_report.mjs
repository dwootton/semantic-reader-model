import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { computeMetrics, summarize } from './metrics.mjs';

const root = new URL('./', import.meta.url);
const catalog = JSON.parse(await readFile(new URL('data/catalog.json', root), 'utf8'));
const variants = [];
for (const entry of catalog.datasets) {
  const data = JSON.parse(await readFile(new URL(`data/${entry.id}.json`, root), 'utf8'));
  for (const variant of entry.variants) variants.push({
    dataset: entry.id, label: entry.label, variant: variant.id,
    metrics: computeMetrics(data, variant.id),
  });
}
const revised = variants.filter(v => v.variant === 'revised');
const targets = revised.flatMap(v => v.metrics.targets);
const sum = key => revised.reduce((value, row) => value + row.metrics.structure[key], 0);
const eligible = revised.reduce((n, row) => n + row.metrics.coverage.eligibleTargets, 0);
const aggregate = {
  scope: 'Revised variants only: each of the 14 captures counted once. Navigation pools the same directly mapped targets, equally weighted; not task-frequency weighted.',
  captures: revised.length, domNodes: sum('domNodes'), semanticNodes: sum('semanticNodes'),
  reductionPercent: (1 - sum('semanticNodes') / sum('domNodes')) * 100,
  eligibleTargets: eligible, mappedTargets: targets.length,
  coveragePercent: eligible ? targets.length / eligible * 100 : null,
  semantic: summarize(targets.map(t => t.semanticKeys)),
  quickNav: summarize(targets.map(t => t.quickNavKeys)),
  linear: summarize(targets.map(t => t.linearStops)),
  targetComparisons: {
    hierarchyFewer: targets.filter(t => t.semanticKeys < t.quickNavKeys).length,
    equal: targets.filter(t => t.semanticKeys === t.quickNavKeys).length,
    quickNavFewer: targets.filter(t => t.semanticKeys > t.quickNavKeys).length,
    meaning: 'Comparison of unlike navigation proxies with stated operation units; not observed wins or user performance.',
  },
};
await mkdir(new URL('qa/', root), { recursive: true });
await writeFile(new URL('qa/metrics-report.json', root), JSON.stringify({ generatedAt: new Date().toISOString(), aggregate, variants }, null, 2) + '\n');
const f = n => n == null ? '—' : n.toLocaleString('en', { maximumFractionDigits: 1 });
const lines = [
  '# Structural reduction and modeled navigation', '',
  'These are calculations over saved DOM and authored hierarchy data. They are not measured screen-reader keystrokes, reading-buffer sizes, task times, or blind-user results. A high structural reduction can reflect omitted/undetailed content as well as removal of implementation wrappers.', '',
  '## Revised hierarchy by capture', '',
  'All navigation columns within each row use exactly the same directly mapped source targets. The coverage column counts all eligible inferred headings, links, buttons, and form controls; an ancestor reference does not count as direct coverage.', '',
  '| Capture | DOM → hierarchy nodes | Reduction | Direct target coverage | Hierarchy median steps | Quick-nav median keys | Target-scan median stops |',
  '|---|---:|---:|---:|---:|---:|---:|',
  ...revised.map(v => {
    const m = v.metrics;
    return `| ${v.dataset} | ${f(m.structure.domNodes)} → ${f(m.structure.semanticNodes)} | ${f(m.structure.reductionPercent)}% | ${m.coverage.mappedTargets}/${m.coverage.eligibleTargets} (${f(m.coverage.percent)}%) | ${f(m.navigation.semantic.median)} | ${f(m.navigation.quickNav.median)} | ${f(m.navigation.linear.median)} |`;
  }), '',
  '## Pooled revised results', '',
  `${f(aggregate.domNodes)} DOM elements → ${f(aggregate.semanticNodes)} semantic nodes (${f(aggregate.reductionPercent)}% reduction). ${f(aggregate.mappedTargets)} of ${f(aggregate.eligibleTargets)} eligible source targets are directly mapped (${f(aggregate.coveragePercent)}%).`, '',
  `For the same pooled mapped targets: median hierarchical traversal = ${f(aggregate.semantic.median)} modeled steps; median optimistic quick navigation = ${f(aggregate.quickNav.median)} modeled keys; median linear target scan = ${f(aggregate.linear.median)} stops.`, '',
  aggregate.scope, '',
  '## Definitions and limits', '',
  ...revised[0].metrics.assumptions.map(a => '- ' + a), '',
  'NVDA documents heading/link/button/form-field commands, an element-list filter, and text search. This model only approximates selected heading/type routes. It does not predict a reader’s choice, recognition cost, browser virtual-buffer order, active modal scope, tab order, or VoiceOver rotor use. [Official NVDA guide](https://download.nvaccess.org/releases/stable/documentation/en/userGuide.html#SingleLetterNavigation).', '',
  'Every target-level estimate and all original/revised variants are in [metrics-report.json](qa/metrics-report.json). Use the inspector’s Statistics panel for the selected capture/variant; Show all targets reveals the complete destination list.', '',
  '## Reproduce', '',
  '```sh', 'node --test inspector/metrics.test.mjs', 'node inspector/build_metrics_report.mjs', '```', '',
  'A real evaluation still needs shared tasks, initial focus/reading position, a browser and assistive-technology combination, and observed completion time/errors. These figures are useful for prioritizing tests, not for claiming a percentage improvement in accessibility.',
];
await writeFile(new URL('METRICS.md', root), lines.join('\n') + '\n');
console.log(JSON.stringify(aggregate, null, 2));
