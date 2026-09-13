import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { computeMetrics, summarize } from './metrics.mjs';

const d = (id, tag = 'button', children = [], attributes = {}, extra = {}) => ({ id, tag, children, attributes, text: id, ...extra });
const h = (id, children = [], sourceRefs = [], kind = 'group') => ({ id, children, sourceRefs, kind });
function fixture() {
  return { dom: { roots: ['body'], nodes: [d('body', 'body', ['z', 'a', 'n', 'q']), d('z'), d('a'), d('n', 'h2'), d('q')] }, variants: { revised: { rootId: 'root', nodes: [h('root', ['group', 'leaf-q']), h('group', ['leaf-a', 'leaf-z'], ['body']), h('leaf-a', [], ['a'], 'dom'), h('leaf-z', [], ['z'], 'dom'), h('leaf-q', [], ['q'], 'dom')] } } };
}
test('depth, branch choice, DOM preorder and common target denominator', () => {
  const result = computeMetrics(fixture(), 'revised');
  assert.deepEqual(result.structure, { domNodes: 5, semanticNodes: 5, reductionPercent: 0, domMaxDepth: 1, semanticMaxDepth: 2, semanticMeanLeafDepth: 5 / 3 });
  assert.deepEqual(result.coverage, { eligibleTargets: 4, mappedTargets: 3, percent: 75 });
  assert.deepEqual(result.targets.map(t => [t.sourceId, t.semanticKeys, t.linearStops]), [['z', 3, 1], ['a', 2, 2], ['q', 2, 4]]);
  assert.equal(result.navigation.targetCount, 3);
  assert.equal(result.navigation.linear.mean, 7 / 3);
  assert.equal(result.targets[2].quickNavKeys, 2);
  assert.match(result.targets[2].quickNavStrategy, /1 heading commands, then 1 next-button/);
});
test('many-to-many leaf references deduplicate targets and choose cheapest owner, never group descendants', () => {
  const data = fixture();
  data.variants.revised.nodes.find(n => n.id === 'leaf-q').sourceRefs.push('z', 'a', 'a');
  data.variants.revised.nodes.find(n => n.id === 'group').sourceRefs.push('n');
  const result = computeMetrics(data, 'revised');
  assert.equal(result.targets.length, 3);
  assert.equal(result.targets[0].semanticKeys, 2);
  assert.equal(result.targets[0].semanticDepth, 1);
  assert.equal(result.coverage.mappedTargets, 3);
});
test('ancestor visibility exclusion retains disabled, offscreen and zero-sized controls', () => {
  const data = fixture();
  const additions = [d('hidden', 'div', ['child'], { 'aria-hidden': 'true' }), d('child'), d('inert', 'div', ['inert-child'], { inert: '' }), d('inert-child'), d('disabled', 'button', [], { disabled: '' }), d('offscreen', 'input', [], {}, { rect: { x: 0, y: 9000, width: 0, height: 0 } }), d('inputhidden', 'input', [], { type: 'hidden', role: 'button' }), d('hiddenattr', 'button', [], { hidden: '' })];
  data.dom.nodes.push(...additions);
  data.dom.nodes[0].children.push('hidden', 'inert', 'disabled', 'offscreen', 'inputhidden', 'hiddenattr');
  const result = computeMetrics(data, 'revised');
  assert.equal(result.coverage.eligibleTargets, 6);
});
test('quick navigation counts only strictly subsequent targets after each heading', () => {
  const data = fixture();
  data.dom.nodes[0].children = ['z', 'n', 'a', 'q'];
  const result = computeMetrics(data, 'revised');
  assert.equal(result.targets.find(t => t.sourceId === 'q').quickNavKeys, 3);
  assert.equal(result.targets.find(t => t.sourceId === 'z').quickNavKeys, 1);
});
test('native and ARIA targets exclude non-target and unknown-only roles', () => {
  const data = fixture();
  data.dom.nodes.push(d('rolelink', 'div', [], { role: 'unknown link' }), d('unknown', 'div', [], { role: 'unknown' }), d('field', 'div', [], { role: 'textbox' }), d('anchor', 'a'), d('presentation', 'h2', [], { role: 'presentation' }));
  data.dom.nodes[0].children.push('rolelink', 'unknown', 'field', 'anchor', 'presentation');
  assert.equal(computeMetrics(data, 'revised').coverage.eligibleTargets, 6);
});
test('empty statistics and nearest-rank percentile', () => {
  assert.deepEqual(summarize([]), { median: null, p90: null, mean: null });
  assert.deepEqual(summarize([4, 1, 3, 2]), { median: 2.5, p90: 4, mean: 2.5 });
  const data = { dom: { roots: [], nodes: [] }, variants: { empty: { rootId: null, nodes: [] } } };
  const result = computeMetrics(data, 'empty');
  assert.equal(result.coverage.percent, null);
  assert.equal(result.structure.reductionPercent, null);
  assert.equal(result.navigation.semantic.median, null);
});
test('all real captures and variants have bounded coverage and common finite navigation estimates', { skip: process.env.SEMANTIC_LOCAL_CORPUS_TESTS !== '1'
  ? 'Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original 14-site corpus' : false }, async () => {
  const catalog = JSON.parse(await readFile(new URL('./data/catalog.json', import.meta.url), 'utf8'));
  assert.equal(catalog.datasets.length, 14);
  for (const entry of catalog.datasets) {
    const data = JSON.parse(await readFile(new URL(`./data/${entry.id}.json`, import.meta.url), 'utf8'));
    for (const variantId of Object.keys(data.variants)) {
      const result = computeMetrics(data, variantId);
      assert.ok(result.coverage.mappedTargets <= result.coverage.eligibleTargets);
      assert.equal(result.targets.length, result.navigation.targetCount);
      assert.equal(new Set(result.targets.map(t => t.sourceId)).size, result.targets.length);
      for (const target of result.targets) {
        assert.ok(Number.isFinite(target.semanticKeys) && target.semanticKeys >= target.semanticDepth);
        assert.ok(target.quickNavKeys >= 1 && target.quickNavKeys <= target.linearStops);
      }
    }
  }
});
test('form-field navigation includes preceding buttons in its scan stream', () => {
  const data = fixture();
  data.dom.nodes = [d('body', 'body', ['z', 'a']), d('z'), d('a', 'input')];
  const result = computeMetrics(data, 'revised');
  const field = result.targets.find(t => t.sourceId === 'a');
  assert.equal(field.quickNavKeys, 2);
  assert.match(field.quickNavStrategy, /including buttons/);
});
test('heading followed by form navigation still counts buttons after the heading', () => {
  const data = fixture();
  data.dom.nodes = [d('body', 'body', ['pre1', 'pre2', 'n', 'z', 'a']), d('pre1'), d('pre2'), d('n', 'h2'), d('z'), d('a', 'input')];
  const field = computeMetrics(data, 'revised').targets.find(t => t.sourceId === 'a');
  assert.equal(field.quickNavKeys, 3);
  assert.match(field.quickNavStrategy, /1 heading commands, then 2 next-form-control/);
});
test('non-rendered script, style, template and noscript descendants are excluded', () => {
  const data = fixture();
  for (const tag of ['script', 'style', 'template', 'noscript']) {
    data.dom.nodes[0].children.push(tag);
    data.dom.nodes.push(d(tag, tag, [`${tag}-child`]), d(`${tag}-child`));
  }
  assert.equal(computeMetrics(data, 'revised').coverage.eligibleTargets, 4);
});
