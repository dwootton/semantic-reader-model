/** Full-document browser parser. Never insert returned DOM in a live page.
 * Caller MUST block browser network requests; DOMParser inert documents can load resources.
 * Node users supply this returned JSON to adaptDOM; DOM globals stay here.
 */
export function parseDOM(source, options = {}) {
  if (typeof source !== 'string') throw new TypeError('source must be a string');
  const maxCharacters = options.maxCharacters ?? 20_000_000;
  const maxNodes = options.maxNodes ?? 200_000;
  if (!Number.isSafeInteger(maxCharacters) || maxCharacters < 1) throw new RangeError('invalid character limit');
  if (source.length > maxCharacters) throw new RangeError('DOM source limit exceeded');
  if (!Number.isSafeInteger(maxNodes) || maxNodes < 1) throw new RangeError('invalid node limit');
  const documentId = options.documentId ?? 'd0';
  const profile = options.profile ?? 'saved-dom';
  if (!['saved-dom', 'rendered-dom', 'legacy-compact-dom'].includes(profile)) throw new TypeError('unsupported DOM profile');
  if (options.networkIsolated !== true) throw new TypeError('parseDOM requires a network-isolated browser context');
  const inert = new DOMParser().parseFromString(source, 'text/html');
  const records = [{id:'0', parent:null, children:[], kind:'element', tag:'#document', attributes:{}}];
  const stack = [...inert.childNodes].reverse().map(node => ({node,parent:records[0]}));
  while (stack.length) {
    const {node,parent} = stack.pop();
    if (node.nodeType !== 1 && node.nodeType !== 3) continue;
    if (records.length >= maxNodes) throw new RangeError('DOM node limit exceeded');
    const record = {id:String(records.length),parent:parent.id,children:[],kind:node.nodeType === 3 ? 'text':'element',attributes:{}};
    if (node.nodeType === 3) record.text = node.data;
    else {
      record.tag = node.localName.toLowerCase();
      for (const attribute of node.attributes) record.attributes[attribute.name] = attribute.value;
    }
    parent.children.push(record.id); records.push(record);
    const children = node.localName === 'template' ? node.content.childNodes : node.childNodes;
    for (let i=children.length-1;i>=0;i--) stack.push({node:children[i],parent:record});
  }
  return {documentId,profile,roots:['0'],records,metadata:{parser:'browser-domparser-document/0.1',parserRepairPossible:true,sourceCharacters:source.length,baseURL:options.baseURL ?? null,...(options.referenceAttribute?{referenceAttribute:options.referenceAttribute}:{})}};
}
