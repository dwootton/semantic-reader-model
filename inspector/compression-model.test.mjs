import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {indexData, matchNode, ancestorIds, treeRows} from './compression-model.mjs';

function fixture(duplicate=false) {
  const n=(id,parent,children,text='')=>({id,parent,children,tag:'div',text,attributes:{}});
  const source=[n('0',null,['1','2','3']),n('1','0',[],'Visible'),n('2','0',[],'Omitted'),n('3','0',[],'Script')];
  const compressed=[{...n('c0',null,duplicate?['c1','c2']:['c1']),sourceId:'0'},
    {...n('c1','c0',[],'Visible'),sourceId:'1'}];
  if(duplicate) compressed.push({...n('c2','c0',[]),sourceId:'1'});
  return {source:{roots:['0'],nodes:source},profiles:{budget:{tree:{roots:['c0'],nodes:compressed},
    sourceMap:[{id:'0',disposition:'retained',representedBy:'0'},
      {id:'1',disposition:'retained',representedBy:'1'},
      {id:'2',disposition:'deferred',representedBy:'0'},
      {id:'3',disposition:'excluded',representedBy:null}]}}};
}

test('exact matching works in both directions',()=>{
  const index=indexData(fixture(),'budget');
  assert.equal(matchNode(index,'compressed','c1').sourceRowId,'1');
  assert.equal(matchNode(index,'source','1').compressedRowId,'c1');
  assert.equal(matchNode(index,'source','1').kind,'exact');
});
test('omission fallback is explicitly representative; excluded node has no match',()=>{
  const index=indexData(fixture(),'budget');
  assert.equal(matchNode(index,'source','2').kind,'representative');
  assert.equal(matchNode(index,'source','2').compressedRowId,'c0');
  assert.equal(matchNode(index,'source','3').kind,'absent');
  assert.equal(matchNode(index,'source','3').compressedRowId,null);
});
test('duplicate source references are not treated as a unique counterpart',()=>{
  const index=indexData(fixture(true),'budget');
  assert.equal(matchNode(index,'source','1').kind,'ambiguous');
  assert.equal(matchNode(index,'source','1').compressedRowId,null);
});
test('search preserves ancestor path and matches hidden attributes',()=>{
  const data=fixture(); data.source.nodes[2].attributes={'aria-label':'Needle'};
  const index=indexData(data,'budget');
  assert.deepEqual(treeRows(index.source,index.sourceRoots,new Set(),'needle').map(r=>r.node.id),['0','2']);
  assert.deepEqual(ancestorIds(index.source,'2'),['0']);
  assert.equal(treeRows(index.source,index.sourceRoots,new Set(),'missing').length,0);
});
test('invalid trees and uncovered source maps fail',()=>{
  const data=fixture(); data.source.nodes[1].parent='invalid';
  assert.throws(()=>indexData(data,'budget'),/Inconsistent/);
  const missing=fixture();missing.profiles.budget.sourceMap.pop();
  assert.throws(()=>indexData(missing,'budget'),/cover/);
});
test('all exported captures have valid bidirectional mappings', { skip: process.env.SEMANTIC_LOCAL_CORPUS_TESTS !== '1'
  ? 'Set SEMANTIC_LOCAL_CORPUS_TESTS=1 with the original compression artifacts' : false },()=>{
  const base=new URL('./data/compression/',import.meta.url);
  const catalog=JSON.parse(fs.readFileSync(new URL('catalog.json',base)));
  assert.equal(catalog.documents.length,15);
  for(const entry of catalog.documents){
    const data=JSON.parse(fs.readFileSync(new URL(entry.file,base)));
    for(const profile of Object.keys(data.profiles)){
      const index=indexData(data,profile);
      for(const node of index.compressed.values()){
        const match=matchNode(index,'compressed',node.id);
        if(match.kind==='exact') assert.equal(matchNode(index,'source',match.sourceId).compressedRowId,node.id);
      }
    }
  }
});
