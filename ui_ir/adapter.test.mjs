import test from 'node:test';
import assert from 'node:assert/strict';
import {adaptDOM} from './dom/adapter.mjs';
import {parseDOM} from './dom/parse.mjs';

const element=(tag,attributes={},...children)=>({tag,attributes,children});
function fixture(children,profile='saved-dom',documentId='d0') {
  const records=[];const stack=[{node:element('#document',{},...children),parent:null}];
  while(stack.length){const {node,parent}=stack.pop(),id=String(records.length);const record=typeof node==='string'?{id,parent,kind:'text',text:node,attributes:{},children:[]}:{id,parent,kind:'element',tag:node.tag,attributes:node.attributes,children:[]};records.push(record);if(parent!==null)records[Number(parent)].children.push(id);if(typeof node!=='string')for(let i=node.children.length-1;i>=0;i--)stack.push({node:node.children[i],parent:id});}
  return {snapshotId:'test',documents:[{documentId,profile,roots:['0'],records}]};
}
const nodeByRole=(bundle,role)=>Object.entries(bundle.observation.nodes).find(([,n])=>n.role===role);

test('mixed Unicode text is owned once in original order, deterministic and frozen',()=>{
  const input=fixture([element('p',{},'Pay 🦊 ',element('a',{href:'/bill'},'invoice'),' now')]);
  const a=adaptDOM(input),b=adaptDOM(input);assert.deepEqual(a,b);
  const [,p]=nodeByRole(a,'paragraph');assert.deepEqual(p.children,['d0:2','d0:3','d0:5']);assert.equal(p.text,undefined);
  assert.equal(a.observation.nodes['d0:2'].text,'Pay 🦊 ');assert.equal(a.observation.nodes['d0:3'].children[0],'d0:4');assert.ok(Object.isFrozen(a.observation.nodes));
});

test('saved current states remain unknown while default checked/selected/open are local',()=>{
  const b=adaptDOM(fixture([element('input',{type:'checkbox',checked:'',value:'yes'}),element('option',{selected:''},'A'),element('details',{open:''},'More')]));
  assert.equal(b.observation.nodes['d0:1'].states.checked,undefined);assert.equal(b.evidence.nodes['d0:1'].defaultStates.checked,true);
  assert.equal(b.evidence.nodes['d0:1'].defaultValue,'yes');assert.equal(b.observation.nodes['d0:1'].value,undefined);
  assert.equal(b.evidence.nodes['d0:2'].defaultStates.selected,true);assert.equal(b.observation.nodes['d0:4'].states,undefined);
});

test('verified rendered overlay preserves false states and known empty names/value',()=>{
  const input=fixture([element('input',{type:'checkbox',checked:''}),element('input',{value:'default'})],'rendered-dom');
  input.enrichment={snapshotId:'test',verified:true,records:[{documentId:'d0',recordId:'1',verified:true,name:'',states:{checked:false}},{documentId:'d0',recordId:'2',verified:true,value:{kind:'text',text:''}}]};
  const b=adaptDOM(input,{allowFreeformValues:true});assert.deepEqual(b.observation.nodes['d0:1'].name,{text:'',basis:'browser'});assert.equal(b.observation.nodes['d0:1'].states.checked,false);assert.equal(b.observation.nodes['d0:2'].value.text,'');
  input.enrichment.snapshotId='other';assert.throws(()=>adaptDOM(input),/stale enrichment/);
});

test('labels, help, errors, header, caption and fragment references preserve hidden qualifiers',()=>{
  const b=adaptDOM(fixture([element('form',{id:'f'},element('label',{for:'zip'},'Postal code'),element('input',{id:'zip','aria-describedby':'help','aria-errormessage':'error','aria-invalid':'true'}),element('p',{id:'help',hidden:''},'Only available to members.'),element('p',{id:'error'},'Required')),element('table',{},element('caption',{},'Prices'),element('tr',{},element('th',{id:'head'},'USD'),element('td',{headers:'head'},'$8'))),element('a',{href:'#zip'},'Edit')]));
  for(const kind of ['labelFor','labelledBy','describedBy','errorMessage','formOwner','headers','captionedBy','fragmentTarget'])assert.ok(b.observation.relations.some(r=>r.kind===kind),kind);
  assert.ok(Object.values(b.observation.nodes).some(n=>n.text==='Only available to members.'));
  assert.ok(Object.values(b.observation.nodes).some(n=>n.exposure?.rendered===false));
});

test('duplicate and missing HTML IDs produce unresolved endpoints within document scope',()=>{
  const input=fixture([element('p',{id:'dup'},'a'),element('p',{id:'dup'},'b'),element('input',{'aria-labelledby':'dup missing'})]);
  const other=fixture([element('label',{id:'dup'},'unique'),element('input',{'aria-labelledby':'dup'})],'saved-dom','d1');input.documents.push(other.documents[0]);
  const b=adaptDOM(input);assert.equal(Object.keys(b.evidence.unresolved).length,2);assert.ok(b.observation.relations.find(r=>r.from.startsWith('d1:')).targets[0].node.startsWith('d1:'));
});

