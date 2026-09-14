/** Emit wire schemas from the same pinned registries used at runtime. */
import { writeFile } from 'node:fs/promises';
import { ROLES, RELATIONS, ACTIONS, BOOLEAN_STATES, COVERAGE, PROFILE } from '../registries.mjs';

const enumeration = values => ({ enum: [...values] });
const str = { type: 'string' }, id = { type: 'string', minLength: 1, maxLength: 512 };
const ids = { type: 'array', items: id, uniqueItems: true };
const bool = { type: 'boolean' }, num = { type: 'number' };
const object = (properties, required = []) => ({ type: 'object', properties, required, additionalProperties: false });
const list = items => ({ type: 'array', items });
const reference = (kind, value = id) => object({ [kind]: value }, [kind]);
const coverageProps = Object.fromEntries(['children', 'names', 'actions', 'relations', 'text'].map(k => [k, enumeration(COVERAGE)]));
const coverage = object(coverageProps);
const name = object({ text: str, basis: enumeration(['browser', 'explicit']) }, ['text', 'basis']);
const states = object({ ...Object.fromEntries([...BOOLEAN_STATES].map(k => [k, bool])),
  checked: enumeration([true, false, 'mixed']), pressed: enumeration([true, false, 'mixed']),
  invalid: enumeration([true, false, 'grammar', 'spelling']), current: enumeration([true, false, 'page', 'step', 'location', 'date', 'time']) });
const structure = object({
  ...Object.fromEntries(['level', 'positionInSet', 'rowIndex', 'columnIndex', 'rowSpan', 'columnSpan'].map(k => [k, { type: 'integer', minimum: 1 }])),
  ...Object.fromEntries(['setSize', 'rowCount', 'columnCount'].map(k => [k, { type: 'integer', minimum: 0 }])),
  boundary: enumeration(['semantic', 'branching']), preserveScope: bool, textMode: enumeration(['normal', 'verbatim']),
  contentKind: enumeration(['prose', 'code', 'math']), opaqueContent: enumeration(['frame', 'shadow', 'media']),
});
const nodeProps = {
  role: enumeration(ROLES), children: ids, text: str, name, description: name,
  value: { oneOf: [object({ kind: { const: 'text' }, text: str }, ['kind', 'text']),
    object({ kind: { const: 'number' }, current: num, min: num, max: num, step: { type: 'number', exclusiveMinimum: 0 }, displayText: str }, ['kind'])] },
  states, actions: list(object({ kind: enumeration(ACTIONS), basis: enumeration(['reported', 'native-semantics']) }, ['kind', 'basis'])),
  destination: object({ id, label: str }, ['id']), labelHints: list(object({ text: str, basis: enumeration(['title', 'placeholder', 'source-label']) }, ['text', 'basis'])),
  language: { ...str, minLength: 1 }, direction: enumeration(['ltr', 'rtl', 'auto']), structure,
  exposure: object(Object.fromEntries(['accessibilityIncluded', 'rendered', 'intersectsViewport', 'inert', 'dormant'].map(k => [k, bool]))),
  bounds: object({ x: num, y: num, width: { type: 'number', minimum: 0 }, height: { type: 'number', minimum: 0 }, space: id }, ['x', 'y', 'width', 'height', 'space']), coverage,
};
const endpoint = { oneOf: [reference('node'), reference('unresolved')] };
const viewEndpoint = { oneOf: [...endpoint.oneOf, reference('gap')] };
const relation = target => object({ from: id, kind: enumeration(RELATIONS), targets: list(target), basis: enumeration(['reported', 'native-semantics']) }, ['from', 'kind', 'targets', 'basis']);
const node = object(nodeProps, ['role', 'children']);
const viewNode = object({ ...nodeProps,
  membership: enumeration(['owned', 'context']),
  children: list({ oneOf: [reference('node'), reference('gap')] }),
  text: { oneOf: [object({ kind: { const: 'complete' }, value: str }, ['kind', 'value']),
    object({ kind: { const: 'extract' }, parts: { ...list({ oneOf: [reference('text', str), reference('gap')] }), contains: reference('gap') } }, ['kind', 'parts'])] },
}, ['role', 'children', 'membership']);
const gap = object({ id, owner: id, field: enumeration(['text', 'children', 'relation', 'media', 'upstream']), reason: { ...str, minLength: 1 },
  expansion: enumeration(['local', 'unavailable']),
  ...Object.fromEntries(['omittedNodes', 'omittedItems', 'omittedCharacters'].map(k => [k, { type: 'integer', minimum: 0 }])),
}, ['id', 'owner', 'field', 'reason', 'expansion']);
const prefix = { $schema: 'https://json-schema.org/draft/2020-12/schema', $comment: 'Also run validateObservation/validateView for graph references, membership, scope, cardinality, and numeric cross-field invariants.' };
const observation = { ...prefix, $id: 'urn:semantic-reader:ui-observation:0.1', ...object({
  version: { const: 'ui-observation/0.1' }, snapshotId: id,
  documents: list({ type: 'object', properties: { id, roots: ids, containmentBasis: enumeration(['dom', 'ax', 'uia', 'native', 'synthetic']), coverage }, required: ['id', 'roots', 'containmentBasis'] }),
  roots: ids, nodes: { type: 'object', maxProperties: 100000, propertyNames: id, additionalProperties: node },
  relations: { ...list(relation(endpoint)), maxItems: 250000 }, coverage: object(coverageProps, ['children', 'names', 'actions', 'relations']), focusedNode: id,
}, ['version', 'snapshotId', 'documents', 'roots', 'nodes', 'relations', 'coverage']) };
const view = { ...prefix, $id: 'urn:semantic-reader:ui-view:0.1', ...object({
  version: { const: 'ui-view/0.1' }, snapshotId: id, observationHash: { type: 'string', pattern: '^[a-f0-9]{64}$' },
  policy: { const: 'organizer-floor/0.1' }, profile: enumeration(PROFILE),
  scope: object({ roots: ids, context: ids }, ['roots', 'context']), roots: ids, contextRoots: ids,
  nodes: { type: 'object', maxProperties: 100000, propertyNames: id, additionalProperties: viewNode },
  relations: { ...list(relation(viewEndpoint)), maxItems: 250000 }, gaps: list(gap), coverage: enumeration(COVERAGE), focusedNode: id,
}, ['version', 'snapshotId', 'observationHash', 'policy', 'profile', 'scope', 'roots', 'contextRoots', 'nodes', 'relations', 'gaps', 'coverage']) };
for (const [file, data] of [['observation-v0.schema.json', observation], ['view-v0.schema.json', view], ['registries-v0.json', { version: '0.1', roles: [...ROLES], relations: [...RELATIONS], actions: [...ACTIONS], booleanStates: [...BOOLEAN_STATES] }]]) {
  await writeFile(new URL(file, import.meta.url), JSON.stringify(data, null, 2) + '\n');
}
