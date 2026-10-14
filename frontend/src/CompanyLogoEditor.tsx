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
  const initialValue = useRef(value);
  const drag = useRef<{ x: number; y: number; left: number; top: number }>();
  useEffect(() => {
    if (!initialValue.current) return;
    let active = true;
    const image = new Image(); image.src = initialValue.current;
    void image.decode().then(() => { if (active && generation.current === 0) setSource(image); }).catch(() => {});
    return () => { active = false; };
  }, []);
  const change = useRef(onChange);
  change.current = onChange;
  useEffect(() => {
    if (!source) return;
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256;
    const context = canvas.getContext('2d');
    if (!context) { setError('Image preview is unavailable in this browser.'); return; }
    const scale = Math.min(256 / source.naturalWidth, 256 / source.naturalHeight) * zoom;
    const width = source.naturalWidth * scale, height = source.naturalHeight * scale;
    context.drawImage(source, (256 - width) / 2 + (x - 50) * 2.56, (256 - height) / 2 + (y - 50) * 2.56, width, height);
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
    <p style={{ fontSize: 13 }}>Upload a logo, drag it to reposition, and resize it with Zoom. The small preview shows its actual size on the customer page.</p>
    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
      <div onPointerDown={event => {
        if (disabled || !source) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { x: event.clientX, y: event.clientY, left: x, top: y };
      }} onPointerMove={event => {
        if (!drag.current || disabled) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        setX(Math.max(-50, Math.min(150, drag.current.left + (event.clientX - drag.current.x) / bounds.width * 100)));
        setY(Math.max(-50, Math.min(150, drag.current.top + (event.clientY - drag.current.y) / bounds.height * 100)));
      }} onPointerUp={() => { drag.current = undefined; }} onPointerCancel={() => { drag.current = undefined; }}
      style={{ touchAction: 'none', cursor: source && !disabled ? 'grab' : 'default', flexShrink: 0, width: 168, height: 168, borderRadius: 36, overflow: 'hidden', border: '1px solid #d8dde6', display: 'grid', placeItems: 'center', background: '#f7f7f7' }}>
        {value ? <img draggable={false} src={value} alt="Logo crop preview" style={{ display: 'block', minWidth: 0, minHeight: 0, objectFit: 'contain', width: '100%', height: '100%' }} /> : <span>Logo preview</span>}
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
      <button type="button" className="slds-button" disabled={disabled} onClick={() => { setZoom(1); setX(50); setY(50); }}>Fit logo</button>
      <label>Zoom <input type="range" min="0.1" max="3" step="0.01" value={zoom} disabled={disabled} onChange={event => setZoom(Number(event.target.value))} /></label>
      <label>Horizontal position <input type="range" min="-50" max="150" value={x} disabled={disabled} onChange={event => setX(Number(event.target.value))} /></label>
      <label>Vertical position <input type="range" min="-50" max="150" value={y} disabled={disabled} onChange={event => setY(Number(event.target.value))} /></label>
    </div>}
    {value && <button type="button" className="slds-button" disabled={disabled} style={{ marginTop: 12 }} onClick={() => { generation.current++; setSource(undefined); onChange(''); }}>Remove logo</button>}
    <p style={{ fontSize: 12 }}>Save Company to apply your logo.</p>
    {error && <p role="alert" style={{ color: '#ba0517' }}>{error}</p>}
  </section>;
}
