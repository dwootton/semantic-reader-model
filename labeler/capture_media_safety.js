/* Copied unchanged from the corpus collector (bucket snapshots/2026-09-14/vm-code, collection/media_safety.js, sha256 3140dff0529977d3773293d2516ea256c079c3b56ac9959b42e640c13b1356a9).
   The capture ran this before every page loaded, so its geometry describes the page as this script leaves it.
   labeler/render_pages.py runs it too, so a fresh screenshot lines up with the captured geometry. */
/* Pre-navigation suppression. Network blocking and final image review remain mandatory. */
(() => {
  'use strict';
  if (Object.prototype.hasOwnProperty.call(window, '__semanticMediaSafety')) return;
  const MEDIA = new Set(['IMG', 'SVG', 'CANVAS', 'VIDEO', 'AUDIO', 'IFRAME', 'FRAME', 'OBJECT', 'EMBED', 'PICTURE']);
  const DROP = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'BASE', 'NOSCRIPT', 'TEMPLATE']);
  const ATTRS = new Set(['id', 'role', 'alt', 'title', 'for', 'headers', 'scope', 'tabindex', 'lang', 'dir',
    'type', 'name', 'disabled', 'checked', 'selected', 'multiple', 'required', 'readonly', 'open',
    'hidden', 'inert', 'colspan', 'rowspan', 'autocomplete']);
  const SAFE_ARIA = /^aria-(?:label|labelledby|description|describedby|details|role-description|roledescription|controls|owns|flowto|activedescendant|atomic|autocomplete|busy|checked|colcount|colindex|colspan|current|disabled|expanded|haspopup|hidden|invalid|keyshortcuts|level|live|modal|multiline|multiselectable|orientation|placeholder|posinset|pressed|readonly|relevant|required|rowcount|rowindex|rowspan|selected|setsize|sort|valuemax|valuemin|valuenow|valuetext)$/;
  const overrides = {'background-image': 'none', 'border-image-source': 'none', 'list-style-image': 'none',
    'mask-image': 'none', '-webkit-mask-image': 'none', 'filter': 'none', 'backdrop-filter': 'none',
    'box-shadow': 'none', 'text-shadow': 'none', 'font-family': 'Arial, sans-serif', 'animation': 'none',
    'transition': 'none', 'cursor': 'auto'};
  const css = `*,*::before,*::after,*::marker{background-image:none!important;border-image-source:none!important;list-style-image:none!important;mask-image:none!important;-webkit-mask-image:none!important;filter:none!important;box-shadow:none!important;text-shadow:none!important;font-family:Arial,sans-serif!important;animation:none!important;transition:none!important}*::before,*::after,*::marker{content:none!important}`;
  const ids = new WeakMap();
  const normalizedStyles = new WeakMap();
  let serial = 0, revision = 0, styleNode = null, overflow = false;
  const maximumNodes = 20000;
  const idFor = node => { if (!ids.has(node)) ids.set(node, `sr-${++serial}`); return ids.get(node); };
  const generated = el => el.hasAttribute('data-sr-placeholder') || el === styleNode;
  const setStyle = (el, key, value) => {
    if (!normalizedStyles.has(el)) normalizedStyles.set(el, new Map());
    const values = normalizedStyles.get(el);
    if (el.style.getPropertyValue(key) !== values.get(key) || el.style.getPropertyPriority(key) !== 'important') {
      el.style.setProperty(key, value, 'important');
      values.set(key, el.style.getPropertyValue(key));
    }
  };
  function suppress() {
    if (!document.documentElement) return;
    if (!styleNode || !styleNode.isConnected) {
      styleNode = document.createElement('style');
      styleNode.textContent = css;
      document.documentElement.appendChild(styleNode);
    }
    const all = document.querySelectorAll('*');
    if (all.length > maximumNodes) { overflow = true; return; }
    for (const el of all) {
      if (generated(el)) continue;
      for (const [key, value] of Object.entries(overrides)) setStyle(el, key, value);
      if (MEDIA.has(el.tagName.toUpperCase())) {
        setStyle(el, 'opacity', '0');
        // Opacity preserves layout and AX exposure; no alt or role is invented.
        for (const key of ['src', 'srcset', 'poster', 'data', 'background']) el.removeAttribute(key);
        if (['VIDEO', 'AUDIO'].includes(el.tagName)) { try { el.pause(); } catch (_) {} }
      }
    }
  }
  const observer = new MutationObserver(records => {
    if (records.length) revision++;
    suppress();
  });
  observer.observe(document, {childList: true, subtree: true, attributes: true, characterData: true});
  suppress();
  function rect(el) {
    const r = el.getBoundingClientRect();
    return {x: r.x, y: r.y, width: r.width, height: r.height};
  }
  function prepare() {
    suppress();
    document.querySelectorAll('[data-sr-placeholder]').forEach(el => el.remove());
    const reasons = new Set();
    if (overflow) reasons.add('dom_node_limit');
    const all = document.querySelectorAll('*');
    for (const el of all) {
      if (generated(el)) continue;
      if (el.shadowRoot) reasons.add('shadow_dom_not_exported');
      const style = getComputedStyle(el);
      for (const key of ['background-image', 'border-image-source', 'list-style-image', 'mask-image', '-webkit-mask-image']) {
        const value = style.getPropertyValue(key);
        if (value && value !== 'none') reasons.add('css_media_remaining');
      }
      for (const pseudo of ['::before', '::after', '::marker']) {
        const ps = getComputedStyle(el, pseudo);
        if (!['none', 'normal', ''].includes(ps.content)) reasons.add('pseudo_content_remaining');
        if (ps.backgroundImage && ps.backgroundImage !== 'none') reasons.add('pseudo_media_remaining');
      }
      if (style.fontFamily.replace(/\s/g, '').toLowerCase() !== 'arial,sans-serif') reasons.add('source_font_remaining');
      if (MEDIA.has(el.tagName.toUpperCase())) {
        if (Number(style.opacity) !== 0) reasons.add('media_surface_visible');
        const box = rect(el);
        if (box.width > 0 && box.height > 0) {
          const placeholder = document.createElement('div');
          placeholder.setAttribute('data-sr-placeholder', '');
          placeholder.setAttribute('aria-hidden', 'true');
          placeholder.style.cssText = `position:fixed!important;left:${box.x}px!important;top:${box.y}px!important;width:${box.width}px!important;height:${box.height}px!important;background:#e5e5e5!important;border:1px solid #b8b8b8!important;box-sizing:border-box!important;pointer-events:none!important;z-index:2147483647!important;`;
          document.documentElement.appendChild(placeholder);
        }
      }
    }
    return {verified: reasons.size === 0, reason_codes: [...reasons], revision,
      verification_scope: 'computed_style_and_surface_checks_only', final_pixels_verified: false,
      transformations: ['all_source_media_suppressed', 'neutral_media_overlays', 'system_fonts_only',
        'pseudo_content_suppressed', 'media_source_attributes_removed', 'intrinsic_media_layout_may_change',
        'animations_disabled', 'shadows_and_filters_removed'],
      screenshot_policy: 'omit_without_independent_final_pixel_verification'};
  }
  function exportDOM() {
    suppress();
    const nodes = [], reasons = new Set();
    let textCharacters = 0;
    if (overflow) reasons.add('dom_node_limit');
    const container = document.createElement('div');
    function visit(node, parentID, destination, depth = 0) {
      if (depth > 100 || nodes.length >= maximumNodes) { reasons.add('dom_complexity_limit'); return; }
      if (node.nodeType === Node.TEXT_NODE) {
        const value = node.nodeValue || '';
        textCharacters += value.length;
        if (textCharacters > 2000000) { reasons.add('dom_text_limit'); return; }
        if (!value.trim()) return;
        const range = document.createRange();
        range.selectNodeContents(node);
        nodes.push({id: idFor(node), parent_id: parentID, node_type: 'text', text: value,
          geometry: Array.from(range.getClientRects(), r => ({x:r.x,y:r.y,width:r.width,height:r.height}))});
        destination.appendChild(document.createTextNode(value));
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE || generated(node) || DROP.has(node.tagName)) return;
      if (node.shadowRoot) reasons.add('shadow_dom_not_exported');
      const originalTag = node.tagName.toLowerCase();
      const media = MEDIA.has(node.tagName.toUpperCase());
      // Unknown/custom tags become inert spans; media payload children never export.
      const safeTag = /^[a-z][a-z0-9]*$/.test(originalTag) && !media ? originalTag : 'span';
      const clone = document.createElement(safeTag);
      const attributes = {};
      for (const attr of node.attributes) {
        if (ATTRS.has(attr.name) || SAFE_ARIA.test(attr.name)) {
          attributes[attr.name] = attr.value;
          clone.setAttribute(attr.name, attr.value);
        }
      }
      // No href/src/style/event/data/value attributes or application state.
      const identity = idFor(node);
      clone.setAttribute('data-sr-node', identity);
      destination.appendChild(clone);
      const computed = getComputedStyle(node);
      const row = {id: identity, parent_id: parentID, node_type: 'element', tag: originalTag,
        attributes, geometry: rect(node), media_suppressed: media,
        styles: {display: computed.display, visibility: computed.visibility, opacity: computed.opacity,
          font_size: computed.fontSize, font_weight: computed.fontWeight, text_align: computed.textAlign,
          color: computed.color, background_color: computed.backgroundColor, position: computed.position},
        state: {focused: document.activeElement === node, checked: typeof node.checked === 'boolean' ? node.checked : null,
          selected: typeof node.selected === 'boolean' ? node.selected : null, open: typeof node.open === 'boolean' ? node.open : null}};
      if (node.tagName === 'IMG') row.alt_state = !node.hasAttribute('alt') ? 'missing' : node.getAttribute('alt') === '' ? 'empty' : 'nonempty';
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName)) row.value_omitted = true;
      nodes.push(row);
      if (!media && !['TEXTAREA'].includes(node.tagName)) {
        for (const child of node.childNodes) visit(child, identity, clone, depth + 1);
      }
    }
    if (document.documentElement) visit(document.documentElement, null, container);
    return {allowed: reasons.size === 0, reason_codes: [...reasons], html: reasons.size ? null : container.innerHTML,
      nodes: reasons.size ? [] : nodes, revision, media_suppressed: true,
      focus_id: document.activeElement ? ids.get(document.activeElement) || null : null,
      scroll: {x: scrollX, y: scrollY}, transformations: ['inert_attribute_whitelist', 'media_payloads_and_urls_omitted',
        'form_values_omitted', 'scripts_styles_omitted', 'media_elements_exported_as_inert_spans'],
      limitations: ['heuristic_content_screen_required', 'frames_omitted', 'closed_shadow_roots_not_observable',
        'geometry_after_media_and_font_suppression', 'not_an_untouched_rendering']};
  }
  Object.defineProperty(window, '__semanticMediaSafety', {value: Object.freeze({prepare, export: exportDOM}),
    writable: false, configurable: false});
})();
