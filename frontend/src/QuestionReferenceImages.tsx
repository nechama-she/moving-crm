import { useEffect, useRef, useState } from "react";
type Image = { url: string; room: string; name: string; expires_at: number };
export default function QuestionReferenceImages({ name, room, endpoint, linkKey, session, active = true }: { active?: boolean; name: string; room?: string; endpoint: string; linkKey: string; session: string }) {
  const [images, setImages] = useState<Image[]>([]);
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [tabVisible, setTabVisible] = useState(document.visibilityState === 'visible');
  const cache = useRef<{ key: string; rows: Image[] }>();
  useEffect(() => {
    const changed = () => setTabVisible(document.visibilityState === 'visible');
    document.addEventListener('visibilitychange', changed);
    return () => document.removeEventListener('visibilitychange', changed);
  }, []);
  useEffect(() => {
    if (!active || !tabVisible) return;
    const cacheKey = JSON.stringify([name, room, endpoint, linkKey, session]);
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const cleanup = () => { controller.abort(); if (timer) clearTimeout(timer); };
    const display = (rows: Image[]) => {
      setImages(rows); setNotice('');
      const expires = Math.min(...rows.map(row => row.expires_at * 1000));
      // Never loop on already-expired URLs returned by the provider.
      if (rows.length && expires > Date.now()) timer = setTimeout(() => {
        if (document.visibilityState === 'visible') setRefresh(value => value + 1);
      }, expires - Date.now());
    };
    const cached = cache.current;
    if (cached?.key === cacheKey && cached.rows.every(row => row.expires_at * 1000 > Date.now())) {
      display(cached.rows);
      return cleanup;
    }
    setImages([]); setNotice('');
    fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json", "x-public-link": linkKey, "x-public-session": session }, body: JSON.stringify({ names: [name] }), signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(body => {
        if (controller.signal.aborted) return;
        const rows: Image[] = body.images?.[name] || [];
        const visibleRows = room ? rows.filter(row => row.room.toLowerCase() === room.toLowerCase()) : rows;
        cache.current = { key: cacheKey, rows: visibleRows };
        display(visibleRows);
      }).catch(() => { if (!controller.signal.aborted) setNotice("Reference photos are unavailable. You can still answer this question."); });
    return cleanup;
  }, [name, room, endpoint, linkKey, session, refresh, active, tabVisible]);
  return <>{images.length > 0 && <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "8px 0 16px" }}>{images.map(image => <a key={image.room + image.url} href={image.url} target="_blank" rel="noopener noreferrer" style={{ maxWidth: "100%" }}><img src={image.url} alt={`${image.name}${image.room ? ` in ${image.room}` : ''}`} loading="lazy" style={{ width: 104, height: 80, objectFit: "cover", borderRadius: 8 }} /><small style={{ display: "block" }}>{image.room}</small></a>)}</div>}{notice && <small role="status">{notice}</small>}</>;
}
