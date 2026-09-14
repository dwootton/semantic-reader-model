// Score a hierarchy JSON (condensed.json schema) against an inspector dataset with metrics.mjs.
// usage: node score_variant.mjs inspector/data/SITE.json HIERARCHY.json [compare-variant]
import { readFile } from 'node:fs/promises';
const { computeMetrics } = await import(new URL('../../inspector/metrics.mjs', import.meta.url).pathname);
const [datasetPath, hierPath, compare = 'condensed'] = process.argv.slice(2);
const data = JSON.parse(await readFile(datasetPath, 'utf8'));
const h = JSON.parse(await readFile(hierPath, 'utf8'));
const variant = { rootId: h.root_id, nodes: h.nodes.map(n => ({ id: n.id, kind: n.kind, label: n.label, summary: n.summary || '', children: n.children, origin: n.origin, sourceRefs: n.source_refs })) };
data.variants.__model = variant;
const rows = [];
for (const v of [compare, '__model']) {
  if (!data.variants[v]) continue;
  const m = computeMetrics(data, v);
  rows.push({ variant: v === '__model' ? 'model' : v, nodes: m.structure.semanticNodes, depth: m.structure.semanticMaxDepth,
    coverage: `${m.coverage.mappedTargets}/${m.coverage.eligibleTargets} (${m.coverage.percent.toFixed(0)}%)`,
    semMedian: m.navigation.semantic.median, semP90: m.navigation.semantic.p90 });
}
console.table(rows);
