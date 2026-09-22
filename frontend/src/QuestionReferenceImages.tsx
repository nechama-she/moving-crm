import { useEffect, useState } from "react";
type Image = { url: string; room: string; name: string; expires_at: number };
export default function QuestionReferenceImages({ name, room, endpoint, linkKey, session }: { name: string; room?: string; endpoint: string; linkKey: string; session: string }) {
  const [images, setImages] = useState<Image[]>([]);
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setImages([]); setNotice("");
    fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json", "x-public-link": linkKey, "x-public-session": session }, body: JSON.stringify({ names: [name] }), signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(body => {
        if (controller.signal.aborted) return;
        const rows: Image[] = body.images?.[name] || [];
        setImages(room ? rows.filter(row => row.room.toLowerCase() === room.toLowerCase()) : rows);
        if (rows.length) timer = setTimeout(() => setRefresh(value => value + 1), Math.max(1000, Math.min(...rows.map(row => row.expires_at * 1000)) - Date.now()));
      }).catch(() => { if (!controller.signal.aborted) setNotice("Reference photos are unavailable. You can still answer this question."); });
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [name, room, endpoint, linkKey, session, refresh]);
  return <>{images.length > 0 && <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "8px 0 16px" }}>{images.map(image => <a key={image.room + image.url} href={image.url} target="_blank" rel="noopener noreferrer" style={{ maxWidth: "100%" }}><img src={image.url} alt={`${image.name}${image.room ? ` in ${image.room}` : ''}`} loading="lazy" style={{ width: 104, height: 80, objectFit: "cover", borderRadius: 8 }} /><small style={{ display: "block" }}>{image.room}</small></a>)}</div>}{notice && <small role="status">{notice}</small>}</>;
}
