import { requestReferenceImages } from "./referenceImageRequests";
import { useEffect, useRef, useState } from "react";
type Image = { url: string; room: string; name: string; expires_at: number };
export default function QuestionReferenceImages({ name, room, endpoint, linkKey, session, active = true, compact = false }: { active?: boolean; compact?: boolean; name: string; room?: string; endpoint: string; linkKey: string; session: string }) {
  const [images, setImages] = useState<Image[]>([]);
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
      setImages(rows);
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
    setImages([]);
    requestReferenceImages(endpoint, linkKey, session, name)
      .then(rows => {
        if (controller.signal.aborted) return;
        const visibleRows = room ? rows.filter(row => row.room.toLowerCase() === room.toLowerCase()) : rows;
        cache.current = { key: cacheKey, rows: visibleRows };
        display(visibleRows);
      }).catch(() => { if (!controller.signal.aborted) setImages([]); });
    return cleanup;
  }, [name, room, endpoint, linkKey, session, refresh, active, tabVisible]);
  return <>{images.length > 0 && <div className={`cm-reference-images${compact ? ' cm-reference-images-compact' : ''}`}>{images.map(image => <a key={image.room + image.url} href={image.url} target="_blank" rel="noopener noreferrer"><img src={image.url} alt={`${image.name}${image.room ? ` in ${image.room}` : ''}`} loading="lazy" onError={() => setImages(current => current.filter(row => row.url !== image.url))} /><small>{image.room}</small></a>)}</div>}</>;
}
