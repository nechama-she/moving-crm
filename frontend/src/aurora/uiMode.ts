// Which look the CRM uses: the new "Aurora" design (the default) or the classic one.
// A person who switches back to classic keeps that choice in this browser.
export type UiMode = "aurora" | "classic";
const KEY = "crm-ui";

declare global {
  interface Window {
    // Optional override in api-config.js: "classic" makes a deployment open in the classic look.
    __UI_DEFAULT__?: string;
  }
}

export function getUiMode(): UiMode {
  try {
    // A link with ?look=new or ?look=classic picks the look explicitly (and remembers it).
    const requested = new URLSearchParams(window.location.search).get("look");
    if (requested === "new" || requested === "classic") localStorage.setItem(KEY, requested === "new" ? "aurora" : "classic");
    const saved = localStorage.getItem(KEY);
    if (saved === "aurora" || saved === "classic") return saved;
  } catch { /* storage unavailable: fall back to the default */ }
  return window.__UI_DEFAULT__ === "classic" ? "classic" : "aurora";
}

export function setUiMode(mode: UiMode) {
  try { localStorage.setItem(KEY, mode); } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent(KEY, { detail: mode }));
}

export function onUiModeChange(listener: (mode: UiMode) => void) {
  const handler = (event: Event) => listener((event as CustomEvent<UiMode>).detail);
  window.addEventListener(KEY, handler);
  return () => window.removeEventListener(KEY, handler);
}
