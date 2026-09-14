import { createHash } from 'node:crypto';
import { validateObservation, stableStringify, deepFreeze } from '../validate.mjs';

const nativeRoles = { '#document':'document', p:'paragraph', a:'link', button:'button', textarea:'textField', select:'comboBox', option:'option', optgroup:'group', fieldset:'group', form:'form', ul:'list', ol:'list', li:'listItem', table:'table', tr:'row', td:'cell', th:'columnHeader', dl:'definitionList', dt:'term', dd:'definition', img:'image', svg:'image', figure:'figure', figcaption:'caption', caption:'caption', pre:'code', code:'code', math:'math', dialog:'dialog', nav:'navigation', main:'main', aside:'complementary', hr:'separator', br:'lineBreak', iframe:'frame', progress:'progress', meter:'progress', details:'group', summary:'button', datalist:'listBox',search:'search',area:'link'};
const ariaRoles = {button:'button',checkbox:'checkbox',radio:'radio',switch:'switch',textbox:'textField',combobox:'comboBox',listbox:'listBox',option:'option',group:'group',form:'form',list:'list',listitem:'listItem',table:'table',row:'row',cell:'cell',rowheader:'rowHeader',columnheader:'columnHeader',img:'image',figure:'figure',heading:'heading',dialog:'dialog',alertdialog:'dialog',alert:'alert',status:'status',navigation:'navigation',main:'main',banner:'banner',contentinfo:'contentInfo',complementary:'complementary',search:'search',region:'group',tab:'tab',tablist:'tabList',tabpanel:'tabPanel',separator:'separator',slider:'slider',spinbutton:'spinButton',progressbar:'progress',tree:'tree',treeitem:'treeItem',grid:'grid',gridcell:'gridCell',menu:'menu',menuitem:'menuItem',none:'generic',presentation:'generic'};
const stripped = new Set(['script','style','link','meta','base','path','polygon','polyline','circle','ellipse','rect','line','defs','use']);
const labelable = r => r && ['input','select','textarea','button','meter','progress','output'].includes(r.tag) && !(r.tag==='input'&&(r.attributes.type ?? '').toLowerCase()==='hidden');
const legacyPartial = new Set(['data-excerpt','data-deferred','data-folded','data-preview','data-omitted-items','data-relations-deferred']);
const boundaries = new Set(['form','group','list','listItem','table','row','cell','rowHeader','columnHeader','definitionList','term','definition','figure','caption','navigation','main','dialog']);
const refs = {'aria-labelledby':'labelledBy','aria-describedby':'describedBy','aria-errormessage':'errorMessage','aria-details':'details','aria-controls':'controls','aria-owns':'owns','aria-activedescendant':'activeDescendant',headers:'headers',list:'choices'};
const digest = value => createHash('sha256').update(value).digest('hex');
const own = (object,key) => Object.prototype.hasOwnProperty.call(object,key);
function fail(message) { throw new TypeError(`DOM adapter: ${message}`); }
function indexDocument(doc,maxNodes) {
  if (!doc || !/^[\w.-]+$/.test(doc.documentId) || !['saved-dom','rendered-dom','legacy-compact-dom'].includes(doc.profile)) fail('invalid document identity/profile');
  if (!Array.isArray(doc.records) || !Array.isArray(doc.roots) || doc.records.length > maxNodes) fail('invalid records or node limit exceeded');
  const map = new Map(); let characters=0;
  for (const r of doc.records) {
    if (!r || typeof r.id !== 'string' || !r.id || map.has(r.id) || !Array.isArray(r.children) || !['text','element'].includes(r.kind)) fail('invalid/duplicate record');
    if (r.kind === 'text' && (typeof r.text !== 'string' || r.children.length)) fail('invalid text record');
    if (r.kind === 'element' && typeof r.tag !== 'string') fail('missing tag');
    if (!r.attributes || Array.isArray(r.attributes) || typeof r.attributes !== 'object' || Object.values(r.attributes).some(v=>typeof v!=='string')) fail('invalid attributes');
    characters+=(r.text?.length ?? 0)+Object.entries(r.attributes).reduce((n,[k,v])=>n+k.length+v.length,0);
    if(characters>20_000_000) fail('source character limit exceeded');
    if(r.tag && r.tag!==r.tag.toLowerCase()) fail('tags must be normalized lowercase');
    map.set(r.id,r);
  }
  const visited = new Set(), order=[], stack=doc.roots.slice().reverse().map(id=>[id,null]);
  while(stack.length) {
    const [id,parent]=stack.pop(),r=map.get(id);
    if(!r || visited.has(id) || r.parent!==parent) fail('invalid containment, parent mismatch or cycle');
    visited.add(id); order.push(r);
    for(let i=r.children.length-1;i>=0;i--) stack.push([r.children[i],id]);
  }
  if(visited.size!==map.size) fail('unreachable records');
  if(doc.recordsHash && doc.recordsHash!==digest(stableStringify(doc.records))) fail('records hash mismatch');
  return {map,order};
}

