import { dimensionFeet } from './dimensions';
import { inventoryActions, type InventoryAction } from './inventoryActions';
import { catalogQuantity, setCatalogQuantity } from './inventoryCatalogQuantities';
import { piecesPerItem } from './inventoryPieces';
import QuestionReferenceImages from './QuestionReferenceImages';
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react';
import './ManualInventoryModal.css';
type CatalogItem = { id: string; name: string; description: string; cuft: number; weight: number };
type RoomType = { id: string; name: string };
type CustomItem = { id: string; catalog_item_id?: string; name_override?: boolean; name: string; cuft: number; quantity: number; reference_name?: string; going?: boolean; mover_pack?: boolean };
type Room = { id: string; room_type_id: string; name: string; items: Record<string, number>; item_names?: Record<string,string>; custom_items?: CustomItem[] };
type Catalog = { rooms: RoomType[]; items: CatalogItem[] };
type InitialRow = { item_id?:string; catalog_item_id?:string; name_override?:boolean; name:string; room?:string; amount?:number; quantity?:number; cuft?:number; unit_cuft?:number; reference_name?:string; going?:boolean };
function linkCatalogItem(item: CustomItem, catalog: Catalog): CustomItem {
  if (item.name_override) return item;
  const normalize = (name: string) => name.toLowerCase().replace(/\s*\((?:cp|pbo)\)\s*$/i, '').replace(/[^a-z0-9]+/g, ' ').trim();
  const name = normalize(item.name);
  const matches = item.catalog_item_id ? catalog.items.filter(row => row.id === item.catalog_item_id) : catalog.items.filter(row => {
    const candidate = normalize(row.name);
    return Math.abs(row.cuft - item.cuft) < 0.001 && (candidate === name || candidate.replace(/ \d+ pieces?$/, '') === name);
  });
  if (matches.length !== 1) return item;
  const matched = matches[0];
  const packing = item.name.match(/\s*\((?:CP|PBO)\)\s*$/i)?.[0] || '';
  return {...item, catalog_item_id: matched.id, reference_name: item.reference_name || item.name, name: matched.name + packing};
}
function packingItemName(name: string) {
  if (/\((?:cp|pbo)\)\s*$/i.test(name)) return name;
  return /\bbox(?:es)?\b|\bdish\s*pack\b/i.test(name) ? `${name} (PBO)` : name;
}
function PackingChoice({ name, disabled, onChange }: { name: string; disabled: boolean; onChange: (checked: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const movers = /\(CP\)\s*$/i.test(name);
  return <span className="mi-packing-choice" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false); }} onKeyDown={event => {
    if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); trigger.current?.focus(); }
  }}>
    <button ref={trigger} type="button" className="mi-packing-trigger" disabled={disabled} aria-expanded={open} aria-label={`Packing for ${name}: ${movers ? 'Movers pack' : 'You pack'}`} onClick={() => setOpen(value => !value)}>
      {movers ? 'CP' : 'PBO'}<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m3 4.5 3 3 3-3"/></svg>
    </button>
    {open && <span className="mi-packing-menu" role="group" aria-label="Who packs this item?">
      {[false, true].map(value => <button type="button" key={String(value)} aria-pressed={movers === value} onClick={() => { onChange(value); setOpen(false); trigger.current?.focus(); }}>
        <span>{value ? 'CP' : 'PBO'}</span><span>{value ? 'Movers pack' : 'You pack'}</span>
        {movers === value && <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m2 6 2.5 2.5L10 3"/></svg>}
      </button>)}
    </span>}
  </span>;
}
function InventoryRow({ name, cuft, quantity, busy, photo, going = true, onGoingChange, onMoverPackChange, packingLocked = false, onSave, onRemove }: {
  name: string; cuft: number; quantity: number; busy: boolean; photo?: ReactNode; going?: boolean; onGoingChange: (going: boolean) => void;
  onMoverPackChange?: (checked: boolean) => void; packingLocked?: boolean;
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
      <div className="mi-inventory-name"><strong>{onMoverPackChange ? name.replace(/\s*\((?:CP|PBO)\)\s*$/i, '') : name}</strong>{onMoverPackChange && <PackingChoice name={name} disabled={busy || packingLocked || !going} onChange={onMoverPackChange}/>}</div>
      <span>{cuft.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
      <span aria-label="Total volume in cubic feet">{totalVolumeLabel}</span>
      <span aria-label={`Quantity: ${quantity}`}>{quantity}</span>
    </>}
    <input className="mi-going-checkbox" type="checkbox" aria-label={`Going: ${name}`} checked={going} disabled={busy} onChange={event => onGoingChange(event.target.checked)} />
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
export default function ManualInventoryModal({ loadCatalog, submitActions, downloadPdf, onDone, onClose, draftKey, initialRooms, initialRows, packing, imageEndpoint, linkKey='', session='' }: {
  submitActions: (requestId: string, actions: InventoryAction[]) => Promise<void>;
  draftKey: string;
  initialRooms?: { room_type_id: string; name: string; items: { item_id: string; quantity: number; name?:string }[]; custom_items?: CustomItem[] }[];
  initialRows?: InitialRow[];
  packing?: { full: boolean; boxes: { label: string; room?: string; quantity: number }[] };
  imageEndpoint?: string;
  linkKey?: string;
  session?: string;
  loadCatalog: () => Promise<Catalog>;
  downloadPdf: (body: { request_id: string; rooms: { room_type_id: string; name: string; items: { item_id: string; quantity: number; name?:string }[]; custom_items?: CustomItem[] }[] }) => Promise<void>;
  onClose: () => void;
  onDone: () => Promise<void>;
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
  const [pdfBusy, setPdfBusy] = useState(false);
  const [error, setError] = useState('');
  const [finishing, setFinishing] = useState(false);
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
        const linked=linkCatalogItem({id:crypto.randomUUID(),catalog_item_id:row.catalog_item_id || (row.item_id?.startsWith('custom-') ? undefined : row.item_id),name_override:row.name_override,name:row.name,cuft:Number(row.unit_cuft||total/quantity)||0.01,quantity,reference_name:row.reference_name},value);
        const itemName=packingItemName(linked.name);
        const itemKey=itemName.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim() + (row.going === false ? ':not-going' : ':going');
        const existing=merged.get(itemKey);
        if(existing){const combined=existing.cuft*existing.quantity+total;existing.quantity+=quantity;existing.cuft=combined/existing.quantity;}
        else merged.set(itemKey,{...linked,name:itemName,quantity,going:row.going !== false,cuft:Number(row.unit_cuft||total/quantity)||0.01,reference_name:row.reference_name||row.name});
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
  const inFlight = useRef<Room[] | null>(null);
  const saving = useRef<Promise<void> | null>(null);
  const loadedRooms = useRef<Room[] | null>(null);
  const dirty = useRef(false);
  const savedRooms = useRef<Room[] | null>(null);
  const submitActionsRef = useRef(submitActions);
  submitActionsRef.current = submitActions;
  const requestIds = useRef(new WeakMap<Room[], string>());
  const retrySnapshot = useRef<Room[] | null>(null);
  function flush(): Promise<void> {
    if (saving.current) return saving.current;
    const operation = (async () => {
      while (retrySnapshot.current || pending.current) {
        const snapshot = retrySnapshot.current || pending.current!;
        if (pending.current === snapshot) pending.current = null;
        inFlight.current = snapshot;
        setSaveStatus('Saving...');
        try {
          const actions = inventoryActions(savedRooms.current || [], snapshot, catalog?.items || []);
          if (actions.length) {
            const requestId = requestIds.current.get(snapshot) || crypto.randomUUID();
            requestIds.current.set(snapshot, requestId);
            await submitActionsRef.current(requestId, actions);
          }
          savedRooms.current = snapshot;
          retrySnapshot.current = null;
          if (latest.current === snapshot) {
            try { localStorage.removeItem(draftKey); } catch { /* The database copy is saved. */ }
          }
        } catch (err) {
          retrySnapshot.current = snapshot;
          pending.current = pending.current || snapshot;
          setSaveStatus('Not saved. Check your connection and retry.');
          throw err;
        } finally {
          inFlight.current = null;
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
    setSaveStatus('Unsaved changes');
    const timer = window.setTimeout(() => {
      void flush().catch(err => setError(err instanceof Error ? err.message : 'Could not save your list.'));
    }, 500);
    return () => window.clearTimeout(timer);
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
      const serverRooms: Room[] = initialRooms?.map(r => ({ id: crypto.randomUUID(), room_type_id: r.room_type_id, name: r.name, custom_items: (r.custom_items || []).map(item => ({ ...item, cuft: Number(item.cuft) })), items: Object.fromEntries(r.items.map(i => [i.item_id, i.quantity])), item_names:Object.fromEntries(r.items.filter(i=>i.name).map(i=>[i.item_id,i.name!])) })) || (initialRows?.length?roomsFromRows(initialRows,value):value.rooms.filter(r => ['bedroom', 'living-room', 'dining-room', 'kitchen'].includes(r.id)).map(r => ({ id: crypto.randomUUID(), room_type_id: r.id, name: r.name, items: {} })));
      const loaded = saved || serverRooms;
      loaded.forEach(room => { room.custom_items = (room.custom_items || []).map(item => linkCatalogItem(item, value)); });
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
      savedRooms.current = initialRooms?.length || initialRows?.length ? serverRooms : [];
      setRooms(loaded);
    }).catch(err => { if (active) setError(err.message); });
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { active = false; document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  const items = new Map((catalog?.items || []).map(item => [item.id, item]));
  const total = (room: Room, field: 'cuft' | 'weight') => Object.entries(room.items).reduce((sum, [id, qty]) => sum + (items.get(id)?.[field] || 0) * qty, 0) + (field === 'cuft' ? (room.custom_items || []).reduce((sum, item) => sum + (item.going === false ? 0 : item.cuft * item.quantity), 0) : 0);
  const count = (room: Room) => Object.values(room.items).reduce((sum, qty) => sum + qty, 0) + (room.custom_items || []).reduce((sum, item) => sum + item.quantity, 0);
  const pieces = (room: Room) => Object.entries(room.items).reduce((sum, [id, qty]) => sum + qty * piecesPerItem(room.item_names?.[id] || items.get(id)?.name || ''), 0)
    + (room.custom_items || []).reduce((sum, item) => sum + item.quantity * piecesPerItem(item.name), 0);
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
  async function download() {
    if (pdfBusy || !catalog) return;
    setPdfBusy(true); setError('');
    try {
      await downloadPdf({ request_id: crypto.randomUUID(), rooms: rooms.map(r => ({
        room_type_id: r.room_type_id, name: r.name.trim(), custom_items: r.custom_items || [],
        items: Object.entries(r.items).filter(([, qty]) => qty > 0).map(([item_id, quantity]) => ({
          item_id, quantity, ...(r.item_names?.[item_id] ? { name: r.item_names[item_id] } : {}),
        })),
      })) });
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not download inventory. Please try again.'); }
    finally { setPdfBusy(false); }
  }
  async function save(calculate = true) {
    if (busy) return;
    if (!catalog) { onClose(); return; }
    if (rooms.some(r => !r.name.trim())) { setError('Enter a name for each room before closing.'); return; }
    if (!calculate && !dirty.current && !pending.current && !saving.current) { onClose(); return; }
    setBusy(true); setError('');
    try {
      if (dirty.current || pending.current || saving.current) {
        if (inFlight.current !== rooms) pending.current = rooms;
        await flush();
      }
      if (calculate) { setFinishing(true); await onDone(); }
      onClose();
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not finish updating your estimate. Please try Done again.'); setBusy(false); }
    finally { setFinishing(false); }
  }
  return <div className="cm-modal-overlay"><div className="mi-modal" ref={modal} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="mi-title" onKeyDown={event => {
    if (event.key === 'Escape' && !busy) { event.preventDefault(); void save(false); }
    if (event.key === 'Tab') {
      const nodes = modal.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)');
      if (!nodes?.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === modal.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }}>
    <header><div><span className="cm-eyebrow">YOUR INVENTORY</span><h2 id="mi-title">Your home, room by room</h2></div><div style={{display: 'flex', alignItems: 'center', gap: 8}}><button type="button" className="slds-button" disabled={busy || pdfBusy || !catalog || !rooms.length || rooms.some(r => !r.name.trim())} title={pdfBusy ? "Preparing PDF..." : "Download inventory PDF"} aria-label={pdfBusy ? "Preparing inventory PDF" : "Download inventory PDF"} aria-busy={pdfBusy} onClick={() => void download()}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/></svg></button><button type="button" className="slds-button" disabled={busy || !catalog || !rooms.length} title="Clear inventory" aria-label="Clear inventory" onClick={() => { setRooms([]); setSelected(''); setCustomOpen(false); }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg></button><button type="button" className="slds-button" disabled={busy} onClick={() => void save(false)} aria-label="Save and close inventory">&times;</button></div></header>
    <div className="mi-totals" aria-live="polite"><span>{rooms.length} rooms</span><span>{rooms.reduce((sum, r) => sum + count(r), 0)} items &middot; {rooms.reduce((sum, r) => sum + pieces(r), 0)} pieces</span><strong>{number(cuft)} cu ft</strong><span>{number(weight)} lb</span></div>
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
          summary={`${count(r)} items \u00b7 ${pieces(r)} pieces \u00b7 ${number(total(r, 'cuft'))} cu ft`}
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
                <button type="button" disabled={busy || !catalogQuantity(room, item.id)} aria-label={`Remove ${item.name} from ${room.name}`} title="Remove item" onClick={() => setRooms(current => current.map(r => r.id === room.id ? setCatalogQuantity(r, item.id, 0) : r))}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg>
                </button>
                <input type="number" min="0" max="999" step="1" aria-label={`Count of ${item.name}`} disabled={busy} value={catalogQuantity(room, item.id) || ''} placeholder="0" onChange={event => {const value = Number(event.target.value); setRooms(current => current.map(r => r.id === room.id ? setCatalogQuantity(r, item.id, value) : r));}} />
                <button type="button" disabled={busy || catalogQuantity(room, item.id) >= 999} aria-label={`Add one ${item.name} to ${room.name}`} title="Add one" onClick={() => setRooms(current => current.map(r => r.id === room.id ? setCatalogQuantity(r, item.id, catalogQuantity(r, item.id) + 1) : r))}>+</button>
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
            <summary><strong>{r.name}</strong> &middot; {count(r)} items &middot; {pieces(r)} pieces</summary>
            <div className="mi-inventory-row mi-inventory-headings"><span>Image</span><span>Item name</span><span>Unit volume<small>cu ft</small></span><span>Total volume<small>cu ft</small></span><span>Qty</span><span>Going</span><span className="mi-inventory-actions-heading">Actions</span></div>
            {Object.entries(r.items).filter(([, qty]) => qty > 0).map(([id, qty]) => <InventoryRow key={id}
              name={packingItemName(r.item_names?.[id] || items.get(id)?.name || 'Item')} cuft={items.get(id)?.cuft || 0} quantity={qty} busy={busy}
              photo={imageEndpoint ? <QuestionReferenceImages compact name={items.get(id)?.name || r.item_names?.[id] || 'Item'} room={r.name} endpoint={imageEndpoint} linkKey={linkKey} session={session}/> : undefined}
              onSave={value => setRooms(current => current.map(valueRoom => valueRoom.id === r.id ? {
                ...valueRoom, items: { ...valueRoom.items, [id]: 0 },
                custom_items: [...(valueRoom.custom_items || []), { id: crypto.randomUUID(), catalog_item_id: id, name_override: value.name !== (r.item_names?.[id] || items.get(id)?.name), ...value, reference_name: items.get(id)?.name }],
              } : valueRoom))}
              onGoingChange={going => setRooms(current => current.map(value => value.id === r.id ? { ...value, items: { ...value.items, [id]: 0 }, custom_items: [...(value.custom_items || []), { id: crypto.randomUUID(), catalog_item_id: id, name: r.item_names?.[id] || items.get(id)?.name || 'Item', cuft: items.get(id)?.cuft || 0.01, quantity: qty, going, reference_name: items.get(id)?.name }] } : value))}
              packingLocked={packing?.full}
              onMoverPackChange={/\bbox(?:es)?\b|\bdish\s*pack\b/i.test(items.get(id)?.name || '') ? checked => setRooms(current => current.map(value => value.id === r.id ? { ...value, items: { ...value.items, [id]: 0 }, custom_items: [...(value.custom_items || []), { id: crypto.randomUUID(), catalog_item_id: id, name: (r.item_names?.[id] || items.get(id)?.name || 'Box').replace(/\s*\((?:CP|PBO)\)\s*$/i, '') + (checked ? ' (CP)' : ' (PBO)'), cuft: items.get(id)?.cuft || 0.01, quantity: qty, mover_pack: checked, reference_name: items.get(id)?.name }] } : value)) : undefined}
              onRemove={() => quantity(id, 0, r.id)} />)}
            {(r.custom_items || []).map(item => <InventoryRow key={item.id} name={packingItemName(item.name)} cuft={item.cuft} quantity={item.quantity} busy={busy}
              going={item.going} onGoingChange={going => setRooms(current => current.map(value => value.id === r.id ? { ...value, custom_items: value.custom_items?.map(entry => entry.id === item.id ? { ...entry, going } : entry) } : value))}
              packingLocked={packing?.full}
              onMoverPackChange={/\bbox(?:es)?\b|\bdish\s*pack\b/i.test(item.name) ? checked => setRooms(current => current.map(value => value.id === r.id ? { ...value, custom_items: value.custom_items?.map(entry => entry.id === item.id ? { ...entry, reference_name: entry.reference_name || entry.name, mover_pack: checked, name: entry.name.replace(/\s*\((?:CP|PBO)\)\s*$/i, '') + (checked ? ' (CP)' : ' (PBO)') } : entry) } : value)) : undefined}
              photo={imageEndpoint ? <QuestionReferenceImages compact name={item.reference_name || item.name} room={r.name} endpoint={imageEndpoint} linkKey={linkKey} session={session}/> : undefined}
              onSave={changes => setRooms(current => current.map(value => value.id === r.id ? { ...value, custom_items: value.custom_items?.map(entry => entry.id === item.id ? { ...entry, name_override: entry.name_override || changes.name !== entry.name, reference_name: entry.reference_name || entry.name, ...changes } : entry) } : value))}
              onRemove={() => setRooms(current => current.map(value => value.id === r.id ? { ...value, custom_items: value.custom_items?.filter(entry => entry.id !== item.id) } : value))} />)}
          </details>)}
          <p><strong>{room ? 'Room total' : 'List total'}: {number(visibleCuft)} cu ft</strong></p>
        </section>
      </>}
    </div>
    <footer><span role="status">{finishing ? 'Updating your estimate...' : busy ? 'Saving your list...' : saveStatus || 'Changes save automatically. Done updates your estimate.'}</span><button type="button" className="slds-button cm-primary" disabled={busy || !catalog || rooms.some(r => !r.name.trim())} onClick={() => void save()}>{finishing ? 'Updating estimate...' : 'Done'}</button></footer>
  </div></div>;
}
