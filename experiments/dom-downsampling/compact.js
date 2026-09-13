/* Bounded organizer evidence, not lossless HTML. All omission provenance stays
 * local; data-r references support explicit expansion from the immutable source.
 */
(() => {
  const NS = 'http://www.w3.org/1999/xhtml';
  const bytes = value => new TextEncoder().encode(value).length;
  const parse = value => new DOMParser().parseFromString(value, 'text/html');
  const serialize = doc => '<!DOCTYPE html>\n' + doc.documentElement.outerHTML;
  const children = node => node.localName === 'template' && node.content
    ? [...node.content.childNodes] : [...node.childNodes];
  const elements = root => {
    const output = [];
    const visit = node => { if (node.nodeType === 1) output.push(node); children(node).forEach(visit); };
    visit(root); return output;
  };
  const normalize = text => text.replace(/\s+/g, ' ').trim();
  const textNodes = root => {
    const output = [];
    const visit = node => { if (node.nodeType === 3) output.push(node); else children(node).forEach(visit); };
    visit(root); return output;
  };
  const HEADINGS = 'h1,h2,h3,h4,h5,h6,legend,caption,summary,[role="heading"]';
  const CONTROL = 'a,button,input,select,textarea,[role="button"],[role="checkbox"],[role="combobox"],[role="radio"],[role="switch"],[role="slider"],[role="textbox"],[tabindex]';
  const RELATIONS = new Set(['for','headers','list','form','aria-labelledby','aria-describedby',
    'aria-controls','aria-owns','aria-details','aria-errormessage','aria-activedescendant']);
  const KEEP = new Set(['id','role','type','name','value','label','alt','title','placeholder','checked','selected',
    'disabled','required','readonly','multiple','open','hidden','inert','tabindex','lang','dir',
    'colspan','rowspan','scope','start','reversed','min','max','step','pattern','autocomplete']);
  const NOISE = new Set(['script','style','link','meta','base']);
  const EXCEPTION = '[selected],[checked],[required],[disabled],[aria-disabled="true"],[aria-required="true"],[aria-selected="true"],[aria-checked="true"],[aria-checked="mixed"],'+
    '[aria-current]:not([aria-current="false"]),[aria-invalid]:not([aria-invalid="false"]),[aria-expanded="true"],[role="alert"],[role="status"]';
  const excerpt = (value, limit) => {
    if (value.length <= limit) return value;
    const cut = value.slice(0, limit);
    const space = cut.lastIndexOf(' ');
    return cut.slice(0, space >= limit / 2 ? space : limit).trimEnd() + '…';
  };
  function compactDOM(source, options = {}) {
    const profile = options.profile ?? 'budget';
    const targetRatio = options.targetRatio ?? 0.1;
    if (!['structure','excerpt','budget'].includes(profile)) throw new Error('Unknown compact profile');
    if (!Number.isFinite(targetRatio) || targetRatio <= 0 || targetRatio > 1) throw new Error('Invalid targetRatio');
    const doc = parse(source), originalElements = elements(doc);
    const ids = new Map(originalElements.map((el, i) => [el, i.toString(36)]));
    const recordMap = new Map(), ledger = [], stages = [];
    const originalText = new Map(), originalAttributes = new Map();
    const sourceTextCharacters = textNodes(doc.body).filter(n => !n.parentElement?.closest('script,style,template,noscript')).reduce((total,n)=>total+normalize(n.data).length,0);
    const sourceRoundTripStable = parse(serialize(doc)).documentElement.outerHTML === doc.documentElement.outerHTML;
    // References are snapshot-local and don't overload original HTML id values.
    let marker = 'data-r';
    while (originalElements.some(el => el.hasAttribute(marker))) marker += '-x';
    const relationTargets = new Set();
    for (const el of originalElements) {
      for (const a of el.attributes) {
        if (RELATIONS.has(a.name)) a.value.split(/\s+/).filter(Boolean).forEach(v => relationTargets.add(v));
        if (a.name === 'href' && a.value.startsWith('#')) {
          let target = a.value.slice(1);
          try { target = decodeURIComponent(target); } catch { /* Preserve literal malformed escapes. */ }
          relationTargets.add(target);
        }
      }
      originalAttributes.set(el, [...el.attributes].map(a => [a.name,a.value]));
      originalText.set(el, normalize(children(el).filter(n => n.nodeType === 3).map(n => n.data).join(' ')));
      recordMap.set(el, {id: ids.get(el), tag: el.localName, parent: ids.get(el.parentElement) ?? null,
        disposition: 'retained', representedBy: ids.get(el), reasons: []});
    }
    const record = (el, reason) => { const r = recordMap.get(el); if (!r.reasons.includes(reason)) r.reasons.push(reason); };
    const markSubtree = (el, disposition, owner, reason) => {
      for (const child of elements(el)) {
        const r = recordMap.get(child);
        if (!r) continue;
        r.disposition = disposition; r.representedBy = owner ? ids.get(owner) : null; record(child, reason);
      }
    };
    const stage = name => stages.push({name, elements: elements(doc).length, bytes: bytes(serialize(doc))});
    stage('parsed-source');
    // Exclude nonreading payload, but mark template/alternative content deferred.
    for (const el of [...originalElements].reverse()) {
      if (!el.isConnected && !doc.documentElement.contains(el)) continue;
      if (NOISE.has(el.localName)) { markSubtree(el, 'excluded', null, 'nonreading-payload'); el.remove(); }
      else if (['template','noscript'].includes(el.localName)) {
        markSubtree(el, 'deferred', el.parentElement, 'inactive-or-alternative-content'); el.remove();
      }
    }
    function comments(node) {
      for (const child of children(node)) {
        if (child.nodeType === 8) child.remove(); else comments(child);
      }
    }
    comments(doc);
    // Head is title-only. Other head content remains accounted for in the ledger.
    for (const el of [...doc.head.children]) if (el.localName !== 'title') {
      markSubtree(el, 'excluded', null, 'document-metadata'); el.remove();
    }
    const removedAttributes = {}, destinationIds = new Map(), fragmentTargets = new Map();
    for (const el of elements(doc)) {
      const old = [...el.attributes];
      const explicitlyHidden = el.hasAttribute('hidden') ||
        /(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b/i.test(el.getAttribute('style') ?? '');
      for (const a of old) {
        const keep = (KEEP.has(a.name) || RELATIONS.has(a.name) || a.name.startsWith('aria-')) &&
          (a.name !== 'id' || relationTargets.has(a.value));
        if (!keep) {
          removedAttributes[a.name] = (removedAttributes[a.name] ?? 0) + bytes(a.name + a.value);
          el.removeAttribute(a.name); record(el, 'attribute:' + a.name);
        }
      }
      // Never ship embedded assets or tracking query strings as navigation evidence.
      const href = old.find(a => a.name === 'href')?.value;
      if (el.localName === 'a' && href) {
        if (!destinationIds.has(href)) destinationIds.set(href, 'u' + destinationIds.size.toString(36));
        el.setAttribute('data-destination-id', destinationIds.get(href));
        if (href.startsWith('#')) {
          el.setAttribute('data-destination-kind', 'fragment');
          let target = href.slice(1);
          try { target = decodeURIComponent(target); } catch { /* Keep literal invalid escapes. */ }
          fragmentTargets.set(el, target);
        }
        let destination;
        if (/^(data|blob|javascript):/i.test(href)) destination = href.split(':')[0] + ': [omitted]';
        else {
          try {
            const url = new URL(href, 'https://relative.invalid');
            destination = (url.hostname === 'relative.invalid' ? '' : url.hostname) + url.pathname;
          } catch { destination = href.split(/[?#]/)[0]; }
        }
        el.setAttribute('data-destination', excerpt(destination, 96));
        if (destination !== href) record(el, 'destination-is-descriptive-not-executable');
      }
      if (explicitlyHidden) el.setAttribute('hidden','');
      if (el.localName === 'input' && el.getAttribute('type') === 'password') {
        el.removeAttribute('value'); record(el, 'password-value-redacted');
      }
    }
    stage('attributes');
    // Preserve SVG text and names, but never send drawing/embedded-image payloads.
    for (const el of [...elements(doc)].reverse()) {
      if (el.localName !== 'svg') continue;
      const label = el.getAttribute('aria-label') || normalize(el.querySelector('title,desc')?.textContent ?? '');
      function stripGeometry(parent) {
        for (const child of [...parent.children]) {
          if (child.matches('title,desc,text,tspan,[aria-label],[aria-labelledby]')) continue;
          if (child.querySelector('title,desc,text,tspan,[aria-label],[aria-labelledby]')) stripGeometry(child);
          else { markSubtree(child, 'deferred', el, 'vector-geometry'); child.remove(); }
        }
      }
      stripGeometry(el);
      if (label) el.setAttribute('aria-label', label);
      el.setAttribute('data-deferred','vector'); record(el,'vector-geometry');
    }
    // Collapse generic structure, retaining text containers and semantic attributes.
    for (const el of [...elements(doc)].reverse()) {
      if (!['div','span','font','center'].includes(el.localName)) continue;
      const semAttrs = [...el.attributes].filter(a => !['data-destination'].includes(a.name));
      if (semAttrs.length || originalText.get(el) || el.children.length > 1) continue;
      const parent = el.parentElement;
      recordMap.get(el).disposition = 'collapsed'; recordMap.get(el).representedBy = ids.get(parent) ?? null;
      record(el,'generic-wrapper'); el.replaceWith(...el.childNodes);
    }
    // Attach short refs only once, after flattening eligibility is decided.
    for (const el of elements(doc)) if (!['html','head'].includes(el.localName)) el.setAttribute(marker, ids.get(el));
    for (const node of textNodes(doc.body)) {
      if (node.parentElement?.closest('pre,code,textarea,math')) continue;
      const normalized=node.data.replace(/\s+/g,' ');
      if (node.data!==normalized) { record(node.parentElement,'whitespace-normalized'); node.data=normalized; }
    }
    stage('structure');
    let shortenedTextNodes = 0, omittedTextCharacters = 0;
    const textLimit = profile === 'budget' ? 180 : 360;
    const stateContexts = new Set();
    const expectedStateContext = new Map();
    const fullEvidence = new Set(), skeletons = new Set();
    for (const el of elements(doc)) {
      if (el.matches(HEADINGS + ',' + EXCEPTION + ',label,math,pre,code,textarea,img,figcaption,dt,dd,svg title,svg desc,svg text,svg tspan,svg[aria-label],svg[aria-labelledby]') && !el.matches('select,optgroup')) fullEvidence.add(el);
      if (el.matches(CONTROL) && !el.matches('select')) fullEvidence.add(el);
      if (el.matches('form,fieldset,select,optgroup,ul,ol,dl,table,thead,tbody,tr,th,article') ||
          (['div','span'].includes(el.localName) && el.children.length > 1) ||
          (el.id && relationTargets.has(el.id))) skeletons.add(el);
      if (el.matches('p,li,td') && normalize(el.textContent).length <= 360) fullEvidence.add(el);
      if (el.matches('th')) fullEvidence.add(el);
      if (el.matches(HEADINGS) && el.nextElementSibling?.matches('p')) fullEvidence.add(el.nextElementSibling);
    }
    for (const control of elements(doc).filter(el=>el.matches(CONTROL + ',' + EXCEPTION))) {
      if (control.matches(EXCEPTION) && !control.matches('select,optgroup')) stateContexts.add(control);
      const implicit = control.closest('label');
      if (implicit) stateContexts.add(implicit);
      if (control.id) for (const label of doc.querySelectorAll('label[for]')) {
        if (label.getAttribute('for') === control.id) stateContexts.add(label);
      }
      for (const attr of ['aria-labelledby','aria-describedby','aria-details','aria-errormessage']) {
        for (const id of (control.getAttribute(attr)??'').split(/\s+/).filter(Boolean)) {
          for (const target of doc.querySelectorAll('[id]')) if (target.id===id) stateContexts.add(target);
        }
      }
    }
    // Compare against pre-excerpt evidence, not an already truncated warning.
    for (const el of stateContexts) {
      expectedStateContext.set(el, normalize(el.textContent));
      fullEvidence.add(el);
    }
    const protectedText = new Set([...fullEvidence].flatMap(el => elements(el)));
    const expectedControls = new Set(elements(doc).filter(el => el.matches(CONTROL)));
    const stateAttributes = ['type','value','checked','selected','disabled','required','readonly','multiple','hidden',
      'aria-checked','aria-selected','aria-current','aria-invalid','aria-expanded','aria-disabled','aria-required'];
    const expectedStates = new Map([...expectedControls].map(el => [el,
      stateAttributes.filter(name => el.hasAttribute(name)).map(name => [name, el.getAttribute(name)])]));
    const expectedBoundaries = new Set(skeletons);
    if (profile !== 'structure') {
      for (const el of elements(doc)) {
        if (el.closest('math') || [...stateContexts].some(root => root === el || root.contains(el))) continue;
        const preformatted = Boolean(el.closest('pre,code,textarea'));
        if (protectedText.has(el) && !preformatted && !el.matches(HEADINGS)) continue;
        const limit = el.matches(HEADINGS) ? 512 : el.closest('pre,code,textarea') ? 1200 : textLimit;
        let changed = false;
        for (const node of children(el).filter(n => n.nodeType === 3)) {
          const value = preformatted ? node.data : normalize(node.data);
          if (value.length <= limit) continue;
          const shortened = preformatted ? value.slice(0, limit) + '…' : excerpt(value, limit);
          omittedTextCharacters += value.length - shortened.length + 1;
          node.data = shortened; changed = true; shortenedTextNodes++;
        }
        for (const a of [...el.attributes]) {
          if (!['aria-label','title','alt','placeholder'].includes(a.name) || a.value.length <= textLimit) continue;
          el.setAttribute(a.name, excerpt(a.value, textLimit)); changed = true;
          record(el, 'attribute-excerpt:' + a.name);
        }
        if (changed) { el.setAttribute('data-excerpt','true'); record(el,'text-excerpt'); }
      }
      stage('excerpts');
      // Sample long choice sets, not distinct records, ingredients, or fields.
      for (const parent of [...elements(doc)].reverse()) {
        if (!['select','optgroup','datalist'].includes(parent.localName)) continue;
        const tag = 'option';
        const items = [...parent.children].filter(n => n.localName === tag);
        if (items.length < 7) continue;
        const keep = new Set([items[0],items[1],items.at(-1)]);
        for (const item of items) if (item.matches(EXCEPTION) || item.querySelector(EXCEPTION) || [...stateContexts].some(n=>item===n || item.contains(n))) keep.add(item);
        const omitted = items.filter(n => !keep.has(n));
        for (const item of omitted) { markSubtree(item,'deferred',parent,'list-sampling'); item.remove(); }
        if (omitted.length) {
          parent.setAttribute('data-omitted-items', String(omitted.length));
          parent.setAttribute('data-deferred','items'); record(parent,'list-sampling');
        }
      }
      // Later ancestor folding must not erase the representatives just retained.
      for (const option of doc.querySelectorAll('option')) fullEvidence.add(option);
      stage('lists');
    }
    const targetNodes = Math.max(1, Math.floor(originalElements.length * targetRatio));
    if (profile === 'budget') {
      // Fold complete regions, preserving their native container and headings.
      // The model sees a partial outline and must request expansion for missing detail.
      while (elements(doc).length > targetNodes) {
        const live = elements(doc);
        const candidates = live.filter(el => !['html','head','title','body','h1','h2','h3','h4','h5','h6',
          'legend','caption','summary','input','img','br','hr','option','th','td','tr'].includes(el.localName) &&
          !el.hasAttribute('data-folded') && !protectedText.has(el) && !el.closest(EXCEPTION) && !el.closest('math,pre,code') && el.children.length);
        const ranked = candidates.map(el => {
          const subtree = elements(el);
          const roots = subtree.filter(n => fullEvidence.has(n));
          const protectedNodes = new Set(roots.flatMap(h=>elements(h)));
          for (const node of subtree) if (skeletons.has(node)) protectedNodes.add(node);
          for (const node of [...protectedNodes]) {
            let parent=node.parentElement;
            while (parent && parent!==el) { protectedNodes.add(parent); parent=parent.parentElement; }
          }
          const saving = subtree.length - 1 - protectedNodes.size;
          // Prefer repeated structures before forms or stateful/primary regions.
          const priority = ['ul','ol','tbody','select','nav'].includes(el.localName) ? 1 :
            el.matches('form,dialog,[role="dialog"]') || el.querySelector(EXCEPTION) ? 5 : 2;
          return {el, roots, protectedNodes, saving, score: saving / priority};
        }).filter(x => x.saving > 0).sort((a,b) => b.score-a.score);
        if (!ranked.length) break;
        const {el,roots,protectedNodes} = ranked[0];
        const before = elements(el).length;
        const preview = excerpt(normalize(el.textContent), 140);
        function prune(parent) {
          let changed = false;
          for (const child of [...parent.childNodes]) {
            if (child.nodeType === 1) {
              if (!protectedNodes.has(child)) { markSubtree(child,'deferred',el,'budget-fold'); child.remove(); changed = true; }
              else if (!roots.includes(child)) prune(child);
            } else { if (normalize(child.textContent ?? '')) changed = true; child.remove(); }
          }
          if (changed && parent !== el) { parent.setAttribute('data-deferred','children'); record(parent,'partial-children'); }
        }
        prune(el);
        el.setAttribute('data-folded','true'); el.setAttribute('data-deferred',String(before - elements(el).length));
        if (preview) el.setAttribute('data-preview',preview);
        record(el,'budget-fold');
      }
      stage('budget');
    }
    // Never emit dangling IDREF relationships as if their evidence were present.
    const availableIds = new Set(elements(doc).map(el=>el.getAttribute('id')).filter(Boolean));
    let deferredRelations = 0;
    for (const el of elements(doc)) {
      const missing = [];
      for (const a of [...el.attributes]) if (RELATIONS.has(a.name) && a.value.split(/\s+/).some(id=>id && !availableIds.has(id))) {
        const endpoints = a.value.split(/\s+/).filter(Boolean);
        const remaining = endpoints.filter(id => availableIds.has(id));
        missing.push(a.name);
        if (remaining.length) el.setAttribute(a.name, remaining.join(' ')); else el.removeAttribute(a.name);
        el.setAttribute('data-missing-' + a.name, endpoints.filter(id => !availableIds.has(id)).join(' '));
        record(el,'relationship-needs-expansion:' + a.name); deferredRelations++;
      }
      if (fragmentTargets.has(el)) {
        const matches = elements(doc).filter(target => target.id === fragmentTargets.get(el));
        if (matches.length === 1 && matches[0].hasAttribute(marker)) el.setAttribute('data-target-ref', ids.get(matches[0]));
        else { missing.push('href'); record(el,'relationship-needs-expansion:href'); deferredRelations++; }
      }
      if (missing.length) el.setAttribute('data-relations-deferred',missing.join(' '));
    }
    // Resolve collapsed/deferred owner chains to a currently emitted source ref.
    const live = new Set(elements(doc));
    for (const el of originalElements) {
      const r = recordMap.get(el);
      if (live.has(el)) { r.disposition = 'retained'; r.representedBy = ids.get(el); }
      else if (r.disposition === 'retained') { r.disposition = 'deferred'; record(el,'ancestor-omission'); }
    }
    const byId = new Map([...recordMap.values()].map(r=>[r.id,r]));
    for (const r of byId.values()) {
      const seen = new Set([r.id]);
      let owner = r.representedBy;
      while (owner && byId.get(owner)?.disposition !== 'retained') {
        if (seen.has(owner)) { owner = null; break; }
        seen.add(owner); const parent = byId.get(owner); owner = parent?.representedBy ?? parent?.parent;
      }
      r.representedBy = owner;
      ledger.push(r);
    }
    // Browser normalization can repair invalid captured nesting (e.g. nested links).
    // Accept it only when refs/order, protected inventory and text survive the checks.
    const draftHTML = serialize(doc), reparsed = parse(draftHTML);
    const html = serialize(reparsed), output = elements(reparsed);
    const emitted = output.map(el=>el.getAttribute(marker)).filter(Boolean);
    const expectedRefs = elements(doc).map(el=>el.getAttribute(marker)).filter(Boolean);
    const checks = {
      stableHTML: serialize(parse(html)) === html,
      sourceTextOrderPreserved: normalize(reparsed.body.textContent) === normalize(doc.body.textContent),
      stateContextPreserved: [...expectedStateContext].every(([el,text])=>{
        const out=output.find(n=>n.getAttribute(marker)===ids.get(el));
        return out && normalize(out.textContent)===text;
      }),
      controlInventoryPreserved: [...expectedControls].every(el => output.some(n => n.getAttribute(marker) === ids.get(el))),
      controlStatePreserved: [...expectedStates].every(([el,attributes]) => {
        const node = output.find(n => n.getAttribute(marker) === ids.get(el));
        return node && attributes.every(([name,value]) => node.getAttribute(name) === value);
      }),
      recordBoundariesPreserved: [...expectedBoundaries].every(el => output.some(n => n.getAttribute(marker) === ids.get(el))),
      uniqueReferences: emitted.length === new Set(emitted).size,
      referencesKnown: emitted.every(id=>byId.has(id)),
      emittedReferenceOrder: JSON.stringify(emitted) === JSON.stringify(expectedRefs),
      inventoryComplete: ledger.length === originalElements.length && new Set(ledger.map(r=>r.id)).size === originalElements.length,
      dispositionComplete: ledger.every(r=>['retained','collapsed','deferred','excluded'].includes(r.disposition)),
      noDanglingRelations: output.every(el=>[...el.attributes].filter(a=>RELATIONS.has(a.name)).every(a=>a.value.split(/\s+/).every(id=>!id || availableIds.has(id)))),
      noEmbeddedPayloads: !output.some(el=>[...el.attributes].some(a=>/^(?:data|blob):/i.test(a.value) && a.name!=='data-destination')),
    };
    const omittedElements = ledger.filter(r=>r.disposition==='deferred').length;
    const report = {profile,targetRatio,referenceAttribute:marker,passed:Object.values(checks).every(Boolean),checks,
      preservationPolicy:'semantic-floor/1',serializationNormalized:draftHTML!==html,
      sourceElements:originalElements.length,outputElements:output.length,nodeRatio:output.length/originalElements.length,
      sourceBytes:bytes(source),outputBytes:bytes(html),targetNodes,budgetMet:output.length<=targetNodes,nodeBudgetMet:output.length<=targetNodes,
      omittedElements,shortenedTextNodes,omittedTextCharacters,deferredRelations,
      sourceTextCharacters,exposedTextCharacters:textNodes(reparsed.body).reduce((n,t)=>n+normalize(t.data).length,0),
      previewCharacters:output.reduce((n,el)=>n+(el.getAttribute('data-preview')?.length??0),0),
      collapsedElements:ledger.filter(r=>r.disposition==='collapsed').length,
      excludedElements:ledger.filter(r=>r.disposition==='excluded').length,
      originalControls:originalElements.filter(el=>el.matches(CONTROL)).length,
      exposedControls:output.filter(el=>el.matches(CONTROL)).length,
      deferredGroups:output.filter(el=>el.hasAttribute('data-deferred')).length,
      sourceRoundTripStable,removedAttributeBytes:removedAttributes,stages,
      limitations:['Extractive excerpts are incomplete evidence, not semantic summaries.',
        'Deferred descendants are available only from the local source store; organizer quality not evaluated.',
        'Computed CSS, live properties, and existing capture-ID joins are not inferred from saved HTML.']};
    return {html,sourceMap:ledger,report};
  }
  function expandCompact(source, id) {
    const doc=parse(source), all=elements(doc);
    if (!/^[0-9a-z]+$/.test(id) || parseInt(id,36)>=all.length) throw new Error('Unknown source reference');
    const el=all[parseInt(id,36)];
    return {id,tag:el.localName,html:el.outerHTML};
  }
  globalThis.compactDOM=compactDOM;
  globalThis.expandCompact=expandCompact;
})();
