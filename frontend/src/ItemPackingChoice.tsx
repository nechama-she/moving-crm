import { useEffect, useRef } from 'react';

// One packing material of an inventory row: its price per unit and the packing option of each unit, in unit order.
export type ItemPackingMaterial = { name: string; price: number; ids: string[]; groups: string[] };

const money = (value: number) => value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });

// The item packing of an inventory row, as the packing questions set it: for each material, how many units the movers
// pack (CP); the rest are packed by the customer (PBO). Saved on the same choices the questions tab saves.
export default function ItemPackingChoice({ name, materials, picked, disabled, open, setOpen, onChange }: {
  name: string; materials: ItemPackingMaterial[]; picked: ReadonlySet<string>; disabled: boolean;
  open: boolean; setOpen: (open: boolean) => void; onChange: (changes: { id: string; cp: boolean }[]) => void;
}) {
  const container = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!container.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open, setOpen]);
  const trigger = useRef<HTMLButtonElement>(null);
  const units = new Set(materials.flatMap(material => material.groups)).size;
  // A unit is CP when the movers pack it with any of its materials.
  const packed = new Set(materials.flatMap(material => material.ids.flatMap((id, index) => picked.has(id) ? [material.groups[index]] : []))).size;
  const summary = packed === 0 ? 'PBO' : packed === units ? 'CP' : `CP (${packed}), PBO (${units - packed})`;
  // n units of a material packed by the movers: its first n units, the rest not.
  const setCount = (material: ItemPackingMaterial, count: number) => {
    const next = Math.max(0, Math.min(material.ids.length, Math.floor(count)));
    const changes = material.ids.map((id, index) => ({ id, cp: index < next })).filter(change => picked.has(change.id) !== change.cp);
    if (changes.length) onChange(changes);
  };
  return <span ref={container} className="mi-packing-choice mi-service-choice" onBlur={event => { if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false); }} onKeyDown={event => {
    if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); trigger.current?.focus(); }
  }}>
    <button ref={trigger} type="button" className="mi-packing-trigger" disabled={disabled} aria-expanded={open} aria-label={`Item packing for ${name}: ${summary}`} onClick={() => setOpen(!open)}>
      <span className="mi-service-summary"><span>{summary}</span></span><svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m3 4.5 3 3 3-3"/></svg>
    </button>
    {open && <span className="mi-packing-menu" role="group" aria-label={`Who packs ${name}?`}>
      <span className="mi-service-count-heading">{units} {units === 1 ? 'item' : 'items'} total</span>
      {materials.map(material => {
        const count = material.ids.filter(id => picked.has(id)).length;
        return <span className="mi-service-count-row" key={material.name}>
          <span>CP - {material.name} · {money(material.price)} each</span>
          <span className="mi-service-counter">
            <button type="button" aria-label={`Decrease ${material.name}`} disabled={disabled || count === 0} onClick={() => setCount(material, count - 1)}><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M2.5 6h7"/></svg></button>
            <input type="number" min="0" max={material.ids.length} step="1" aria-label={`Items packed with ${material.name}`} disabled={disabled} value={count} onChange={event => { const next = event.target.valueAsNumber; if (Number.isFinite(next)) setCount(material, next); }} />
            <button type="button" aria-label={`Increase ${material.name}`} disabled={disabled || count === material.ids.length} onClick={() => setCount(material, count + 1)}><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M6 2.5v7M2.5 6h7"/></svg></button>
          </span>
        </span>;
      })}
    </span>}
  </span>;
}
