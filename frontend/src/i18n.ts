import copy from "../../src/hmanga/locales/zh-CN.json";

const messages = copy as Record<string, string>;

export function t(key: string): string {
  return messages[key] ?? key;
}

export function tf(key: string, values: Record<string, string | number>): string {
  return t(key).replace(/\{([A-Za-z0-9_]+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match,
  );
}

function translateTextNode(node: Text): void {
  const source = node.nodeValue ?? "";
  const trimmed = source.trim();
  if (!trimmed) return;
  const translated = t(trimmed);
  if (translated === trimmed) return;
  const start = source.slice(0, source.indexOf(trimmed));
  const end = source.slice(source.indexOf(trimmed) + trimmed.length);
  node.nodeValue = `${start}${translated}${end}`;
}

function translateElement(element: Element): void {
  for (const attribute of ["placeholder", "title", "aria-label"]) {
    const source = element.getAttribute(attribute);
    if (source) element.setAttribute(attribute, t(source));
  }
  for (const child of element.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) translateTextNode(child as Text);
  }
}

export function installLocalization(root: HTMLElement): MutationObserver {
  const translateTree = (node: Node): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      translateTextNode(node as Text);
      return;
    }
    if (!(node instanceof Element)) return;
    translateElement(node);
    for (const element of node.querySelectorAll("*")) translateElement(element);
  };
  translateTree(root);
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === "characterData") translateTree(record.target);
      for (const node of record.addedNodes) translateTree(node);
    }
  });
  observer.observe(root, { childList: true, subtree: true, characterData: true });
  return observer;
}
