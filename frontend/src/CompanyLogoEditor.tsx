import { useEffect, useRef, useState } from 'react';

export default function CompanyLogoEditor({ value, name, color, disabled, onChange }: {
  value: string; name: string; color: string; disabled: boolean; onChange: (value: string) => void;
}) {
  const [source, setSource] = useState<HTMLImageElement>();
  const [zoom, setZoom] = useState(1);
  const [x, setX] = useState(50);
  const [y, setY] = useState(50);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const change = useRef(onChange);
  change.current = onChange;
  useEffect(() => {
    if (!source) return;
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256;
    const context = canvas.getContext('2d');
    if (!context) { setError('Image preview is unavailable in this browser.'); return; }
    const scale = Math.max(256 / source.naturalWidth, 256 / source.naturalHeight) * zoom;
    const width = source.naturalWidth * scale, height = source.naturalHeight * scale;
    context.drawImage(source, (256 - width) * x / 100, (256 - height) * y / 100, width, height);
    change.current(canvas.toDataURL('image/png'));
  }, [source, zoom, x, y]);
  useEffect(() => () => { generation.current++; }, []);
  async function choose(file?: File) {
    if (!file) return;
    const current = ++generation.current;
    setError('');
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) {
      setError('Choose a PNG, JPG, or WebP image up to 10 MB.'); return;
    }
    const url = URL.createObjectURL(file);
    try {
      const image = new Image(); image.src = url; await image.decode();
      if (generation.current !== current) return;
      setZoom(1); setX(50); setY(50); setSource(image);
    } catch { if (generation.current === current) setError('Could not open this image. Please choose another file.'); }
    finally { URL.revokeObjectURL(url); }
  }
  return <section style={{ border: '1px solid #d8dde6', borderRadius: 8, padding: 16, marginBottom: 20 }}>
    <strong>Company logo</strong>
    <p style={{ fontSize: 13 }}>Upload a logo and adjust the square crop. The small preview shows its actual size on the customer page.</p>
    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
      <div style={{ width: 168, height: 168, borderRadius: 36, overflow: 'hidden', border: '1px solid #d8dde6', display: 'grid', placeItems: 'center', background: '#f7f7f7' }}>
        {value ? <img src={value} alt="Logo crop preview" style={{ width: '100%', height: '100%' }} /> : <span>Logo preview</span>}
      </div>
      <div style={{ background: '#f5f3ec', padding: 20, borderRadius: 8, display: 'flex', gap: 16, alignItems: 'center' }}>
        <div style={{ width: 56, height: 56, borderRadius: 12, overflow: 'hidden', flexShrink: 0, display: 'grid', placeItems: 'center', color }}>
          {value ? <img src={value} alt="Customer page logo preview" style={{ width: '100%', height: '100%' }} /> : 'LOGO'}
        </div>
        <div><small style={{ textTransform: 'uppercase', letterSpacing: 2, color }}>Welcome to</small><div style={{ fontWeight: 600, fontSize: 22 }}>{name || 'Your company'}</div></div>
      </div>
    </div>
    <label style={{ display: 'block', marginTop: 16 }}>Upload logo <input type="file" accept="image/png,image/jpeg,image/webp" disabled={disabled} onChange={event => { void choose(event.target.files?.[0]); event.target.value = ''; }} /></label>
    {source && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, marginTop: 16 }}>
      <label>Zoom <input type="range" min="1" max="3" step="0.01" value={zoom} disabled={disabled} onChange={event => setZoom(Number(event.target.value))} /></label>
      <label>Horizontal position <input type="range" min="0" max="100" value={x} disabled={disabled} onChange={event => setX(Number(event.target.value))} /></label>
      <label>Vertical position <input type="range" min="0" max="100" value={y} disabled={disabled} onChange={event => setY(Number(event.target.value))} /></label>
    </div>}
    {value && <button type="button" className="slds-button" disabled={disabled} style={{ marginTop: 12 }} onClick={() => { generation.current++; setSource(undefined); onChange(''); }}>Remove logo</button>}
    <p style={{ fontSize: 12 }}>Save Company to apply your logo.</p>
    {error && <p role="alert" style={{ color: '#ba0517' }}>{error}</p>}
  </section>;
}
