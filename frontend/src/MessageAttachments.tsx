export type MessageAttachment = {
  type?: string;
  payload?: { url?: string };
  url?: string;
};

export function attachmentUrl(attachment: MessageAttachment): string {
  return String(attachment?.payload?.url || attachment?.url || "");
}

export function attachmentSummary(attachments?: MessageAttachment[]): string {
  const types = (attachments || []).map((item) => String(item.type || "attachment").toLowerCase());
  if (types.includes("video")) return "Video";
  if (types.includes("image")) return "Image";
  return types.length ? "Attachment" : "";
}

export default function MessageAttachments({ attachments, compact = false }: { attachments?: MessageAttachment[]; compact?: boolean }) {
  const visible = (attachments || []).filter(attachmentUrl);
  if (!visible.length) return null;
  return <div style={{ display: "grid", gap: 8, marginTop: compact ? 0 : 8 }}>
    {visible.map((attachment, index) => {
      const url = attachmentUrl(attachment);
      const type = String(attachment.type || "").toLowerCase();
      if (type === "image") return <a key={`${url}:${index}`} href={url} target="_blank" rel="noopener noreferrer"><img src={url} alt="Message attachment" loading="lazy" style={{ display: "block", maxWidth: "100%", width: compact ? 120 : "auto", maxHeight: compact ? 90 : 360, borderRadius: 8, objectFit: "contain" }} /></a>;
      if (type === "video") return <video key={`${url}:${index}`} src={url} controls preload="metadata" style={{ display: "block", maxWidth: "100%", width: compact ? 180 : "auto", maxHeight: compact ? 120 : 420, borderRadius: 8 }} />;
      return <a key={`${url}:${index}`} href={url} target="_blank" rel="noopener noreferrer" style={{ color: "#0b5cab", fontWeight: 700 }}>Open attachment</a>;
    })}
  </div>;
}
