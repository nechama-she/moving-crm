import { dimensionFeet } from './dimensions';
import QuestionReferenceImages from './QuestionReferenceImages';
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react';
import './ManualInventoryModal.css';
type CatalogItem = { id: string; name: string; description: string; cuft: number; weight: number };
type RoomType = { id: string; name: string };
type CustomItem = { id: string; name: string; cuft: number; quantity: number; reference_name?: string; going?: boolean };
type Room = { id: string; room_type_id: string; name: string; items: Record<string, number>; item_names?: Record<string,string>; custom_items?: CustomItem[] };
type Catalog = { rooms: RoomType[]; items: CatalogItem[] };
type InitialRow = { name:string; room?:string; amount?:number; quantity?:number; cuft?:number; unit_cuft?:number; reference_name?:string; going?:boolean };
function packingItemName(name: string) {
  if (/\((?:cp|pbo)\)\s*$/i.test(name)) return name;
  return /\bbox(?:es)?\b|\bdish\s*pack\b/i.test(name) ? `${name} (PBO)` : name;
}
function InventoryRow({ name, cuft, quantity, busy, photo, going = true, onGoingChange, onSave, onRemove }: {
  name: string; cuft: number; quantity: number; busy: boolean; photo?: ReactNode; going?: boolean; onGoingChange: (going: boolean) => void;
  onSave: (value: { name: string; cuft: number; quantity: number }) => void; onRemove: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ name, cuft: String(cuft), quantity: String(quantity) });
  const valid = draft.name.trim() && Number(draft.cuft) > 0 && Number(draft.cuft) <= 10000 && Number.isInteger(Number(draft.quantity)) && Number(draft.quantity) >= 1 && Number(draft.quantity) <= 999;
  const totalVolume = editing ? Number(draft.cuft) * Number(draft.quantity) : cuft * quantity;
  const totalVolumeLabel = Number.isFinite(totalVolume) ? totalVolume.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '';
  const save = () => { if (!valid) return; onSave({ name: draft.name.trim(), cuft: Number(draft.cuft), quantity: Number(draft.quantity) }); setEditing(false); };
  return <div className="mi-inventory-row" onKeyDown={event => {
    if (!editing) return;
    if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); save(); }
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setEditing(false); }
  }}>
    <div className="mi-inventory-photo">{photo}</div>
    {editing ? <>
      <input autoFocus aria-label="Item name" maxLength={200} value={draft.name} disabled={busy} onChange={e => setDraft({ ...draft, name: e.target.value })} />
      <label className="mi-inventory-volume"><input aria-label="Cubic feet per item" type="number" min="0.0001" max="10000" step="any" value={draft.cuft} disabled={busy} onChange={e => setDraft({ ...draft, cuft: e.target.value })} /></label>
      <span aria-label="Total volume in cubic feet">{totalVolumeLabel}</span>
      <input aria-label="Quantity" type="number" min="1" max="999" step="1" value={draft.quantity} disabled={busy} onChange={e => setDraft({ ...draft, quantity: e.target.value })} />
    </> : <>
      <strong>{name}</strong>
      <span>{cuft.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
      <span aria-label="Total volume in cubic feet">{totalVolumeLabel}</span>
      <span aria-label={`Quantity: ${quantity}`}>{quantity}</span>
    </>}
    <select aria-label={`Moving status of ${name}`} value={going ? 'going' : 'not-going'} disabled={busy} onChange={event => onGoingChange(event.target.value === 'going')}><option value="going">Going</option><option value="not-going">Not going</option></select>
    <button type="button" className="slds-button" disabled={busy || (editing && !valid)} aria-label={editing ? `Save ${name}` : `Edit ${name}`} title={editing ? 'Save item' : 'Edit item'} onClick={() => {
      if (editing) save(); else { setDraft({ name, cuft: String(cuft), quantity: String(quantity) }); setEditing(true); }
    }}>{editing ? <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/></svg> : <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m16 3 5 5-12 12-6 1 1-6Z M14 5l5 5" /></svg>}</button>
    <button type="button" className="slds-button" disabled={busy} aria-label={`Remove ${name}`} onClick={onRemove}>&times;</button>
  </div>;
}
function RoomCard({ room, selected, busy, summary, onSelect, onRename, onDelete }: {
  room: Room; selected: boolean; busy: boolean; summary: string;
  onSelect: () => void; onRename: (name: string) => void; onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(room.name);
  const cancelled = useRef(false);
  const pencil = useRef<HTMLButtonElement>(null);
  const commit = () => {
    if (!cancelled.current && draft.trim() && draft.trim() !== room.name) onRename(draft.trim());
    setEditing(false);
  };
  return <article className={selected ? 'mi-room-selected' : ''}>
    <button type="button" className="mi-room-filter" disabled={busy} aria-label={`Filter by ${room.name}`} aria-pressed={selected} onClick={onSelect} />
    <div className="mi-room-card-content">
      <div className="mi-room-card-name">
        {editing ? <input autoFocus aria-label={`Room name: ${room.name}`} maxLength={100} value={draft} disabled={busy}
          onFocus={event => event.currentTarget.select()} onChange={event => setDraft(event.target.value)} onBlur={commit}
          onKeyDown={event => {
            if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); event.currentTarget.blur(); pencil.current?.focus(); }
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancelled.current = true; setEditing(false); pencil.current?.focus(); }
          }} /> : <strong>{room.name}</strong>}
        <button ref={pencil} type="button" className="mi-room-rename" disabled={busy} aria-label={`Rename room ${room.name}`} title="Rename room" onClick={() => { cancelled.current = false; setDraft(room.name); setEditing(true); }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m16 3 5 5-12 12-6 1 1-6Z M14 5l5 5" /></svg>
        </button>
      </div>
      <span>{summary}</span>
    </div>
    <button type="button" className="mi-remove" disabled={busy} aria-label={`Delete room ${room.name}`} onClick={onDelete}>&times;</button>
  </article>;
}
export default function ManualInventoryModal({ loadCatalog, submit, onClose, draftKey, initialRooms, initialRows, packing, imageEndpoint, linkKey='', session='' }: {
  draftKey: string;
  initialRooms?: { room_type_id: string; name: string; items: { item_id: string; quantity: number; name?:string }[]; custom_items?: CustomItem[] }[];
  initialRows?: InitialRow[];
  packing?: { full: boolean; boxes: { label: string; room?: string; quantity: number }[] };
  imageEndpoint?: string;
  linkKey?: string;
  session?: string;
  loadCatalog: () => Promise<Catalog>;
  submit: (body: { request_id: string; rooms: { room_type_id: string; name: string; items: { item_id: string; quantity: number; name?:string }[]; custom_items?: CustomItem[] }[] }) => Promise<void>;
  onClose: () => void;
}) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selected, setSelected] = useState('');
  const [roomPickerOpen, setRoomPickerOpen] = useState(false);
  const addRoomButton = useRef<HTMLButtonElement>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogSearch, setCatalogSearch] = useState('');
  const [catalogLimit, setCatalogLimit] = useState(60);
  const catalogScroll = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setCatalogOpen(false); setCustomOpen(false); setCatalogSearch(''); setCatalogLimit(60);
  }, [selected]);
  const [customName, setCustomName] = useState('');
  const [customDimensions, setCustomDimensions] = useState({ width: '', height: '', depth: '' });
  const [manualCuft, setManualCuft] = useState<string | null>(null);
  const validDimensions = Object.values(customDimensions).every(value => dimensionFeet(value) !== null);
  const customCuft = manualCuft !== null ? Number(manualCuft) : validDimensions ? Number((dimensionFeet(customDimensions.width)! * dimensionFeet(customDimensions.height)! * dimensionFeet(customDimensions.depth)!).toFixed(4)) : 0;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [draftError, setDraftError] = useState('');
  function roomsFromRows(rows:InitialRow[], value:Catalog):Room[] {
    const normalized=(text:string)=>text.toLowerCase().replace(/\s*\((?:cp|pbo)\)\s*$/i,'').replace(/[^a-z0-9]+/g,' ').trim();
    const grouped=new Map<string,InitialRow[]>();
    rows.forEach(row=>{const name=row.room?.trim()||'Other items';grouped.set(name,[...(grouped.get(name)||[]),row]);});
    return [...grouped].map(([name,contents])=>{
      const key=normalized(name);
      const type=value.rooms.find(candidate=>normalized(candidate.name)===key || key.includes(normalized(candidate.name)) || normalized(candidate.name).includes(key)) || value.rooms[0];
      const merged=new Map<string,CustomItem>();
      contents.forEach(row=>{
        const quantity=Math.max(1,Math.floor(Number(row.amount??row.quantity??1)||1));
        const total=Math.max(0.01,row.unit_cuft != null ? Number(row.unit_cuft) * quantity : Number(row.cuft||0));
        const itemName=packingItemName(String(row.name||'Item'));
        const itemKey=itemName.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim() + (row.going === false ? ':not-going' : ':going');
        const existing=merged.get(itemKey);
        if(existing){const combined=existing.cuft*existing.quantity+total;existing.quantity+=quantity;existing.cuft=combined/existing.quantity;}
        else merged.set(itemKey,{id:crypto.randomUUID(),name:itemName,quantity,going:row.going !== false,cuft:Number(row.unit_cuft||total/quantity)||0.01,reference_name:row.reference_name||row.name});
      });
      return {id:crypto.randomUUID(),room_type_id:type?.id||'',name,items:{},custom_items:[...merged.values()]};
    });
  }
  useLayoutEffect(() => {
    if (!catalog || loadedRooms.current === rooms) return;
    try { localStorage.setItem(draftKey, JSON.stringify(rooms)); setDraftError(''); }
    catch { setDraftError('Could not save your draft on this device. Keep this page open until you submit.'); }
  }, [rooms, catalog, draftKey]);
  const [saveStatus, setSaveStatus] = useState('');
  const latest = useRef<Room[]>([]);
  const pending = useRef<Room[] | null>(null);
  const saving = useRef<Promise<void> | null>(null);
  const loadedRooms = useRef<Room[] | null>(null);
  const dirty = useRef(false);
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
          await submitRef.current({ request_id: crypto.randomUUID(), rooms: snapshot.map(r => ({ room_type_id: r.room_type_id, custom_items: r.custom_items || [], name: r.name.trim() || catalog?.rooms.find(t => t.id === r.room_type_id)?.name || 'Room', items: Object.entries(r.items).filter(([, qty]) => qty > 0).map(([item_id, quantity]) => ({ item_id, quantity, ...(r.item_names?.[item_id] ? {name:r.item_names[item_id]} : {}) })) })) });
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
      dirty.current = false;
    })();
    saving.current = operation;
    void operation.finally(() => { saving.current = null; }).catch(() => {});
    return operation;
  }
  useEffect(() => {
    if (!catalog) return;
    latest.current = rooms;
    if (loadedRooms.current === rooms) {
      loadedRooms.current = null;
      return;
    }
    dirty.current = true;
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
      setCatalog(value);
      let saved: Room[] | undefined;
      try { const raw = localStorage.getItem(draftKey); if (raw) { const parsed = JSON.parse(raw); if (Array.isArray(parsed) && parsed.every(r => r && typeof r.id === 'string' && typeof r.name === 'string' && typeof r.room_type_id === 'string' && r.items && typeof r.items === 'object' && Object.values(r.items).every(q => typeof q === 'number' && Number.isInteger(q) && q >= 0 && q <= 999))) saved = parsed; } } catch { /* Start with default rooms if storage is unavailable. */ }
      const loaded: Room[] = saved || initialRooms?.map(r => ({ id: crypto.randomUUID(), room_type_id: r.room_type_id, name: r.name, custom_items: (r.custom_items || []).map(item => ({ ...item, cuft: Number(item.cuft) })), items: Object.fromEntries(r.items.map(i => [i.item_id, i.quantity])), item_names:Object.fromEntries(r.items.filter(i=>i.name).map(i=>[i.item_id,i.name!])) })) || (initialRows?.length?roomsFromRows(initialRows,value):value.rooms.filter(r => ['bedroom', 'living-room', 'dining-room', 'kitchen'].includes(r.id)).map(r => ({ id: crypto.randomUUID(), room_type_id: r.id, name: r.name, items: {} })));
      if (packing) {
        const baseName = (name: string) => name.replace(/\s*\((?:CP|PBO)\)\s*$/i, '').trim();
        const key = (room: string, name: string) => `${room.trim().toLowerCase()}:${baseName(name).toLowerCase()}`;
        const remaining = new Map(packing.boxes.map(box => [key(box.room || 'Other items', box.label), box.quantity]));
        for (const room of loaded) {
          room.custom_items = (room.custom_items || []).flatMap(item => {
            if (item.going === false || !/\bbox(?:es)?\b|\bdish\s*pack\b/i.test(item.name)) return [item];
            const id = key(room.name, item.name);
            const cp = packing.full ? item.quantity : Math.min(item.quantity, remaining.get(id) || 0);
            remaining.set(id, Math.max(0, (remaining.get(id) || 0) - cp));
            return [
              ...(cp ? [{ ...item, name: `${baseName(item.name)} (CP)`, quantity: cp }] : []),
              ...(cp < item.quantity ? [{ ...item, id: cp ? crypto.randomUUID() : item.id, name: `${baseName(item.name)} (PBO)`, quantity: item.quantity - cp }] : []),
            ];
          });
        }
      }
      loadedRooms.current = loaded;
      setRooms(loaded);
    }).catch(err => { if (active) setError(err.message); });
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { active = false; document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  const items = new Map((catalog?.items || []).map(item => [item.id, item]));
  const total = (room: Room, field: 'cuft' | 'weight') => Object.entries(room.items).reduce((sum, [id, qty]) => sum + (items.get(id)?.[field] || 0) * qty, 0) + (field === 'cuft' ? (room.custom_items || []).reduce((sum, item) => sum + (item.going === false ? 0 : item.cuft * item.quantity), 0) : 0);
  const count = (room: Room) => Object.values(room.items).reduce((sum, qty) => sum + qty, 0) + (room.custom_items || []).reduce((sum, item) => sum + item.quantity, 0);
  const cuft = rooms.reduce((sum, room) => sum + total(room, 'cuft'), 0);
  const weight = rooms.reduce((sum, room) => sum + total(room, 'weight'), 0);
  const room = rooms.find(r => r.id === selected);
  const catalogWords = catalogSearch.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const catalogMatches = (catalog?.items || []).filter(item => catalogWords.every(word => `${item.name} ${item.description}`.toLowerCase().includes(word)));
  const visibleRooms = room ? [room] : rooms;
  const visibleCuft = visibleRooms.reduce((sum, value) => sum + total(value, 'cuft'), 0);
  const number = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  function quantity(id: string, value: number, roomId = selected) {
    setRooms(current => current.map(r => r.id === roomId ? { ...r, items: { ...r.items, [id]: Math.min(999, Math.max(0, Math.floor(value || 0))) } } : r));
  }
  async function save() {
    if (busy) return;
    if (!catalog) { onClose(); return; }
    if (rooms.some(r => !r.name.trim())) { setError('Enter a name for each room before closing.'); return; }
    if (!dirty.current && !pending.current && !saving.current) { onClose(); return; }
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
    <header><div><span className="cm-eyebrow">YOUR INVENTORY</span><h2 id="mi-title">Your home, room by room</h2></div><button type="button" className="slds-button" disabled={busy} onClick={() => void save()} aria-label="Save and close inventory">&times;</button></header>
    <div className="mi-totals" aria-live="polite"><span>{rooms.length} rooms</span><span>{rooms.reduce((sum, r) => sum + count(r), 0)} items</span><strong>{number(cuft)} cu ft</strong><span>{number(weight)} lb</span></div>
    {draftError && <p className="mi-error" role="alert">{draftError}</p>}
    {error && <p className="mi-error" role="alert">{error}</p>}
    <div className="mi-body">
      {!catalog ? <p>Loading inventory...</p> : <>
        <div className="mi-room-toolbar">
          <p>Choose a room to update its inventory, or add a room.</p>
          <div className="mi-room-picker" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setRoomPickerOpen(false); }} onKeyDown={event => {
            if (event.key === 'Escape' && roomPickerOpen) { event.preventDefault(); event.stopPropagation(); setRoomPickerOpen(false); addRoomButton.current?.focus(); }
          }}>
            <button ref={addRoomButton} type="button" className="slds-button" disabled={busy || rooms.length >= 100 || !catalog.rooms.length} aria-expanded={roomPickerOpen} aria-controls="mi-room-choices" onClick={() => setRoomPickerOpen(open => !open)}>+ Add room</button>
            {roomPickerOpen && <div id="mi-room-choices" className="mi-room-choices" role="group" aria-label="Choose a room to add">
              {catalog.rooms.map(type => <button type="button" key={type.id} disabled={busy} onClick={() => {
                const id = crypto.randomUUID();
                const n = rooms.filter(r => r.room_type_id === type.id).length;
                setRooms(current => [...current, { id, room_type_id: type.id, name: type.name + (n ? ` ${n + 1}` : ''), items: {} }]);
                setSelected(id); setCustomOpen(false); setRoomPickerOpen(false); addRoomButton.current?.focus();
              }}>{type.name}</button>)}
            </div>}
          </div>
        </div>
        <div className="mi-rooms">{rooms.map(r => <RoomCard key={r.id} room={r} selected={r.id === selected} busy={busy}
          summary={`${count(r)} items \u00b7 ${number(total(r, 'cuft'))} cu ft`}
          onSelect={() => { setSelected(current => current === r.id ? '' : r.id); setCustomOpen(false); }}
          onRename={name => setRooms(current => current.map(value => value.id === r.id ? { ...value, name } : value))}
          onDelete={() => { setRooms(current => current.filter(value => value.id !== r.id)); if (selected === r.id) { setSelected(''); setCustomOpen(false); } }} />)}</div>
        {room &&
        <section className="mi-room-editor">
        <button type="button" className="slds-button" style={{ marginTop: 12 }} disabled={busy} aria-expanded={catalogOpen} aria-controls="mi-add-item-catalog" onClick={() => { setCatalogOpen(open => !open); setCustomOpen(false); }}>+ Add item</button>
        {catalogOpen && <section className="mi-catalog-card" id="mi-add-item-catalog" aria-label="Add inventory items">
          <div className="mi-catalog-toolbar">
            <input type="search" placeholder="Search items..." aria-label="Search catalog items" value={catalogSearch} disabled={busy} onChange={event => { setCatalogSearch(event.target.value); setCatalogLimit(60); catalogScroll.current?.scrollTo({ top: 0 }); }} />
            <button type="button" className="slds-button" disabled={busy} aria-expanded={customOpen} onClick={() => setCustomOpen(open => !open)}>+ Add custom item</button>
          </div>
        {customOpen && <section className="mi-custom-item">
          <h3>Add a custom item</h3>
          <p className="mi-dimension-help">Enter cubic feet directly, or calculate it from width &times; height &times; depth. For dimensions, enter 2', 24&quot;, or 2' 6&quot;. Plain numbers mean feet.</p>
          <div className="mi-custom-entry-row">
          <svg viewBox="0 0 260 150" width="120" height="80" role="img" aria-label="Box showing width, height and depth" style={{ maxWidth: '100%', color: 'var(--cm-primary)' }}>
            <g fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M55 50h100v70H55z M55 50l40-28h100v70l-40 28 M155 50l40-28"/><path d="M55 132h100 M40 50v70 M166 43l35-25"/></g>
            <g fill="currentColor" fontSize="12"><text x="83" y="148">Width</text><text x="4" y="88">Height</text><text x="200" y="26">Depth</text></g>
          </svg>
          <label className="mi-custom-name">Item name<input maxLength={200} value={customName} onChange={e => setCustomName(e.target.value)} /></label>
          <div className="mi-custom-dimensions">
            {(['width', 'height', 'depth'] as const).map(dimension => <label key={dimension}>{dimension[0].toUpperCase() + dimension.slice(1)}<input type="text" placeholder={`2' 6"`} aria-invalid={!!customDimensions[dimension] && dimensionFeet(customDimensions[dimension]) === null} value={customDimensions[dimension]} disabled={busy} onChange={e => { setManualCuft(null); setCustomDimensions(current => ({ ...current, [dimension]: e.target.value })); }} /></label>)}
          </div>
          <label className="mi-custom-volume">Volume (cu ft)<input type="number" min="0.0001" max="10000" step="any" aria-label="Volume per item in cubic feet" value={manualCuft ?? (validDimensions && Number.isFinite(customCuft) ? String(customCuft) : '')} disabled={busy} onChange={e => { setManualCuft(e.target.value); setCustomDimensions({ width: '', height: '', depth: '' }); }} /></label>

          <button type="button" className="slds-button cm-primary" disabled={busy || !customName.trim() || !Number.isFinite(Number(customCuft)) || Number(customCuft) <= 0 || Number(customCuft) > 10000} onClick={() => {
            setRooms(current => current.map(r => r.id === selected ? { ...r, custom_items: [...(r.custom_items || []), { id: crypto.randomUUID(), name: customName.trim(), cuft: Number(customCuft), quantity: 1 }] } : r));
            setCustomName(''); setManualCuft(null); setCustomDimensions({ width: '', height: '', depth: '' }); setCustomOpen(false);
          }}>Add item</button>
          </div>
          {Object.values(customDimensions).some(value => value.trim() && dimensionFeet(value) === null) && <p role="status">Use feet (2'), inches (24&quot;), or both (2' 6&quot;).</p>}
          {customCuft > 10000 && <p role="alert">Estimated volume must be 10,000 cu ft or less per item.</p>}
        </section>}
          <div className="mi-catalog-scroll" ref={catalogScroll} tabIndex={0} aria-label="Catalog items" onScroll={event => {
            const list = event.currentTarget;
            if (list.scrollHeight - list.scrollTop - list.clientHeight < 160) setCatalogLimit(limit => Math.min(limit + 60, catalogMatches.length));
          }}>
            {catalogMatches.slice(0, catalogLimit).map(item => <div className="mi-catalog-row" key={item.id}>
              <div><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</div>
              <span>{number(item.cuft)} cu ft</span>
              <div className="mi-catalog-count" role="group" aria-label={`Quantity of ${item.name}`}>
                <button type="button" disabled={busy || !room.items[item.id]} aria-label={`Remove ${item.name} from ${room.name}`} title="Remove item" onClick={() => quantity(item.id, 0, room.id)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg>
                </button>
                <input type="number" min="0" max="999" step="1" aria-label={`Count of ${item.name}`} disabled={busy} value={room.items[item.id] || ''} placeholder="0" onChange={event => quantity(item.id, Number(event.target.value), room.id)} />
                <button type="button" disabled={busy || (room.items[item.id] || 0) >= 999} aria-label={`Add one ${item.name} to ${room.name}`} title="Add one" onClick={() => quantity(item.id, (room.items[item.id] || 0) + 1, room.id)}>+</button>
              </div>
            </div>)}
            {!catalogMatches.length && <p>No matching items. You can add a custom item above.</p>}
            {catalogMatches.length > catalogLimit && <p className="mi-catalog-more">Scroll for more items</p>}
          </div>
        </section>}
        </section>}
        <section className="mi-room-summary">
          <h3>Your inventory</h3>
          {!visibleRooms.some(r => count(r) > 0) && <p>{room ? 'No items in this room yet. Click Add item to get started.' : 'No items yet. Choose a room to add an item.'}</p>}
          {visibleRooms.filter(r => count(r) > 0).map(r => <details key={r.id} open>
            <summary><strong>{r.name}</strong> &middot; {count(r)} items</summary>
            <div className="mi-inventory-row mi-inventory-headings"><span>Image</span><span>Item name</span><span>Unit volume<small>cu ft</small></span><span>Total volume<small>cu ft</small></span><span>Qty</span><span>Status</span><span className="mi-inventory-actions-heading">Actions</span></div>
            {Object.entries(r.items).filter(([, qty]) => qty > 0).map(([id, qty]) => <InventoryRow key={id}
              name={packingItemName(r.item_names?.[id] || items.get(id)?.name || 'Item')} cuft={items.get(id)?.cuft || 0} quantity={qty} busy={busy}
              onSave={value => setRooms(current => current.map(valueRoom => valueRoom.id === r.id ? {
                ...valueRoom, items: { ...valueRoom.items, [id]: 0 },
                custom_items: [...(valueRoom.custom_items || []), { id: crypto.randomUUID(), ...value, reference_name: items.get(id)?.name }],
              } : valueRoom))}
              onGoingChange={going => setRooms(current => current.map(value => value.id === r.id ? { ...value, items: { ...value.items, [id]: 0 }, custom_items: [...(value.custom_items || []), { id: crypto.randomUUID(), name: r.item_names?.[id] || items.get(id)?.name || 'Item', cuft: items.get(id)?.cuft || 0.01, quantity: qty, going }] } : value))}
              onRemove={() => quantity(id, 0, r.id)} />)}
            {(r.custom_items || []).map(item => <InventoryRow key={item.id} name={packingItemName(item.name)} cuft={item.cuft} quantity={item.quantity} busy={busy}
              going={item.going} onGoingChange={going => setRooms(current => current.map(value => value.id === r.id ? { ...value, custom_items: value.custom_items?.map(entry => entry.id === item.id ? { ...entry, going } : entry) } : value))}
              photo={imageEndpoint && item.reference_name ? <QuestionReferenceImages compact name={item.reference_name} room={r.name} endpoint={imageEndpoint} linkKey={linkKey} session={session}/> : undefined}
              onSave={changes => setRooms(current => current.map(value => value.id === r.id ? { ...value, custom_items: value.custom_items?.map(entry => entry.id === item.id ? { ...entry, ...changes } : entry) } : value))}
              onRemove={() => setRooms(current => current.map(value => value.id === r.id ? { ...value, custom_items: value.custom_items?.filter(entry => entry.id !== item.id) } : value))} />)}
          </details>)}
          <p><strong>{room ? 'Room total' : 'List total'}: {number(visibleCuft)} cu ft</strong></p>
        </section>
      </>}
    </div>
    <footer><span>{busy ? 'Saving your list...' : saveStatus || 'Changes save automatically.'}</span><button type="button" className="slds-button cm-primary" disabled={busy || !catalog || rooms.some(r => !r.name.trim())} onClick={() => void save()}>Done</button></footer>
  </div></div>;
}
