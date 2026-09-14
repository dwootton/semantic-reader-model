# Implementation contract for the DOM/IR slice

Shared working contract; the full rationale is `docs/design/dom-ir-compaction-v0.md`.

## Modules and interfaces

- `dom/parse.mjs`: export `parseDOM(source, options={})`, runs in a DOMParser-capable isolated browser, returns `{documentId, profile, roots, records, sourceHash?, metadata}`. Every record `{id,parent,children,tag?,text?,attributes,kind:'element'|'text'}` includes text nodes in ordered children. Default profile `saved-dom`, documentId `d0`. The Node adapter also accepts these JSON records directly.
- `dom/adapter.mjs`: export `adaptDOM(input, policy={})` where input `{snapshotId,documents:[parsedDocument], enrichment?}`. Returns `{observation,grounding,evidence,audit}`. Canonical IDs `${documentId}:${record.id}` within snapshot; no model aliases. Validate output via `validateObservation`.
- `validate.mjs`: export `IRValidationError`, `validateObservation(obs)`, `validateView(view)`, `observationHash(obs)`, `stableStringify(value)`, `deepFreeze(value)`. Validation returns input; throws on invalid. `observationHash` synchronous Node SHA256 of stableStringify observation. Pure transforms may use Node crypto, no DOM/I/O.
- `codec.mjs`: export `encodeModelView(view)` string and `modelPacket(view)` -> `{text,aliases:{nodes,gaps,unresolved,destinations},snapshotId,observationHash,viewHash}`; `aliases.nodes` maps short alias→canonical ID. `validateModelReferences(packet, refs)` returns canonical owned IDs, rejecting context, stale packet hash (optional expected hash) and unknown IDs. Encoder validates view and omits provenance/source handles; references all remapped.
- `compact.mjs`: export `compactIR(obs, request={})`, `expandIR(obs, priorResult, gapIds, request={})`. Returns `{view,ledger,report,partition?}`. Defaults profile `structure`, maxBytes 200000, scope all roots. `request` supports `roots`, `requiredRefs`, `maxBytes`, `maxCandidateEvaluations`<=256, `maxPartitionTrials`<=512, `maxRegions`<=64, `planRegions` boolean, optional `measureTokens` callback plus tokenizerId/maxTokens/reservedOutputTokens/promptPrefix/promptSuffix. Reports exact encoded view bytes + complete prompt bytes; tokens null unless measured. `ready` only if budgets fit, otherwise `requires_partition` or `unrepresentable_under_budget`. No automatic model dispatch.

## Observation shape

`{version:'ui-observation/0.1',snapshotId,documents:[{id,roots,containmentBasis:'dom',coverage?,coordinateSpaces?}],roots,nodes:{id:node},relations,coverage:{children,names,actions,relations},focusedNode?}`. Node `{role,children:[id],text?,name?:{text,basis:'browser'|'explicit'},description?:same,value?,states?,actions?,destination?:{id,label?},labelHints?,language?,direction?,structure?,exposure?,bounds?,coverage?}`. Missing fields make no assertion.

`structure` permits `boundary:'semantic'|'branching'`, `preserveScope:boolean`, `textMode:'normal'|'verbatim'`, `contentKind:'prose'|'code'|'math'`, `opaqueContent:'frame'|'shadow'|'media'`, numeric level/positionInSet/setSize/rowIndex/columnIndex/rowSpan/columnSpan/rowCount/columnCount. Exposure separate optional booleans accessibilityIncluded/rendered/intersectsViewport/inert/dormant.

Roles: generic document text lineBreak paragraph heading link button textField checkbox radio switch comboBox listBox option group form list listItem table row cell rowHeader columnHeader definitionList term definition image figure caption code math dialog alert status navigation main banner contentInfo complementary search tab tabList tabPanel separator slider spinButton progress tree treeItem grid gridCell menu menuItem frame unknown.

States boolean disabled readOnly required focusable selected expanded busy modal multiSelectable; checked/pressed bool or mixed; invalid bool or grammar/spelling; current bool or page/step/location/date/time. Actions `{kind,basis:'reported'|'native-semantics'}` (invoke focus setValue select toggle expand collapse increment decrement scroll scrollIntoView). Value `{kind:'text',text}` or `{kind:'number',current?,min?,max?,step?,displayText?}`.

Relation `{from,kind,targets:[{node:id}|{unresolved:key}],basis:'reported'|'native-semantics'}`. Kinds labelledBy describedBy errorMessage details controls owns activeDescendant headers labelFor formOwner choices fragmentTarget captionedBy embeds. Missing native IDREFs are opaque unresolved handles with reasons in local evidence.

## View shape

`{version:'ui-view/0.1',snapshotId,observationHash,policy:'organizer-floor/0.1',profile,scope:{roots:[originalIDs],context:[allContextIDs]},roots:[viewRootIDs],contextRoots:[],nodes:{id:ViewNode},relations,gaps:[],coverage:'complete'|'partial'|'unknown'}`.

ViewNode copies observation fields except children/text; adds membership owned/context; children ordered `[{node:id}|{gap:gapID}]`; text `{kind:'complete',value:string}` or `{kind:'extract',parts:[{text:string}|{gap:gapID}]}`. View relations add `{gap:gapID}` endpoint variant. Every view node reachable once from roots/contextRoots. Context descendants explicitly context; no group membership granted by context. Optional view.focusedNode preserves an included observed focus identity. Optional coverage.text records upstream text incompleteness; a compact legacy preview emits an unavailable text gap and is never labelled complete.

Gap `{id,owner,field:'text'|'children'|'relation'|'media'|'upstream',reason,expansion:'local'|'unavailable',omittedNodes?,omittedItems?,omittedCharacters?}`. Optional local ledger spans/content are NOT put in gaps/model payload. Ledger `{nodes:[{id,disposition:'retained'|'collapsed'|'deferred'|'excluded'|'reference-only',representedBy:string|null,reason}],fields:[...],gaps:{gapId:{nodeIds?,owner,field,start?,end?}}}`. One disposition per observation node.

## Ownership

Root owns validate/codec/schema/CLI/integration. Adapter agent owns dom/**+adapter tests. Compactor agent owns compact.mjs+compact tests. Do not modify another lane's files. Tests may use synthetic observations parsed-record fixtures until browser parsing is tested by root integration. No new dependencies or cloud operations.
