import { dimensionFeet } from './dimensions';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import './ManualInventoryModal.css';
type CatalogItem = { id: string; name: string; description: string; cuft: number; weight: number };
type RoomType = { id: string; name: string };
type CustomItem = { id: string; name: string; cuft: number; quantity: number };
type Room = { id: string; room_type_id: string; name: string; items: Record<string, number>; custom_items?: CustomItem[] };
type Catalog = { rooms: RoomType[]; items: CatalogItem[] };
export default function ManualInventoryModal({ loadCatalog, submit, onClose, draftKey, initialRooms }: {
  draftKey: string;
  initialRooms?: { room_type_id: string; name: string; items: { item_id: string; quantity: number }[]; custom_items?: CustomItem[] }[];
  loadCatalog: () => Promise<Catalog>;
  submit: (body: { request_id: string; rooms: { room_type_id: string; name: string; items: { item_id: string; quantity: number }[]; custom_items?: CustomItem[] }[] }) => Promise<void>;
  onClose: () => void;
}) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selected, setSelected] = useState('');
  const [roomType, setRoomType] = useState('');
  const [customOpen, setCustomOpen] = useState(false);
  const [customName, setCustomName] = useState('');
  const [customDimensions, setCustomDimensions] = useState({ width: '', height: '', depth: '' });
  const validDimensions = Object.values(customDimensions).every(value => dimensionFeet(value) !== null);
  const customCuft = validDimensions ? Number((dimensionFeet(customDimensions.width)! * dimensionFeet(customDimensions.height)! * dimensionFeet(customDimensions.depth)!).toFixed(4)) : 0;
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [draftError, setDraftError] = useState('');
  useLayoutEffect(() => {
    if (!catalog) return;
    try { localStorage.setItem(draftKey, JSON.stringify(rooms)); setDraftError(''); }
    catch { setDraftError('Could not save your draft on this device. Keep this page open until you submit.'); }
  }, [rooms, catalog, draftKey]);
  const [saveStatus, setSaveStatus] = useState('');
  const latest = useRef<Room[]>([]);
  const pending = useRef<Room[] | null>(null);
  const saving = useRef<Promise<void> | null>(null);
  const submitRef = useRef(submit);
  submitRef.current = submit;
  function flush(): Promise<void> {
    if (saving.current) return saving.current;
    const operation = (async () => {
      while (pending.current) {
        const snapshot = pending.current;
        pending.current = null;
        setSaveStatus('Saving...');
        try {
          await submitRef.current({ request_id: crypto.randomUUID(), rooms: snapshot.map(r => ({ room_type_id: r.room_type_id, custom_items: r.custom_items || [], name: r.name.trim() || catalog?.rooms.find(t => t.id === r.room_type_id)?.name || 'Room', items: Object.entries(r.items).filter(([, qty]) => qty > 0).map(([item_id, quantity]) => ({ item_id, quantity })) })) });
          if (latest.current === snapshot) {
            try { localStorage.removeItem(draftKey); } catch { /* The database copy is saved. */ }
          }
        } catch (err) {
          pending.current = pending.current || snapshot;
          setSaveStatus('Not saved. Check your connection and retry.');
          throw err;
        }
      }
      setError('');
      setSaveStatus('All changes saved');
    })();
    saving.current = operation;
    void operation.finally(() => { saving.current = null; }).catch(() => {});
    return operation;
  }
  useEffect(() => {
    if (!catalog) return;
    latest.current = rooms;
    pending.current = rooms;
    void flush().catch(err => setError(err instanceof Error ? err.message : 'Could not save your list.'));
  }, [rooms, catalog]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (pending.current || saving.current) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);
  const modal = useRef<HTMLDivElement>(null);
  const loader = useRef(loadCatalog);
  useEffect(() => {
    let active = true;
    const previous = document.activeElement as HTMLElement | null;
    modal.current?.focus();
    loader.current().then(value => {
      if (!active) return;
      setCatalog(value); setRoomType(value.rooms[0]?.id || '');
      let saved: Room[] | undefined;
      try { const raw = localStorage.getItem(draftKey); if (raw) { const parsed = JSON.parse(raw); if (Array.isArray(parsed) && parsed.every(r => r && typeof r.id === 'string' && typeof r.name === 'string' && typeof r.room_type_id === 'string' && r.items && typeof r.items === 'object' && Object.values(r.items).every(q => typeof q === 'number' && Number.isInteger(q) && q >= 0 && q <= 999))) saved = parsed; } } catch { /* Start with default rooms if storage is unavailable. */ }
      setRooms(saved || initialRooms?.map(r => ({ id: crypto.randomUUID(), room_type_id: r.room_type_id, name: r.name, custom_items: (r.custom_items || []).map(item => ({ ...item, cuft: Number(item.cuft) })), items: Object.fromEntries(r.items.map(i => [i.item_id, i.quantity])) })) || value.rooms.filter(r => ['bedroom', 'living-room', 'dining-room', 'kitchen'].includes(r.id)).map(r => ({ id: crypto.randomUUID(), room_type_id: r.id, name: r.name, items: {} })));
    }).catch(err => { if (active) setError(err.message); });
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { active = false; document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  const items = new Map((catalog?.items || []).map(item => [item.id, item]));
  const total = (room: Room, field: 'cuft' | 'weight') => Object.entries(room.items).reduce((sum, [id, qty]) => sum + (items.get(id)?.[field] || 0) * qty, 0) + (field === 'cuft' ? (room.custom_items || []).reduce((sum, item) => sum + item.cuft * item.quantity, 0) : 0);
  const count = (room: Room) => Object.values(room.items).reduce((sum, qty) => sum + qty, 0) + (room.custom_items || []).reduce((sum, item) => sum + item.quantity, 0);
  const cuft = rooms.reduce((sum, room) => sum + total(room, 'cuft'), 0);
  const weight = rooms.reduce((sum, room) => sum + total(room, 'weight'), 0);
  const room = rooms.find(r => r.id === selected);
  const matches = (catalog?.items || []).filter(item => `${item.name} ${item.description}`.toLowerCase().includes(search.toLowerCase()));
  const number = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  function quantity(id: string, value: number) {
    setRooms(current => current.map(r => r.id === selected ? { ...r, items: { ...r.items, [id]: Math.min(999, Math.max(0, Math.floor(value || 0))) } } : r));
  }
  async function save() {
    if (busy) return;
    if (!catalog) { onClose(); return; }
    if (rooms.some(r => !r.name.trim())) { setError('Enter a name for each room before closing.'); return; }
    setBusy(true); setError('');
    try {
      pending.current = rooms;
      await flush();
      onClose();
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save your list.'); setBusy(false); }
  }
  return <div className="cm-modal-overlay"><div className="mi-modal" ref={modal} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="mi-title" onKeyDown={event => {
    if (event.key === 'Escape' && !busy) { event.preventDefault(); void save(); }
    if (event.key === 'Tab') {
      const nodes = modal.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)');
      if (!nodes?.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === modal.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }}>
    <header><div><span className="cm-eyebrow">YOUR INVENTORY</span><h2 id="mi-title">{room ? `Items in ${room.name}` : 'Your home, room by room'}</h2></div><button type="button" className="slds-button" disabled={busy} onClick={() => void save()} aria-label="Save and close inventory">&times;</button></header>
    <div className="mi-totals" aria-live="polite"><span>{rooms.length} rooms</span><span>{rooms.reduce((sum, r) => sum + count(r), 0)} items</span><strong>{number(cuft)} cu ft</strong><span>{number(weight)} lb</span></div>
    {draftError && <p className="mi-error" role="alert">{draftError}</p>}
    {error && <p className="mi-error" role="alert">{error}</p>}
    <div className="mi-body">
      {!catalog ? <p>Loading item catalog...</p> : room ? <>
        <button type="button" className="slds-button" disabled={busy} onClick={() => setSelected('')}>Back to rooms</button>
        <label className="mi-room-name">Room name<input maxLength={100} value={room.name} disabled={busy} onChange={e => setRooms(current => current.map(r => r.id === selected ? { ...r, name: e.target.value } : r))} /></label>
        <input className="mi-search" type="search" placeholder="Search for an item..." aria-label="Search inventory items" value={search} disabled={busy} onChange={e => { setSearch(e.target.value); setLimit(60); }} />
        <button type="button" className="slds-button" style={{ marginTop: 12 }} onClick={() => setCustomOpen(!customOpen)}>+ Add custom item</button>
        {customOpen && <section className="mi-custom-item">
          <h3>Add an item not in the catalog</h3>
          <p className="mi-dimension-help">Width &times; height &times; depth = cubic feet. Enter 2', 24&quot;, or 2' 6&quot;. Plain numbers mean feet.</p>
          <div className="mi-custom-entry-row">
          <svg viewBox="0 0 260 150" width="120" height="80" role="img" aria-label="Box showing width, height and depth" style={{ maxWidth: '100%', color: 'var(--cm-primary)' }}>
            <g fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M55 50h100v70H55z M55 50l40-28h100v70l-40 28 M155 50l40-28"/><path d="M55 132h100 M40 50v70 M166 43l35-25"/></g>
            <g fill="currentColor" fontSize="12"><text x="83" y="148">Width</text><text x="4" y="88">Height</text><text x="200" y="26">Depth</text></g>
          </svg>
          <label className="mi-custom-name">Item name<input maxLength={200} value={customName} onChange={e => setCustomName(e.target.value)} /></label>
          <div className="mi-custom-dimensions">
            {(['width', 'height', 'depth'] as const).map(dimension => <label key={dimension}>{dimension[0].toUpperCase() + dimension.slice(1)}<input type="text" placeholder={`2' 6"`} aria-invalid={!!customDimensions[dimension] && dimensionFeet(customDimensions[dimension]) === null} value={customDimensions[dimension]} disabled={busy} onChange={e => setCustomDimensions(current => ({ ...current, [dimension]: e.target.value }))} /></label>)}
          </div>
          <p className="mi-custom-volume" aria-live="polite"><strong>Volume: {validDimensions && Number.isFinite(customCuft) ? `${customCuft.toLocaleString(undefined, { maximumFractionDigits: 4 })} cu ft` : '\u2014'}</strong></p>

          <button type="button" className="slds-button cm-primary" disabled={busy || !customName.trim() || !Number.isFinite(Number(customCuft)) || Number(customCuft) <= 0 || Number(customCuft) > 10000} onClick={() => {
            setRooms(current => current.map(r => r.id === selected ? { ...r, custom_items: [...(r.custom_items || []), { id: crypto.randomUUID(), name: customName.trim(), cuft: Number(customCuft), quantity: 1 }] } : r));
            setCustomName(''); setCustomDimensions({ width: '', height: '', depth: '' }); setCustomOpen(false);
          }}>Add item</button>
          </div>
          {Object.values(customDimensions).some(value => value.trim() && dimensionFeet(value) === null) && <p role="status">Use feet (2'), inches (24&quot;), or both (2' 6&quot;).</p>}
          {customCuft > 10000 && <p role="alert">Estimated volume must be 10,000 cu ft or less per item.</p>}
        </section>}
        {(room.custom_items || []).map(item => <div className="mi-item" key={item.id}>
          <div><strong>{item.name}</strong><small>Custom item &middot; {number(item.cuft)} cu ft each</small></div>
          <div className="mi-quantity"><input type="number" min="1" max="999" aria-label={`Quantity of ${item.name}`} value={item.quantity} disabled={busy} onChange={e => setRooms(current => current.map(r => r.id === selected ? { ...r, custom_items: r.custom_items?.map(i => i.id === item.id ? { ...i, quantity: Math.min(999, Math.max(1, Math.floor(Number(e.target.value) || 1))) } : i) } : r))} /><button type="button" className="slds-button" aria-label={`Remove ${item.name}`} disabled={busy} onClick={() => setRooms(current => current.map(r => r.id === selected ? { ...r, custom_items: r.custom_items?.filter(i => i.id !== item.id) } : r))}>&times;</button></div>
        </div>)}
        <p className="mi-hint">{count(room)} items selected in this room. Measurements shown are per item.</p>
        {matches.slice(0, limit).map(item => <div className={`mi-item ${room.items[item.id] ? 'mi-item-selected' : ''}`} key={item.id}>
          <div><strong>{item.name}</strong><small>{number(item.cuft)} cu ft &middot; {number(item.weight)} lb{item.description ? ` - ${item.description}` : ''}</small></div>
          <div className="mi-quantity"><button type="button" className="slds-button" disabled={busy || !room.items[item.id]} aria-label={`Remove one ${item.name}`} onClick={() => quantity(item.id, (room.items[item.id] || 0) - 1)}>&minus;</button><input type="number" min="0" max="999" disabled={busy} aria-label={`Quantity of ${item.name}, ${item.cuft} cubic feet`} value={room.items[item.id] || 0} onChange={e => quantity(item.id, Number(e.target.value))} /><button type="button" className="slds-button" disabled={busy || room.items[item.id] >= 999} aria-label={`Add one ${item.name}`} onClick={() => quantity(item.id, (room.items[item.id] || 0) + 1)}>+</button></div>
        </div>)}
        {!matches.length && <p>No matching items.</p>}
        {matches.length > limit && <button type="button" className="slds-button" onClick={() => setLimit(value => value + 60)}>Show more items</button>}
      </> : <>
        <p>Choose a room to add items. You can add multiple bedrooms or other rooms.</p>
        <div className="mi-rooms">{rooms.map(r => <article key={r.id}><button type="button" disabled={busy} onClick={() => { setSelected(r.id); setSearch(''); setLimit(60); }}><strong>{r.name}</strong><span>{count(r)} items &middot; {number(total(r, 'cuft'))} cu ft</span></button><button type="button" className="mi-remove" disabled={busy} aria-label={`Delete room ${r.name}`} onClick={() => setRooms(current => current.filter(value => value.id !== r.id))}>&times;</button></article>)}</div>
        <div className="mi-add-room"><select aria-label="Room type" value={roomType} disabled={busy} onChange={e => setRoomType(e.target.value)}>{catalog.rooms.map(r => <option value={r.id} key={r.id}>{r.name}</option>)}</select><button type="button" className="slds-button" disabled={busy || rooms.length >= 100 || !roomType} onClick={() => { const type = catalog.rooms.find(r => r.id === roomType)!; const id = crypto.randomUUID(); const n = rooms.filter(r => r.room_type_id === roomType).length; setRooms(current => [...current, { id, room_type_id: roomType, name: type.name + (n ? ` ${n + 1}` : ''), items: {} }]); setSelected(id); setSearch(''); setLimit(60); }}>+ Add room</button></div>
        {rooms.some(r => count(r) > 0) && <section className="mi-room-summary">
          <h3>Your list by room</h3>
          {rooms.filter(r => count(r) > 0).map(r => <details key={r.id} open>
            <summary><strong>{r.name}</strong> &middot; {count(r)} items</summary>
            {Object.entries(r.items).filter(([, qty]) => qty > 0).map(([id, qty]) => <div className="mi-summary-item" key={id}>
              <span>{qty} &times; {items.get(id)?.name || 'Item'}</span>
              <span>{number((items.get(id)?.cuft || 0) * qty)} cu ft</span>
            </div>)}
            {(r.custom_items || []).map(item => <div className="mi-summary-item" key={item.id}><span>{item.quantity} &times; {item.name}</span><span>{number(item.cuft * item.quantity)} cu ft</span></div>)}
          </details>)}
          <p><strong>List total: {number(cuft)} cu ft</strong></p>
        </section>}
      </>}
    </div>
    <footer><span>{busy ? 'Saving your list...' : saveStatus || 'Changes save automatically.'}</span>{room ? <button type="button" className="slds-button cm-primary" disabled={busy} onClick={() => setSelected('')}>Done with room</button> : <button type="button" className="slds-button cm-primary" disabled={busy || !catalog || rooms.some(r => !r.name.trim())} onClick={() => void save()}>Done</button>}</footer>
  </div></div>;
}