/** Pure adapter for admitted records. enrichment = {snapshotId, verified:true,
 * records:[{documentId,recordId,verified:true,name?,description?,value?,states?,
 * actions?,bounds?,exposure?,focused?}]}. Unverified/conflicting joins fail closed.
 * Freeform text values are withheld by default, even in verified overlays.
 */
export function adaptDOM(input, policy={}) {
  if(!input || typeof input.snapshotId!=='string' || !input.snapshotId || !Array.isArray(input.documents) || !input.documents.length) fail('snapshot and documents required');
  const maxNodes=policy.maxNodes ?? 200_000;
  if(!Number.isSafeInteger(maxNodes)||maxNodes<1) fail('invalid node limit');
  if(input.documents.reduce((n,d)=>n+(d.records?.length ?? 0),0)>maxNodes) fail('aggregate node limit exceeded');
  const observation={version:'ui-observation/0.1',snapshotId:input.snapshotId,documents:[],roots:[],nodes:{},relations:[],coverage:{children:'complete',names:'partial',actions:'partial',relations:'partial'}};
  const grounding={snapshotId:input.snapshotId,nodes:{},destinations:{}}, evidence={snapshotId:input.snapshotId,documents:Object.create(null),nodes:{},unresolved:{}},audit={version:'dom-adapter/0.1',sourceNodes:0,retainedNodes:0,excluded:[],diagnostics:[],redactions:[]};
  const usedDocs=new Set(), internals=new Map();
  for(const doc of input.documents) {
    if(usedDocs.has(doc.documentId)) fail('duplicate document'); usedDocs.add(doc.documentId);
    const {map,order}=indexDocument(doc,maxNodes), canonical=id=>`${doc.documentId}:${id}`;
    const excluded=new Set(),htmlIds=new Map(), contexts=new Map();
    evidence.documents[doc.documentId]={profile:doc.profile,recordsHash:digest(stableStringify(doc.records)),metadata:structuredClone(doc.metadata ?? {})};
    for(const r of order) {
      audit.sourceNodes++;
      const a=r.attributes,tag=(r.tag ?? '').toLowerCase(),id=canonical(r.id),parent=contexts.get(r.parent) ?? {};
      if(a.id) htmlIds.set(a.id,[...(htmlIds.get(a.id) ?? []),r.id]);
      const context={language:a.lang ?? parent.language,direction:a.dir ?? parent.direction,verbatim:parent.verbatim || ['pre','code','math'].includes(tag), contentKind:tag==='math'?'math':['pre','code'].includes(tag)?'code':parent.contentKind,inert:parent.inert || own(a,'inert'),dormant:parent.dormant || tag==='template',disabledFieldsets:parent.disabledFieldsets ?? [], disabledOptgroup:tag==='option' && parent.ownDisabledOptgroup, ownDisabledOptgroup:tag==='optgroup' && own(a,'disabled'), partialText:parent.partialText || doc.profile==='legacy-compact-dom'&&(own(a,'data-excerpt')||own(a,'data-preview'))};
      if(tag==='fieldset' && own(a,'disabled')) context.disabledFieldsets=[...context.disabledFieldsets,r.id];
      // First legend exempts its own fieldset, while outer disabled fieldsets still apply.
      if(tag==='legend' && r.parent && map.get(r.parent)?.tag==='fieldset' && map.get(r.parent).children.find(c=>map.get(c)?.tag==='legend')===r.id) context.disabledFieldsets=context.disabledFieldsets.filter(id=>id!==r.parent);
      context.disabled=own(a,'disabled') || context.disabledFieldsets.length>0 || context.disabledOptgroup;
      contexts.set(r.id,context);
      const privateText=tag==='textarea' && !policy.allowFreeformValues;
      if(excluded.has(r.parent) || stripped.has(tag) || (r.kind==='text' && map.get(r.parent)?.tag==='textarea' && !policy.allowFreeformValues)) {
        excluded.add(r.id); audit.excluded.push({id,reason:r.kind==='text'?'freeform-value':'execution-or-drawing-payload'}); continue;
      }
      let role=r.kind==='text'?'text':nativeRoles[tag] ?? 'generic';
      if(/^h[1-6]$/.test(tag)) role='heading';
      if(['a','area'].includes(tag)&&!own(a,'href')&&!(doc.profile==='legacy-compact-dom'&&own(a,'data-destination-id'))) role='generic';
      if(tag==='select'&&(own(a,'multiple')||Number(a.size)>1)) role='listBox';
      const inputType=(a.type ?? 'text').toLowerCase();
      if(tag==='input') role=({checkbox:'checkbox',radio:'radio',range:'slider',number:'spinButton',button:'button',submit:'button',reset:'button',image:'button',hidden:'generic'})[inputType] ?? 'textField';
      if(tag==='header'||tag==='footer') { let ancestor=map.get(r.parent),sectioned=false;while(ancestor){if(['article','aside','main','nav','section'].includes(ancestor.tag)){sectioned=true;break;}ancestor=map.get(ancestor.parent);}if(!sectioned)role=tag==='header'?'banner':'contentInfo'; }
      if(tag==='th'&&['row','rowgroup'].includes(a.scope)) role='rowHeader';
      if(a.role) {
        const explicit=a.role.split(/\s+/).find(x=>own(ariaRoles,x));
        if(explicit) { if(role!=='generic'&&ariaRoles[explicit]!==role) audit.diagnostics.push({id,reason:'explicit-role-overrides-native',nativeRole:role,explicitRole:ariaRoles[explicit]}); role=ariaRoles[explicit]; } else audit.diagnostics.push({id,reason:'unsupported-role'});
      }
      const node={role,children:[]},local={originalTag:tag,...(a.role?{sourceRole:a.role}:{})}; observation.nodes[id]=node; evidence.nodes[id]=local;
      grounding.nodes[id]={documentId:doc.documentId,recordId:r.id,kind:r.kind,...(r.kind==='text'?{range:{start:0,end:r.text.length}}:{})};
      if(r.kind==='text') node.text=r.text;
      if(doc.profile==='legacy-compact-dom') {
        const markers=Object.fromEntries(Object.entries(a).filter(([key])=>legacyPartial.has(key)||key.startsWith('data-missing-')||key.startsWith('data-destination')||key==='data-target-ref'));
        if(Object.keys(markers).length)local.upstreamMarkers=markers;
        if(context.partialText)node.coverage={...node.coverage,text:'partial'};
        if(['data-deferred','data-folded','data-omitted-items','data-preview'].some(key=>own(a,key)))node.coverage={...node.coverage,children:'partial'};
        if(own(a,'data-relations-deferred'))node.coverage={...node.coverage,relations:'partial'};
        if(own(a,'data-destination-id')&&!own(a,'href')){const destination=`dest:legacy:${digest(`${doc.documentId}\0${a['data-destination-id']}`).slice(0,24)}`;node.destination={id:destination,...(own(a,'data-destination')?{label:a['data-destination']}:{})};grounding.destinations[destination]={documentId:doc.documentId,upstreamId:a['data-destination-id'],executable:false};}
      }
      if(own(a,'aria-label')) node.name={text:a['aria-label'],basis:'explicit'};
      else if(['optgroup','option'].includes(tag)&&own(a,'label')) node.name={text:a.label,basis:'explicit'};
      else if(tag==='option'&&map.get(r.parent)?.tag==='datalist'&&own(a,'value'))node.name={text:a.value,basis:'explicit'};
      else if((tag==='img'||tag==='input'&&inputType==='image')&&own(a,'alt')) node.name={text:a.alt,basis:'explicit'};
      if(own(a,'aria-description')) node.description={text:a['aria-description'],basis:'explicit'};
      if(node.name)local.nameSource=own(a,'aria-label')?'aria-label':own(a,'label')?'label':tag==='option'?'value':'alt';
      if(node.description)local.descriptionSource='aria-description';
      for(const [key,basis] of [['title','title'],['placeholder','placeholder']]) if(own(a,key)) (node.labelHints ??= []).push({text:a[key],basis});
      if(tag==='input'&&['button','submit','reset'].includes(inputType)&&own(a,'value'))(node.labelHints ??= []).push({text:a.value,basis:'source-label'});
      if(context.language) node.language=context.language;
      if(['ltr','rtl','auto'].includes(context.direction)) node.direction=context.direction;
      const structure={};
      if(boundaries.has(role)) structure.boundary='semantic';
      else if(role==='generic'&&r.children.filter(child=>{const c=map.get(child);return c.kind!=='text'||c.text.trim().length>0;}).length>1) structure.boundary='branching';
      if(context.verbatim) { structure.textMode='verbatim'; structure.contentKind=context.contentKind; }
      else structure.textMode='normal';
      if(role==='paragraph') structure.contentKind='prose';
      if(own(a,'lang')||own(a,'dir')||a.style) structure.preserveScope=true;
      if(/^h[1-6]$/.test(tag)) structure.level=Number(tag[1]);
      for(const [attr,key] of [['aria-level','level'],['aria-posinset','positionInSet'],['aria-setsize','setSize'],['aria-rowindex','rowIndex'],['aria-colindex','columnIndex'],['aria-rowcount','rowCount'],['aria-colcount','columnCount'],['rowspan','rowSpan'],['colspan','columnSpan']]) if(own(a,attr)){const numeric=Number(a[attr]),minimum=['setSize','rowCount','columnCount'].includes(key)?0:1;if(a[attr].trim()!==''&&Number.isSafeInteger(numeric)&&numeric>=minimum)structure[key]=numeric;else(local.unmappedStructure ??= {})[attr]=a[attr];}
      if(['iframe','canvas','video','audio','svg'].includes(tag)) {structure.opaqueContent=tag==='iframe'?'frame':'media';node.coverage={...node.coverage,children:'partial'};observation.coverage.children='partial';}
      node.structure=structure;
      const states={};
      for(const [attr,key] of [['disabled','disabled'],['readonly','readOnly'],['required','required']]) if(own(a,attr)&&['input','select','textarea','button','option','optgroup','fieldset'].includes(tag)) states[key]=true;
      if(context.disabled&&['input','select','textarea','button','option','optgroup','fieldset'].includes(tag)) states.disabled=true;
      for(const [attr,key] of [['aria-disabled','disabled'],['aria-readonly','readOnly'],['aria-required','required'],['aria-selected','selected'],['aria-expanded','expanded'],['aria-busy','busy'],['aria-modal','modal'],['aria-multiselectable','multiSelectable']]) if(['true','false'].includes(a[attr])) states[key]=a[attr]==='true';
      if(context.disabled&&['input','select','textarea','button','option','optgroup','fieldset'].includes(tag)){if(a['aria-disabled']==='false')audit.diagnostics.push({id,reason:'aria-disabled-conflicts-with-native'});states.disabled=true;}
      for(const [attr,key] of [['aria-checked','checked'],['aria-pressed','pressed'],['aria-invalid','invalid'],['aria-current','current']]) if(own(a,attr)) {const v=a[attr];if(['true','false'].includes(v)) states[key]=v==='true';else if((key==='invalid'?['grammar','spelling']:key==='current'?['page','step','location','date','time']:['mixed']).includes(v)) states[key]=v;}
      if(Object.keys(states).length) node.states=states;
      for(const [attr,key] of [['checked','checked'],['selected','selected'],['open','expanded']]) if(own(a,attr)) (local.defaultStates ??= {})[key]=true;
      if(local.defaultStates?.selected||local.defaultStates?.checked||local.defaultStates?.expanded)node.structure.preserveScope=true;
      if(own(a,'value')) {
        if(inputType==='password'||(!policy.allowFreeformValues&&role==='textField')) audit.redactions.push({id,field:'defaultValue',reason:'private-value'});
        else local.defaultValue=a.value;
      }
      if(privateText) {node.coverage={...node.coverage,children:'partial'};audit.redactions.push({id,field:'value',reason:'freeform-value'});observation.coverage.children='partial';}
      if(inputType==='password'&&tag==='input') {local.privateValue=true;node.coverage={...node.coverage,children:'partial'};}
      if(['slider','spinButton','progress'].includes(role)) {const value={kind:'number'};for(const [attr,key]of [['aria-valuenow','current'],['aria-valuemin','min'],['aria-valuemax','max'],['min','min'],['max','max'],['step','step']])if(own(a,attr)&&a[attr].trim()!==''&&Number.isFinite(Number(a[attr]))){const numeric=Number(a[attr]);if(key!=='step'||numeric>0)value[key]=numeric;else(local.unmappedNumeric ??= {})[attr]=a[attr];}if(own(value,'min')&&own(value,'max')&&value.min>value.max){local.conflictingRange={min:value.min,max:value.max};delete value.min;delete value.max;}if(own(a,'aria-valuetext'))value.displayText=a['aria-valuetext'];if(Object.keys(value).length>1)node.value=value;}
      if(own(a,'step')&&(a.step.trim()===''||!Number.isFinite(Number(a.step))||Number(a.step)<=0))(local.unmappedNumeric ??= {}).step=a.step;
      const actions=[]; const action=kind=>actions.push({kind,basis:'native-semantics'});
      if(!states.disabled) {
        if((['a','area'].includes(tag)&&own(a,'href'))||['button','summary'].includes(tag)||tag==='input'&&['button','submit','reset','image'].includes(inputType))action('invoke');
        if(tag==='input'&&['checkbox','radio'].includes(inputType))action(inputType==='checkbox'?'toggle':'select');
        if(['input','textarea'].includes(tag)&&!['hidden','checkbox','radio','button','submit','reset','image'].includes(inputType)&&!states.readOnly)action('setValue');
        if(tag==='select'||tag==='option')action('select');
        if(['input','textarea','select','button'].includes(tag)&&inputType!=='hidden'||tag==='a'&&own(a,'href')||own(a,'tabindex')) {states.focusable=true;node.states=states;action('focus');}
      }
      if(actions.length)node.actions=actions;
      if(own(a,'hidden'))node.exposure={rendered:false};
      if(a['aria-hidden']==='true')node.exposure={...node.exposure,accessibilityIncluded:false};
      if(context.inert)node.exposure={...node.exposure,inert:true};
      if(context.dormant)node.exposure={...node.exposure,dormant:true};
      if(tag==='input'&&inputType==='hidden')node.exposure={...node.exposure,rendered:false,accessibilityIncluded:false};
      if(own(a,'data-sr-placeholder')){node.coverage={...node.coverage,children:'partial'};observation.coverage.children='partial';audit.diagnostics.push({id,reason:'upstream-placeholder'});}
      if(tag==='noscript')audit.diagnostics.push({id,reason:'noscript-execution-context-unknown'});
      if(['a','area'].includes(tag)&&own(a,'href')) {const destination=`dest:${digest(`${doc.documentId}\0${doc.metadata?.baseURL ?? ''}\0${a.href}`).slice(0,24)}`;node.destination={id:destination};grounding.destinations[destination]={documentId:doc.documentId,href:a.href,baseURL:doc.metadata?.baseURL ?? null};}
    }
    for(const r of order)if(observation.nodes[canonical(r.id)])observation.nodes[canonical(r.id)].children=r.children.filter(c=>!excluded.has(c)).map(canonical);
    const roots=doc.roots.filter(id=>!excluded.has(id)).map(canonical);
    observation.documents.push({id:doc.documentId,roots,containmentBasis:'dom',...(doc.coordinateSpaces?{coordinateSpaces:structuredClone(doc.coordinateSpaces)}:{})});observation.roots.push(...roots);
    if(doc.profile==='legacy-compact-dom'||doc.metadata?.partial)observation.coverage.children='partial';
    internals.set(doc.documentId,{doc,map,order,canonical,htmlIds});
  }
  for(const {doc,map,order,canonical,htmlIds} of internals.values()) {
    const unresolved=(from,kind,raw,reason)=>{const key=`unresolved:${digest(`${from}\0${kind}\0${raw}\0${reason}`).slice(0,24)}`;evidence.unresolved[key]={documentId:doc.documentId,from,kind,sourceReference:raw,reason};return {unresolved:key};};
    const resolve=(from,kind,raw,requireLabelable=false)=>{const ids=htmlIds.get(raw) ?? [];if(ids.length===1&&observation.nodes[canonical(ids[0])])return requireLabelable&&!labelable(map.get(ids[0]))?unresolved(from,kind,raw,'non-labelable-target'):{node:canonical(ids[0])};return unresolved(from,kind,raw,ids.length>1?'ambiguous-html-id':ids.length?'excluded-target':'missing-target');};
    const referenceAttribute=doc.metadata?.referenceAttribute ?? 'data-r';
    const markerIds=new Map();
    if(doc.profile==='legacy-compact-dom')for(const r of order){const marker=r.attributes[referenceAttribute];if(marker)markerIds.set(marker,[...(markerIds.get(marker) ?? []),r.id]);}
    const relation=(from,kind,targets)=>{if(targets.length)observation.relations.push({from,kind,targets,basis:'native-semantics'});};
    const ancestor=(r,tag)=>{let p=map.get(r.parent);while(p){if(p.tag===tag)return p;p=map.get(p.parent);}return null;};
    for(const r of order) {
      const from=canonical(r.id);if(!observation.nodes[from])continue;
      const a=r.attributes,tag=r.tag;
      for(const [attr,kind]of Object.entries(refs))if(a[attr]?.trim())relation(from,kind,a[attr].trim().split(/\s+/).map(raw=>resolve(from,kind,raw)));
      if(tag==='label') {
        if(own(a,'for')) { if(!a.for)continue;const target=resolve(from,'labelFor',a.for,true);relation(from,'labelFor',[target]);if(target.node)relation(target.node,'labelledBy',[{node:from}]);}
        else {const queue=r.children.slice().reverse();while(queue.length){const child=map.get(queue.pop());if(!child)continue;if(labelable(child)){const target=canonical(child.id);if(observation.nodes[target]){relation(from,'labelFor',[{node:target}]);relation(target,'labelledBy',[{node:from}]);}break;}for(let i=child.children.length-1;i>=0;i--)queue.push(child.children[i]);}}
      }
      if(['fieldset','table','figure','svg'].includes(tag)) {
        const wanted={fieldset:['legend'],table:['caption'],figure:['figcaption'],svg:['title','desc']}[tag];
        for(const childId of r.children){const child=map.get(childId);if(wanted.includes(child?.tag)&&observation.nodes[canonical(childId)])relation(from,child.tag==='desc'?'describedBy':tag==='fieldset'||tag==='svg'?'labelledBy':'captionedBy',[{node:canonical(childId)}]);}
      }
      if(['input','select','textarea','button','fieldset','object','output'].includes(tag)) {
        if(a.form)relation(from,'formOwner',[resolve(from,'formOwner',a.form)]);
        else {const form=ancestor(r,'form');if(form&&observation.nodes[canonical(form.id)])relation(from,'formOwner',[{node:canonical(form.id)}]);}
      }
      if(tag==='summary'&&map.get(r.parent)?.tag==='details')relation(from,'controls',[{node:canonical(r.parent)}]);
      if(doc.profile==='legacy-compact-dom'&&a['data-target-ref']){const raw=a['data-target-ref'],ids=markerIds.get(raw) ?? [];relation(from,'fragmentTarget',[ids.length===1&&observation.nodes[canonical(ids[0])]?{node:canonical(ids[0])}:unresolved(from,'fragmentTarget',raw,ids.length>1?'ambiguous-compact-marker':'missing-compact-marker')]);}
      if(tag==='a'&&a.href?.startsWith('#')&&a.href.length>1) {let fragment=a.href.slice(1);try{fragment=decodeURIComponent(fragment);}catch{/* Preserve malformed literal fragment. */}relation(from,'fragmentTarget',[resolve(from,'fragmentTarget',fragment)]);}
    }
    if(doc.host) {
      const hostId=`${doc.host.documentId}:${doc.host.recordId}`;
      if(!observation.nodes[hostId])fail('missing embedded document host');
      relation(hostId,'embeds',doc.roots.map(id=>({node:canonical(id)})));
    }
  }
  if(input.enrichment) {
    const overlay=input.enrichment;
    if(overlay.snapshotId!==input.snapshotId||overlay.verified!==true||!Array.isArray(overlay.records))fail('unverified or stale enrichment');
    const enriched=new Set();
    for(const item of overlay.records) {
      if(own(item,'focused')&&typeof item.focused!=='boolean') fail('focused must be a boolean');
      const id=`${item.documentId}:${item.recordId}`,node=observation.nodes[id],internal=internals.get(item.documentId);
      if(item.verified!==true||!node||enriched.has(id))fail('unverified, missing or conflicting enrichment record');
      if(internal.doc.profile!=='rendered-dom'&&item.currentStateOverlay!==true)fail('saved DOM enrichment requires declared current-state overlay');
      enriched.add(id); const record=internal.map.get(item.recordId),attrs=record.attributes;
      if(own(item,'name')) {if(typeof item.name!=='string')fail('invalid enriched name');node.name={text:item.name,basis:'browser'};}
      if(own(item,'description')) {if(typeof item.description!=='string')fail('invalid enriched description');node.description={text:item.description,basis:'browser'};}
      if(item.states)node.states={...node.states,...item.states};
      if(node.states?.disabled && node.actions) {node.actions=node.actions.filter(a=>a.basis!=='native-semantics');if(!node.actions.length)delete node.actions;}
      if(own(item,'value')) {
        if(attrs.type?.toLowerCase()==='password'||!policy.allowFreeformValues&&node.role==='textField')audit.redactions.push({id,field:'value',reason:'private-value'});
        else node.value=structuredClone(item.value);
      }
      if(item.actions)node.actions=item.actions.map(action=>({kind:typeof action==='string'?action:action.kind,basis:'reported'}));
      if(item.exposure)node.exposure={...node.exposure,...item.exposure};
      if(item.bounds)node.bounds=structuredClone(item.bounds);
      if(item.focused){if(observation.focusedNode&&observation.focusedNode!==id)fail('conflicting focus');observation.focusedNode=id;}
      evidence.nodes[id].enrichment={verified:true,snapshotId:input.snapshotId};
    }
  }
  audit.retainedNodes=Object.keys(observation.nodes).length;
  validateObservation(observation);
  return deepFreeze({observation,grounding,evidence,audit});
}
