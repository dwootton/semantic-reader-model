/* Conservative D2Snap-inspired snapshot transform. Run in an isolated browser.
 * Input/output are HTML evidence, not a sanitized or executable replacement page.
 */
(() => {
  const HTML = 'http://www.w3.org/1999/xhtml';
  const noise = node => node.nodeType === 1 && ['script', 'style'].includes(node.localName);
  function walk(root) {
    const result = [];
    const visit = node => {
      result.push(node);
      for (const child of node.childNodes) visit(child);
      if (node.nodeType === 1 && node.localName === 'template' && node.content) visit(node.content);
    };
    visit(root);
    return result;
  }
  const bytes = value => new TextEncoder().encode(value).length;
  const serialize = doc => '<!DOCTYPE html>\n' + doc.documentElement.outerHTML;
  const text = doc => walk(doc).filter(n => n.nodeType === 3).map(n => n.data).join('');
  const elements = doc => walk(doc).filter(n => n.nodeType === 1);
  const removableAttribute = (node, attr) =>
    (node.namespaceURI === HTML && attr.name === 'class') ||
    (/^on/i.test(attr.name) && attr.name.toLowerCase() in node);
  const inventory = nodes => nodes.map(n => [n.namespaceURI, n.localName,
    [...n.attributes].filter(a => !removableAttribute(n, a))
      .map(a => [a.namespaceURI, a.name, a.value]).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))]);
  function downsampleHTML(source, {unwrap = false, targetBytes = null} = {}) {
    if (typeof source !== 'string') throw new TypeError('source must be HTML text');
    if (targetBytes !== null && (!Number.isFinite(targetBytes) || targetBytes <= 0)) {
      throw new RangeError('targetBytes must be positive');
    }
    const parser = new DOMParser();
    const doc = parser.parseFromString(source, 'text/html');
    const originalElements = elements(doc).length;
    const removed = {script: 0, style: 0, comments: 0, attributes: 0, wrappers: 0};
    // Remove only execution/style payloads, including within template content.
    for (const node of walk(doc).reverse()) {
      if (noise(node)) { removed[node.localName]++; node.remove(); }
      else if (node.nodeType === 8) { removed.comments++; node.remove(); }
    }
    const baselineText = text(doc);
    const baselineElements = elements(doc).length;
    const baselineHTML = serialize(doc);
    const originalNodes = elements(doc);
    // Record eligibility BEFORE stripping attributes. Unknown metadata survives.
    const redundant = new Set(originalNodes.filter(n =>
      n.namespaceURI === HTML && n.localName === 'div' && n.attributes.length === 0 &&
      n.parentElement?.namespaceURI === HTML && n.parentElement.localName === 'div' &&
      n.childNodes.length === 1 && n.firstChild.nodeType === 1 &&
      n.firstChild.namespaceURI === HTML && n.firstChild.localName === 'div'
    ));
    const expectedInventory = inventory(originalNodes.filter(n => !(unwrap && redundant.has(n))));
    for (const node of originalNodes) {
      for (const attr of [...node.attributes]) {
        // Inline style stays: it may encode hidden state. ARIA, IDs, URL and
        // data attributes stay. SVG class may carry meaning; retain it too.
        if (removableAttribute(node, attr)) {
          node.removeAttributeNode(attr); removed.attributes++;
        }
      }
    }
    if (unwrap) {
      for (const node of originalNodes.reverse()) {
        if (redundant.has(node)) { node.replaceWith(...node.childNodes); removed.wrappers++; }
      }
    }
    const html = serialize(doc);
    // Inspect the actual output through the same HTML5 parser used by Chromium.
    // Any serialization/parser repair is a failure, never a silent pass.
    const reparsed = parser.parseFromString(html, 'text/html');
    const checks = {
      textExact: text(reparsed) === baselineText,
      elementsAndAttributesExact: JSON.stringify(inventory(elements(reparsed))) === JSON.stringify(expectedInventory),
      retainedElementCount: elements(reparsed).length === baselineElements - removed.wrappers,
      roundTripStable: serialize(reparsed) === html,
    };
    if (!Object.values(checks).every(Boolean)) {
      throw new Error('Downsampling failed preservation checks: ' + JSON.stringify(checks));
    }
    return {html, report: {
      sourceBytes: bytes(source), normalizedContentBytes: bytes(baselineHTML), outputBytes: bytes(html),
      byteReduction: 1 - bytes(html) / Math.max(bytes(source), 1),
      originalElements, contentElements: baselineElements, outputElements: elements(reparsed).length,
      contentElementRetention: baselineElements ? elements(reparsed).length / baselineElements : 1,
      textCharacters: baselineText.length, textRetention: 1, removed, checks,
      targetBytes, overBudget: targetBytes !== null && bytes(html) > targetBytes,
      profile: unwrap ? 'conservative-wrapper-collapse' : 'conservative',
    }};
  }
  globalThis.downsampleHTML = downsampleHTML;
})();
