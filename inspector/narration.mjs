export function describeNode(item, side) {
  const n = item.node, a = n.attributes || {};
  const text = side === 'semantic' ? n.label
    : a['aria-label'] || a.alt || n.ownText || (n.children.length ? '' : n.text) || a.placeholder || a.id || n.id;
  const role = side === 'semantic' ? (n.kind === 'group' ? 'group' : 'reference') : a.role || n.tag;
  return [text, role, `level ${item.depth + 1}`, n.hidden ? 'hidden' : '',
    item.hasChildren ? (item.open ? 'expanded' : 'collapsed') : ''].filter(Boolean).join('. ');
}

export function createNarrator(synthesis, Utterance) {
  const supported = Boolean(synthesis && Utterance);
  let enabled = false;
  return {
    supported,
    setEnabled(value) { enabled = supported && value; if (!enabled) this.stop(); },
    stop() { if (supported) synthesis.cancel(); },
    speak(text) {
      if (!enabled || !text) return;
      synthesis.cancel();
      const utterance = new Utterance(text);
      utterance.lang = 'en-US';
      synthesis.speak(utterance);
    },
  };
}
