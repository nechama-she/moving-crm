import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import './ManualInventoryModal.css';
type CatalogItem = { id: string; name: string; description: string; cuft: number; weight: number };
type RoomType = { id: string; name: string };
type Room = { id: string; room_type_id: string; name: string; items: Record<string, number> };
type Catalog = { rooms: RoomType[]; items: CatalogItem[] };
export default function ManualInventoryModal({ loadCatalog, submit, onClose, draftKey, initialRooms }: {
  draftKey: string;
  initialRooms?: { room_type_id: string; name: string; items: { item_id: string; quantity: number }[] }[];
  loadCatalog: () => Promise<Catalog>;
  submit: (body: { request_id: string; rooms: { room_type_id: string; name: string; items: { item_id: string; quantity: number }[] }[] }) => Promise<void>;
  onClose: () => void;
}) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selected, setSelected] = useState('');
  const [roomType, setRoomType] = useState('');
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
          await submitRef.current({ request_id: crypto.randomUUID(), rooms: snapshot.map(r => ({ room_type_id: r.room_type_id, name: r.name.trim() || catalog?.rooms.find(t => t.id === r.room_type_id)?.name || 'Room', items: Object.entries(r.items).filter(([, qty]) => qty > 0).map(([item_id, quantity]) => ({ item_id, quantity })) })) });
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
      setRooms(saved || initialRooms?.map(r => ({ id: crypto.randomUUID(), room_type_id: r.room_type_id, name: r.name, items: Object.fromEntries(r.items.map(i => [i.item_id, i.quantity])) })) || value.rooms.filter(r => ['bedroom', 'living-room', 'dining-room', 'kitchen'].includes(r.id)).map(r => ({ id: crypto.randomUUID(), room_type_id: r.id, name: r.name, items: {} })));
    }).catch(err => { if (active) setError(err.message); });
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { active = false; document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  const items = new Map((catalog?.items || []).map(item => [item.id, item]));
  const total = (room: Room, field: 'cuft' | 'weight') => Object.entries(room.items).reduce((sum, [id, qty]) => sum + (items.get(id)?.[field] || 0) * qty, 0);
  const count = (room: Room) => Object.values(room.items).reduce((sum, qty) => sum + qty, 0);
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
      </>}
    </div>
    <footer><span>{busy ? 'Saving your list...' : saveStatus || 'Changes save automatically.'}</span>{room ? <button type="button" className="slds-button cm-primary" disabled={busy} onClick={() => setSelected('')}>Done with room</button> : <button type="button" className="slds-button cm-primary" disabled={busy || !catalog || rooms.some(r => !r.name.trim())} onClick={() => void save()}>Done</button>}</footer>
  </div></div>;
}