test('inherited language and disabled fieldset honor first legend exemption',()=>{
  const b=adaptDOM(fixture([element('fieldset',{disabled:'',lang:'fr'},element('legend',{},element('input',{type:'checkbox'})),element('input',{type:'checkbox'}))]));
  assert.equal(b.observation.nodes['d0:3'].states.disabled,undefined);assert.equal(b.observation.nodes['d0:4'].states.disabled,true);assert.equal(b.observation.nodes['d0:4'].language,'fr');assert.equal(b.observation.nodes['d0:4'].actions,undefined);
});

test('password and freeform content stay out of observation and sidecar defaults',()=>{
  const input=fixture([element('input',{type:'password',value:'secret'}),element('textarea',{},'private message'),element('script',{},'bad()')],'rendered-dom');
  input.enrichment={snapshotId:'test',verified:true,records:[{documentId:'d0',recordId:'1',verified:true,value:{kind:'text',text:'secret'}}]};
  const b=adaptDOM(input);assert.ok(!JSON.stringify(b).includes('secret'));assert.ok(!JSON.stringify(b).includes('private message'));assert.ok(!JSON.stringify(b.observation).includes('bad()'));assert.ok(b.audit.redactions.length>=2);assert.equal(b.observation.coverage.children,'partial');
});

test('role button alone supplies no invented native action; native button does',()=>{
  const b=adaptDOM(fixture([element('div',{role:'button'},'Fake'),element('button',{},'Real')]));assert.equal(b.observation.nodes['d0:1'].actions,undefined);assert.ok(b.observation.nodes['d0:3'].actions.some(a=>a.kind==='invoke'));
});

test('vector label evidence survives stripped drawing payload; frames are opaque',()=>{
  const b=adaptDOM(fixture([element('svg',{},element('title',{},'Warehouse map'),element('desc',{},'Exit to the west'),element('path',{d:'M 0 0'})),element('iframe',{title:'Embedded tool'})]));assert.equal(b.observation.nodes['d0:1'].structure.opaqueContent,'media');assert.ok(b.observation.relations.some(r=>r.kind==='labelledBy'));assert.ok(b.audit.excluded.length);assert.equal(nodeByRole(b,'frame')[1].coverage.children,'partial');
});

test('malformed graphs, conflicting joins and input limits fail closed',()=>{
  const input=fixture([element('p',{},'hello')]);input.documents[0].records[1].children.push('1');assert.throws(()=>adaptDOM(input),/containment/);
  assert.throws(()=>adaptDOM(fixture(['a']),{maxNodes:1}),/limit/);
  const duplicate=fixture(['a']);duplicate.documents.push(duplicate.documents[0]);assert.throws(()=>adaptDOM(duplicate),/duplicate document/);
  assert.throws(()=>parseDOM(123),/string/);
});

test('deep records are processed iteratively without stack overflow',()=>{
  const count=6000,records=Array.from({length:count},(_,i)=>({id:String(i),parent:i?String(i-1):null,children:i<count-1?[String(i+1)]:[],kind:'element',tag:i?'div':'#document',attributes:{}}));
  const b=adaptDOM({snapshotId:'deep',documents:[{documentId:'d',profile:'saved-dom',roots:['0'],records}]});assert.equal(b.audit.retainedNodes,count);
});

test('non-native disabled attributes do not disable descendant controls',()=>{
  const b=adaptDOM(fixture([element('div',{disabled:''},element('button',{},'Use'))]));assert.equal(b.observation.nodes['d0:2'].states.disabled,undefined);assert.ok(b.observation.nodes['d0:2'].actions.length);
});

test('explicit document namespaces and overlay dictionaries do not mutate caller input',()=>{
  const input=fixture([element('p',{},'ok')],'saved-dom','__proto__');input.documents[0].metadata={partial:true};
  const b=adaptDOM(input);assert.equal(Object.getPrototypeOf(b.evidence.documents),null);assert.equal(Object.isFrozen(input.documents[0].metadata),false);
});

test('native defaults do not leak into actions or numeric current value',()=>{
  const b=adaptDOM(fixture([element('input',{type:'range',min:'0',max:'10',value:'5'}),element('div',{role:'slider','aria-valuenow':'4'})]));assert.deepEqual(b.observation.nodes['d0:1'].value,{kind:'number',min:0,max:10});assert.equal(b.observation.nodes['d0:2'].value.current,4);assert.equal(b.observation.nodes['d0:2'].actions,undefined);
});

