/* Offline compression with a reversible local patch. Never insert captures into
 * the live document. Recovery consumes ONLY compressed HTML + patch, not source.
 */
(() => {
  const NS = 'http://www.w3.org/1999/xhtml';
  const size = text => new TextEncoder().encode(text).length;
  const parse = html => new DOMParser().parseFromString(html, 'text/html');
  const serialize = doc => [...doc.childNodes].map(n =>
    n.nodeType === 10 ? new XMLSerializer().serializeToString(n) :
      n.nodeType === 1 ? n.outerHTML : n.nodeType === 8 ? `<!--${n.data}-->` : n.textContent
  ).join('');
  const children = node => node.nodeType === 1 && node.localName === 'template' && node.content
    ? [...node.content.childNodes] : [...node.childNodes];
  const attrs = el => [...el.attributes].map(a => [a.namespaceURI, a.name, a.value]);
  const directText = el => children(el).filter(n => n.nodeType === 3).map(n => n.data).join('');
  function allElements(doc) {
    const nodes = [];
    const visit = n => { if (n.nodeType === 1) nodes.push(n); children(n).forEach(visit); };
    visit(doc);
    return nodes;
  }
  const setAttrs = (el, attributes) => {
    for (const [ns, name, value] of attributes) {
      if (ns) el.setAttributeNS(ns, name, value); else el.setAttribute(name, value);
    }
  };
  function restoreCompressed(html, patch) {
    if (patch.version !== 1) throw new Error('Unsupported recovery patch');
    const compressed = parse(html);
    const available = new Map();
    for (const el of allElements(compressed)) {
      const id = el.getAttribute(patch.marker);
      if (id === null || available.has(id)) throw new Error('Missing/duplicate compressed source ID: ' + el.localName + ' id=' + id);
      available.set(id, el);
    }
    const consumed = new Set();
    const target = parse('<!doctype html><html><head></head><body></body></html>');
    while (target.firstChild) target.firstChild.remove();
    function build(entry) {
      if (entry.type === 10) return target.implementation.createDocumentType(entry.name, entry.publicId, entry.systemId);
      if (entry.type === 8) return target.createComment(entry.data);
      if (entry.type !== 1) throw new Error('Unsupported patch node');
      const el = target.createElementNS(entry.ns, entry.name);
      const existing = available.get(entry.id);
      if (entry.disposition === 'retained' && !existing) throw new Error('Missing retained node ' + entry.id);
      if (existing && (existing.namespaceURI !== entry.ns || existing.localName !== entry.localName)) {
        throw new Error('Changed retained tag ' + entry.id);
      }
      if (existing) consumed.add(entry.id);
      const kept = existing ? attrs(existing).filter(a => a[1] !== patch.marker) : [];
      const removedNames = new Set(entry.removedAttributes.map(a => a[1]));
      const expectedKept = entry.attributeOrder.filter(name => !removedNames.has(name));
      if (existing && JSON.stringify(kept.map(a => a[1])) !== JSON.stringify(expectedKept)) {
        throw new Error('Unexpected/missing retained attributes');
      }
      const merged = new Map([...kept, ...entry.removedAttributes].map(a => [a[1], a]));
      const ordered = entry.attributeOrder.map(name => {
        if (!merged.has(name)) throw new Error('Missing attribute ' + name);
        return merged.get(name);
      });
      setAttrs(el, ordered);
      const owner = el.localName === 'template' && el.content ? el.content : el;
      const text = existing ? directText(existing) : entry.storedText;
      const expectedLength = entry.children.filter(c => c.type === 3).reduce((n, c) => n + c.length, 0);
      if (typeof text !== 'string' || text.length !== expectedLength) throw new Error('Changed text length');
      for (const item of entry.children) {
        if (item.type === 3) {
          if (typeof text !== 'string' || item.offset + item.length > text.length) throw new Error('Missing text');
          owner.appendChild(target.createTextNode(text.slice(item.offset, item.offset + item.length)));
        } else owner.appendChild(build(item));
      }
      return el;
    }
    for (const entry of patch.documentChildren) target.appendChild(build(entry));
    if (consumed.size !== available.size) throw new Error('Unexpected compressed nodes');
    return serialize(target);
  }
  function runRecoveryExperiment(source, profile = 'conservative', metadata = []) {
    if (!['conservative', 'wrappers'].includes(profile)) throw new Error('Unknown profile');
    const doc = parse(source);
    const original = serialize(doc);
    const elements = allElements(doc);
    let marker = 'data-sr-node';
    while (elements.some(n => n.hasAttribute(marker))) marker += '-x';
    const ids = new Map(elements.map((n, i) => [n, 'n' + i]));
    const sourceMatches = metadata.map(item => {
      let matches = [];
      try { matches = [...doc.querySelectorAll(item.css_path)]; } catch { /* invalid original selector */ }
      const match = matches.length === 1 && matches[0].localName === item.tag.toLowerCase() ? matches[0] : null;
      return {captureId: item.id, sourceId: match ? ids.get(match) : null, status: match ? 'matched' : 'unresolved'};
    });
    const entries = new Map();
    const records = [];
    function record(node, excluded = false) {
      if (node.nodeType === 10) return {type: 10, name: node.name, publicId: node.publicId, systemId: node.systemId};
      if (node.nodeType === 8) return {type: 8, data: node.data};
      if (node.nodeType !== 1) throw new Error('Unsupported source node ' + node.nodeType);
      excluded ||= ['script', 'style'].includes(node.localName);
      // Eligibility is frozen before source markers or attribute changes.
      const collapsible = profile === 'wrappers' && !excluded && node.namespaceURI === NS &&
        node.localName === 'div' && !node.attributes.length &&
        node.parentElement?.namespaceURI === NS && node.parentElement.localName === 'div' &&
        node.childNodes.length === 1 && node.firstChild.nodeType === 1 &&
        node.firstChild.namespaceURI === NS && node.firstChild.localName === 'div';
      const entry = {type: 1, id: ids.get(node), ns: node.namespaceURI, name: node.tagName,
        localName: node.localName,
        disposition: excluded ? 'excluded' : collapsible ? 'collapsed' : 'retained',
        attributeOrder: attrs(node).map(a => a[1]), removedAttributes: [], children: []};
      // HTML tagName is uppercase; createElementNS needs the original localName.
      if (node.namespaceURI === NS) entry.name = node.localName;
      entries.set(node, entry); records.push(entry);
      let offset = 0;
      for (const child of children(node)) {
        if (child.nodeType === 3) {
          entry.children.push({type: 3, offset, length: child.data.length}); offset += child.data.length;
        } else entry.children.push(record(child, excluded));
      }
      if (entry.disposition !== 'retained') entry.storedText = directText(node);
      return entry;
    }
    const patch = {version: 1, marker, profile, documentChildren: [...doc.childNodes].map(n => record(n))};
    for (const node of elements) {
      const entry = entries.get(node);
      for (const attr of [...node.attributes]) {
        const remove = entry.disposition !== 'retained' ||
          (node.namespaceURI === NS && attr.name === 'class') ||
          (/^on/i.test(attr.name) && attr.name.toLowerCase() in node);
        if (remove) { entry.removedAttributes.push([attr.namespaceURI, attr.name, attr.value]); node.removeAttributeNode(attr); }
      }
      if (entry.disposition === 'retained') node.setAttribute(marker, entry.id);
    }
    // Comments are recovery-only; retained text is never copied into the patch.
    function removeComments(n) {
      for (const child of children(n)) {
        if (child.nodeType === 8) child.remove(); else removeComments(child);
      }
    }
    removeComments(doc);
    for (const node of [...elements].reverse()) {
      const disposition = entries.get(node).disposition;
      if (disposition === 'excluded') node.remove();
      if (disposition === 'collapsed') node.replaceWith(...node.childNodes);
    }
    const html = serialize(doc);
    const reparsed = parse(html);
    const after = new Map(allElements(reparsed).map(n => [n.getAttribute(marker), n]));
    const retained = records.filter(e => e.disposition === 'retained');
    const collapsed = records.filter(e => e.disposition === 'collapsed');
    const excluded = records.filter(e => e.disposition === 'excluded');
    const expectedParent = new Map();
    function parents(entry, ancestor = null) {
      if (entry.type !== 1) return;
      if (entry.disposition === 'retained') { expectedParent.set(entry.id, ancestor); ancestor = entry.id; }
      for (const child of entry.children) parents(child, ancestor);
    }
    patch.documentChildren.forEach(e => parents(e));
    let exactText = true, exactAttributes = true, exactParents = true;
    for (const node of elements) {
      const entry = entries.get(node);
      if (entry.disposition !== 'retained') continue;
      const result = after.get(entry.id);
      if (!result) { exactText = exactAttributes = exactParents = false; continue; }
      exactText &&= directText(node) === directText(result);
      exactAttributes &&= JSON.stringify(attrs(node)) === JSON.stringify(attrs(result));
    }
    // Check parent IDs including template ownership (parentElement alone loses it).
    function checkParents(n, ancestor = null) {
      if (n.nodeType === 1) {
        const id = n.getAttribute(marker);
        exactParents &&= expectedParent.get(id) === ancestor;
        ancestor = id;
      }
      children(n).forEach(c => checkParents(c, ancestor));
    }
    checkParents(reparsed);
    let recovered = null, recoveryError = null;
    try { recovered = restoreCompressed(html, patch); } catch (error) { recoveryError = error.message; }
    const checks = {
      sourceRoundTripStable: serialize(parse(original)) === original,
      uniqueSourceIds: after.size === retained.length && after.size === allElements(reparsed).length && !after.has(null),
      retainedTextExact: exactText, retainedAttributesExact: exactAttributes, parentsExact: exactParents,
      retainedOrderExact: JSON.stringify([...after.keys()]) === JSON.stringify(retained.map(e => e.id)),
      stableHTML: serialize(reparsed) === html,
      recoveredDOMExact: recovered === original,
    };
    const report = {profile, recoveryError, passed: Object.values(checks).every(Boolean), checks,
      metadataJoin: {total: metadata.length, matched: sourceMatches.filter(m => m.status === 'matched').length,
        failed: sourceMatches.filter(m => m.status !== 'matched').length},
      sourceElements: elements.length, retainedElements: retained.length,
      collapsedElements: collapsed.length, excludedElements: excluded.length,
      contentElements: elements.length - excluded.length,
      contentRetention: retained.length / Math.max(1, elements.length - excluded.length),
      recoveredElements: checks.recoveredDOMExact ? allElements(parse(recovered)).length : null,
      compressedBytes: size(html), normalizedSourceBytes: size(original), patchBytes: size(JSON.stringify(patch)),
      textRecovery: 'Retained direct text read from compressed HTML; excluded text stored only in local patch.',
      scope: 'Browser-normalized HTML DOM; no live behavior or organizer quality claim.'};
    const recordById = new Map(records.map(e => [e.id, e]));
    for (const match of sourceMatches) {
      match.disposition = match.sourceId ? recordById.get(match.sourceId)?.disposition : 'unknown';
    }
    return {html, patch, report, sourceMatches};
  }
  globalThis.runRecoveryExperiment = runRecoveryExperiment;
  globalThis.restoreCompressed = restoreCompressed;
})();
