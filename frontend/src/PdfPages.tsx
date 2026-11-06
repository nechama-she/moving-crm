import { useEffect, useRef, useState } from 'react';

// The PDF's empty signature spots are links marked with this text and the spot's number (bill_of_lading_pdf.SIGN_HERE).
const SIGN_HERE = 'sign-here';

type SignArea = { spot: number; page: number; left: number; top: number; width: number; height: number };

/** The PDF's pages, drawn to fit the width. With onSign, each signature spot opens its signing when clicked;
 * with toNextSpot, the first spot left to sign is scrolled into view. */
export default function PdfPages({ url, title, onSign, toNextSpot = false }: {
  url: string; title: string; onSign?: (spot: number) => void; toNextSpot?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const firstSpot = useRef<HTMLButtonElement | null>(null);
  const [pages, setPages] = useState<HTMLCanvasElement[]>([]);
  const [signAreas, setSignAreas] = useState<SignArea[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    let task: { destroy: () => Promise<void> } | null = null;
    setPages([]); setSignAreas([]); setError('');
    (async () => {
      // Loaded with the viewer only, so the rest of the page does not carry it.
      const pdfjs = await import('pdfjs-dist');
      const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url');
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
      const loading = pdfjs.getDocument(url);
      task = loading;
      const pdf = await loading.promise;
      const width = container.current?.clientWidth || 800;
      const drawn: HTMLCanvasElement[] = [];
      const areas: SignArea[] = [];
      for (let number = 1; number <= pdf.numPages; number += 1) {
        const page = await pdf.getPage(number);
        const viewport = page.getViewport({ scale: width / page.getViewport({ scale: 1 }).width });
        const ratio = window.devicePixelRatio || 1;
        const canvas = document.createElement('canvas');
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        await page.render({ canvasContext: canvas.getContext('2d')!, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] }).promise;
        if (cancelled) return;
        drawn.push(canvas);
        for (const link of (await page.getAnnotations()).filter(annotation => annotation.subtype === 'Link' && annotation.contentsObj?.str?.startsWith(SIGN_HERE + ' '))) {
          const [x1, y1, x2, y2] = viewport.convertToViewportRectangle(link.rect);
          // As shares of the page, so the spot stays on the line when the page is shown narrower or wider.
          areas.push({ spot: Number(link.contentsObj.str.slice(SIGN_HERE.length + 1)), page: number - 1, left: Math.min(x1, x2) / viewport.width, top: Math.min(y1, y2) / viewport.height,
            width: Math.abs(x2 - x1) / viewport.width, height: Math.abs(y2 - y1) / viewport.height });
        }
        setPages([...drawn]);
      }
      if (!cancelled) setSignAreas(areas);
    })().catch(reason => { if (!cancelled) setError((reason as Error).message || 'Could not show the PDF.'); });
    return () => { cancelled = true; void task?.destroy(); };
  }, [url]);
  useEffect(() => {
    if (!toNextSpot || !firstSpot.current) return;
    firstSpot.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    firstSpot.current.focus({ preventScroll: true });
  }, [signAreas, toNextSpot]);

  return <div ref={container} className="pdf-pages" role="document" aria-label={title}>
    {error && <p role="alert">Could not show the PDF. Use Download PDF to open it. ({error})</p>}
    {!error && !pages.length && <p role="status">Loading PDF...</p>}
    {pages.map((canvas, index) => <div key={index} className="pdf-page">
      <div ref={holder => { if (holder && holder.firstChild !== canvas) holder.replaceChildren(canvas); }} />
      {onSign && signAreas.filter(area => area.page === index).map(area => <button key={area.spot} type="button" className="pdf-sign-here"
        ref={area === signAreas[0] ? firstSpot : undefined} onClick={() => onSign(area.spot)}
        style={{ left: `${area.left * 100}%`, top: `${area.top * 100}%`, width: `${area.width * 100}%`, height: `${area.height * 100}%` }}>
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M4 12h13M12 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
        Sign here
      </button>)}
    </div>)}
  </div>;
}