test('invalid or unknown native numeric assertions remain evidence without corrupting IR',()=>{
  const b=adaptDOM(fixture([element('div',{role:'list','aria-setsize':'-1'}),element('input',{type:'range',min:'10',max:'0',step:'0'}),element('td',{rowspan:'0'})]));
  assert.equal(b.observation.nodes['d0:1'].structure.setSize,undefined);assert.equal(b.evidence.nodes['d0:1'].unmappedStructure['aria-setsize'],'-1');assert.equal(b.observation.nodes['d0:2'].value,undefined);
});

test('optgroup naming, default choice protection, datalist and summary relationships',()=>{
  const b=adaptDOM(fixture([element('select',{},element('optgroup',{label:'Europe'},element('option',{selected:''},'France'))),element('input',{list:'suggestions'}),element('datalist',{id:'suggestions'},element('option',{value:'A'})),element('details',{},element('summary',{},'Details'))]));
  assert.equal(b.observation.nodes['d0:2'].name.text,'Europe');assert.equal(b.observation.nodes['d0:3'].structure.preserveScope,true);assert.equal(b.observation.nodes['d0:3'].states,undefined);assert.ok(b.observation.relations.some(r=>r.kind==='choices'));assert.ok(b.observation.relations.some(r=>r.kind==='controls'));
});

test('aria-disabled false cannot weaken native disabled behavior',()=>{
  const b=adaptDOM(fixture([element('button',{disabled:'','aria-disabled':'false'},'No')]));assert.equal(b.observation.nodes['d0:1'].states.disabled,true);assert.equal(b.observation.nodes['d0:1'].actions,undefined);assert.ok(b.audit.diagnostics.some(d=>d.reason==='aria-disabled-conflicts-with-native'));
});

test('implicit label selects first labelable descendant in preorder and skips hidden inputs',()=>{
  const b=adaptDOM(fixture([element('label',{},element('input',{type:'hidden'}),element('span',{},element('input',{id:'first'})),element('input',{id:'second'})),element('label',{for:'notfield'},'No'),element('div',{id:'notfield'},'Content')]));
  assert.equal(b.observation.relations.find(r=>r.from==='d0:1'&&r.kind==='labelFor').targets[0].node,'d0:4');
  const invalid=b.observation.relations.find(r=>r.from==='d0:6'&&r.kind==='labelFor');assert.ok(invalid.targets[0].unresolved);assert.equal(b.evidence.unresolved[invalid.targets[0].unresolved].reason,'non-labelable-target');
});

test('trusted legacy markers preserve upstream partial text, child and relationship evidence',()=>{
  const b=adaptDOM(fixture([element('p',{'data-excerpt':'true'},'Partial text…'),element('section',{'data-folded':'true','data-preview':'A preview','data-omitted-items':'12','data-relations-deferred':'aria-describedby'},'Remaining')],'legacy-compact-dom'));
  assert.equal(b.observation.nodes['d0:1'].coverage.text,'partial');assert.equal(b.observation.nodes['d0:2'].coverage.text,'partial');assert.equal(b.observation.nodes['d0:3'].coverage.children,'partial');assert.equal(b.observation.nodes['d0:3'].coverage.relations,'partial');assert.equal(b.evidence.nodes['d0:3'].upstreamMarkers['data-omitted-items'],'12');
  const plain=adaptDOM(fixture([element('p',{'data-excerpt':'true'},'Author data attribute')]));assert.equal(plain.observation.nodes['d0:1'].coverage,undefined);
});

test('legacy destinations keep link identity without inventing execution and resolve marker targets',()=>{
  const input=fixture([element('a',{'data-destination-id':'u0','data-destination':'example.test/path','data-target-ref':'target'},'One'),element('a',{'data-destination-id':'u1','data-destination':'example.test/path'},'Two'),element('p',{'data-capture':'target'},'Destination')],'legacy-compact-dom');
  input.documents[0].metadata={referenceAttribute:'data-capture'};const b=adaptDOM(input);
  assert.equal(b.observation.nodes['d0:1'].role,'link');assert.equal(b.observation.nodes['d0:1'].actions,undefined);assert.notEqual(b.observation.nodes['d0:1'].destination.id,b.observation.nodes['d0:3'].destination.id);assert.equal(b.observation.relations.find(r=>r.kind==='fragmentTarget').targets[0].node,'d0:5');
});

test('focus enrichment rejects truthy nonboolean values',()=>{
  const input=fixture([element('button',{},'Go')],'rendered-dom');
  input.enrichment={snapshotId:input.snapshotId,verified:true,records:[{documentId:'d0',recordId:'1',verified:true,focused:'false'}]};
  assert.throws(()=>adaptDOM(input),/focused must be a boolean/);
});

test('formatting whitespace does not create a false branching boundary',()=>{
  const b=adaptDOM(fixture([element('div',{},'\n',element('p',{},'Read me'),'\n')]));
  assert.equal(b.observation.nodes['d0:1'].structure.boundary,undefined);
  assert.equal(b.observation.nodes['d0:1'].children.length,3);
});
