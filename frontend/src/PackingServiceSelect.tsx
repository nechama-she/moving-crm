import {useRef, useState} from 'react';
export type PackingMaterialService = 'self' | 'packing' | 'materials';

const money = (value: number) => value.toLocaleString('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 2,
});

export default function PackingServiceSelect({
  label,
  value,
  packingPrice,
  materialsPrice,
  disabled = false,
  available = true,
  onChange,
}: {
  label: string;
  value: PackingMaterialService;
  packingPrice: number;
  materialsPrice: number;
  disabled?: boolean;
  available?: boolean;
  onChange: (service: PackingMaterialService) => void;
}) {
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const options: {value: PackingMaterialService; label: string}[] = [
    {value: 'self', label: "I'll pack"},
    ...(available ? [
      {value: 'packing' as const, label: `Packing only - ${money(packingPrice)}`},
      {value: 'materials' as const, label: `Packing + materials - ${money(materialsPrice)}`},
    ] : []),
  ];
  const selected = options.find(option => option.value === value) || options[0];
  return <div className="cm-service-picker" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }} onKeyDown={event => {
    if (event.key === 'Escape') { event.stopPropagation(); setOpen(false); trigger.current?.focus(); }
  }}>
    <button ref={trigger} type="button" className="cm-service-picker-trigger" aria-label={`Packing service for ${label}: ${selected.label}`} aria-expanded={open} disabled={disabled || !available} onClick={() => {
      const rect = trigger.current?.getBoundingClientRect();
      const container = trigger.current?.closest('.cm-modal-card')?.getBoundingClientRect();
      if (rect) setAlignRight(rect.left + 230 > (container?.right ?? window.innerWidth) - 16);
      setOpen(current => !current);
    }}>
      {selected.label}
      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><path d="m5 6 3 3 3-3"/></svg>
    </button>
    {open && !disabled && available && <div className="cm-service-picker-options" style={{left: alignRight ? 'auto' : 0, right: alignRight ? 0 : 'auto'}} role="group" aria-label={`Packing service for ${label}`}>
      {options.map(option => <button key={option.value} type="button" aria-pressed={selected.value === option.value} onClick={() => {
        onChange(option.value); setOpen(false); trigger.current?.focus();
      }}>{option.label}</button>)}
    </div>}
    {selected.value === 'packing' && <small style={{display: 'block', fontSize: 11, color: 'var(--cm-text-muted)'}}>Packing only: you supply materials.</small>}
  </div>;
}
