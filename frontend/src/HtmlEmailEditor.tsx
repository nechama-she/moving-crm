import { useEffect, useRef, useState } from "react";

// The placeholders an automated email can use; inserted as text, filled when it is sent.
type Props = { value: string; onChange: (html: string) => void; disabled: boolean; placeholders: string[] };

/** An email's HTML: shown as it looks and edited in place (Design), or as its HTML (HTML). The design view is a
 * sandboxed frame without scripts, so pasted HTML never runs in the CRM. A full HTML document (with its <head>
 * styles) is kept whole; a fragment stays a fragment. */
export default function HtmlEmailEditor({ value, onChange, disabled, placeholders }: Props) {
  const [mode, setMode] = useState<"design" | "html">("design");
  const frame = useRef<HTMLIFrameElement>(null);
  // The HTML the frame was loaded with: the frame is loaded again only for a change that did not come from it.
  const loaded = useRef<string | null>(null);
  const [source, setSource] = useState(value);
  useEffect(() => {
    if (value !== loaded.current) setSource(value);
  }, [value]);

  const doc = () => frame.current?.contentDocument || null;
  const serialize = (page: Document) => /<html[\s>]/i.test(value)
    ? `<!DOCTYPE html>\n${page.documentElement.outerHTML}`
    : page.body.innerHTML;
  const changed = () => {
    const page = doc();
    if (!page) return;
    const html = serialize(page);
    loaded.current = html;
    onChange(html);
  };
  const command = (name: string, argument?: string) => {
    const page = doc();
    if (!page || disabled) return;
    page.execCommand(name, false, argument);
    changed();
  };

  return <div style={{ marginTop: 10 }}>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginBottom: 6 }}>
      {(["design", "html"] as const).map(view => <button key={view} type="button" className="slds-button" aria-pressed={mode === view}
        onClick={() => { if (view === "design") loaded.current = null; setMode(view); }}
        style={{ ...tool, ...(mode === view ? { background: "#0176d3", color: "#fff" } : {}) }}>{view === "design" ? "Design" : "HTML"}</button>)}
      {mode === "design" && !disabled && <>
        <span style={{ width: 1, height: 22, background: "#dddbda", margin: "0 4px" }} />
        {([["Bold", "bold"], ["Italic", "italic"], ["Underline", "underline"], ["Bullets", "insertUnorderedList"], ["Numbered list", "insertOrderedList"],
          ["Align left", "justifyLeft"], ["Center", "justifyCenter"]] as const).map(([label, name]) =>
          <button key={name} type="button" className="slds-button" style={tool} onMouseDown={e => e.preventDefault()} onClick={() => command(name)}>{label}</button>)}
        <button type="button" className="slds-button" style={tool} onMouseDown={e => e.preventDefault()} onClick={() => {
          const url = window.prompt("Link address (https://, mailto: or tel:)");
          if (url && /^(https?:\/\/|mailto:|tel:)/i.test(url.trim())) command("createLink", url.trim());
        }}>Link</button>
        <select aria-label="Insert a placeholder" value="" style={{ ...tool, padding: "4px 6px" }}
          onChange={e => { if (e.target.value) command("insertText", e.target.value); }}>
          <option value="">Insert placeholder…</option>
          {placeholders.map(name => <option key={name} value={name}>{name}</option>)}
        </select>
      </>}
    </div>
    {mode === "html"
      ? <textarea value={value} disabled={disabled} rows={16} onChange={e => onChange(e.target.value)} style={code} aria-label="Email HTML" />
      : <iframe ref={frame} title="Email design" sandbox="allow-same-origin" srcDoc={source}
          onLoad={() => {
            const page = doc();
            if (!page) return;
            page.designMode = disabled ? "off" : "on";
            page.addEventListener("input", changed);
          }}
          style={{ width: "100%", height: 520, border: "1px solid #c9c7c5", borderRadius: 4, background: "#fff" }} />}
  </div>;
}

const tool: React.CSSProperties = { background: "#fff", color: "#0176d3", border: "1px solid #c9c7c5", borderRadius: 4, padding: "4px 10px", fontSize: 12, cursor: "pointer" };
const code: React.CSSProperties = { width: "100%", boxSizing: "border-box", fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", fontSize: 12, padding: 10, border: "1px solid #c9c7c5", borderRadius: 4 };
