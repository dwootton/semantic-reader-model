// Runs inside the live page (labeler/snapshot_pages.py). Matches live elements to the captured document,
// stamps them with the capture's src-<base36> ids, marks what is clickable, makes the page static and
// returns its HTML for the Python side to inline stylesheets, images and fonts into.
//
// Matching is by content, not position (the capture was measured with media removed and Arial forced, so
// a styled page lays out differently even when nothing changed):
//   1. <html>, <head>, <body> pair up; then elements whose tag + own text (or tag + id) is unique on both pages.
//   2. Repeat until nothing changes: a matched pair's unmatched parents pair up when their tags agree, and a
//      matched pair's unmatched children pair up in order (same tag + own text first, then same tag when
//      both sides have the same tag sequence).
(capturedHtml) => {
  const height = Math.ceil(Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0));
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const INERT = new Set(['script', 'style', 'noscript', 'template', 'link', 'meta', 'base', 'title']);
  const ownText = el => norm([...el.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join(' ')).slice(0, 120);
  const usable = el => !INERT.has(el.localName);

  const captured = new DOMParser().parseFromString(capturedHtml, 'text/html');
  const cAll = [...captured.querySelectorAll('*')];
  const cId = new Map(cAll.map((el, i) => [el, `src-${i.toString(36)}`]));
  const lAll = [...document.querySelectorAll('*')].filter(usable);
  const c2l = new Map(), l2c = new Map();
  const pair = (c, l) => { if (c && l && !c2l.has(c) && !l2c.has(l) && c.localName === l.localName) { c2l.set(c, l); l2c.set(l, c); return true; } return false; };

  pair(captured.documentElement, document.documentElement);
  pair(captured.head, document.head);
  pair(captured.body, document.body);
  const keyed = (els, key) => {
    const seen = new Map();
    for (const el of els) { const k = key(el); if (k) seen.set(k, seen.has(k) ? null : el); }
    return seen;
  };
  for (const key of [el => ownText(el).length >= 2 && `${el.localName}|${ownText(el)}`,
    el => el.id && `${el.localName}#${el.id}`]) {
    const live = keyed(lAll, key);
    for (const [k, c] of keyed(cAll.filter(usable), key)) if (c && live.get(k)) pair(c, live.get(k));
  }
  for (let changed = true; changed;) {
    changed = false;
    for (const [c, l] of [...c2l]) {
      if (pair(c.parentElement, l.parentElement)) changed = true;
      const cc = [...c.children].filter(e => usable(e) && !c2l.has(e)), lc = [...l.children].filter(e => usable(e) && !l2c.has(e));
      if (!cc.length || !lc.length) continue;
      let j = 0;
      for (const e of cc) {
        const k = lc.findIndex((x, i) => i >= j && x.localName === e.localName && ownText(x) === ownText(e));
        if (k >= 0 && pair(e, lc[k])) { j = k + 1; changed = true; }
      }
      const cr = cc.filter(e => !c2l.has(e)), lr = lc.filter(e => !l2c.has(e));
      if (cr.length && cr.length === lr.length && cr.every((e, i) => e.localName === lr[i].localName)) {
        cr.forEach((e, i) => pair(e, lr[i]));
        changed = true;
      }
    }
  }
  for (const [c, l] of c2l) l.setAttribute('data-sr-id', cId.get(c));

  // Clickable: links, controls, interactive roles, focusable elements, click listeners (recorded by the init
  // script) and elements that turn the pointer into a hand where their parent does not.
  const ROLES = new Set(['button', 'link', 'tab', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'checkbox',
    'radio', 'switch', 'combobox', 'treeitem', 'slider', 'spinbutton', 'textbox', 'searchbox']);
  let clickable = 0;
  for (const el of lAll) {
    const tag = el.localName, tab = el.getAttribute('tabindex');
    const pointer = getComputedStyle(el).cursor === 'pointer' && (!el.parentElement || getComputedStyle(el.parentElement).cursor !== 'pointer');
    if ((tag === 'a' && el.hasAttribute('href')) || ['button', 'select', 'textarea', 'summary'].includes(tag)
      || (tag === 'input' && el.type !== 'hidden') || ROLES.has(el.getAttribute('role')) || (tab !== null && Number(tab) >= 0)
      || el.hasAttribute('onclick') || el.__srClick || pointer) {
      el.setAttribute('data-sr-click', '');
      clickable++;
    }
  }

  // Static copy: keep form state, absolute media URLs (the Python side swaps in the bytes), CSSOM text for
  // inline styles (CSS-in-JS rules live only there), no scripts, handlers, frames or lazy loading.
  for (const el of document.querySelectorAll('input')) {
    if (el.type === 'checkbox' || el.type === 'radio') el.toggleAttribute('checked', el.checked);
    else if (el.type !== 'password' && el.type !== 'file') el.setAttribute('value', el.value);
  }
  for (const el of document.querySelectorAll('textarea')) el.textContent = el.value;
  for (const el of document.querySelectorAll('option')) el.toggleAttribute('selected', el.selected);
  for (const el of document.querySelectorAll('img')) {
    if (el.currentSrc) el.setAttribute('src', el.currentSrc);
    el.removeAttribute('srcset'); el.removeAttribute('sizes'); el.removeAttribute('loading');
  }
  for (const el of document.querySelectorAll('[poster]')) el.setAttribute('poster', el.poster);
  for (const el of document.querySelectorAll('canvas')) {
    try { const img = document.createElement('img'); img.src = el.toDataURL(); img.width = el.width; img.height = el.height;
      for (const a of el.attributes) img.setAttribute(a.name, a.value); el.replaceWith(img); } catch { /* tainted canvas */ }
  }
  for (const el of document.querySelectorAll('style')) {
    try { el.textContent = [...el.sheet.cssRules].map(r => r.cssText).join('\n'); } catch { /* keep the text */ }
  }
  // Adopted stylesheets (constructable CSS) are not in the HTML at all.
  const adopted = [...(document.adoptedStyleSheets || [])].map(s => [...s.cssRules].map(r => r.cssText).join('\n')).join('\n');
  if (adopted) document.head.append(Object.assign(document.createElement('style'), { textContent: adopted }));
  for (const el of document.querySelectorAll('link')) {
    const rel = (el.rel || '').toLowerCase();
    if (rel.split(/\s+/).includes('stylesheet') && !el.disabled) {
      const style = document.createElement('style');
      style.setAttribute('data-sr-href', el.href);
      if (el.media) style.setAttribute('media', el.media);
      el.replaceWith(style);
    } else el.remove();
  }
  for (const el of document.querySelectorAll('iframe, frame, object, embed')) {
    const r = el.getBoundingClientRect();
    const box = document.createElement('div');
    box.setAttribute('style', `display:inline-block;width:${r.width}px;height:${r.height}px;background:#e5e7eb`);
    for (const a of ['data-sr-id', 'data-sr-click', 'class', 'id']) if (el.hasAttribute(a)) box.setAttribute(a, el.getAttribute(a));
    el.replaceWith(box);
  }
  for (const el of document.querySelectorAll('script, noscript, base, meta[http-equiv], source, track, audio')) el.remove();
  for (const el of document.querySelectorAll('*')) {
    for (const a of [...el.attributes]) if (a.name.startsWith('on')) el.removeAttribute(a.name);
  }
  return {
    html: '<!doctype html>\n' + document.documentElement.outerHTML,
    height,
    stamped: c2l.size, clickable,
    ids: [...c2l.keys()].map(c => cId.get(c)),
  };
}
