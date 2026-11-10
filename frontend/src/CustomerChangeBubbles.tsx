import { useEffect, useState } from 'react';
import './CustomerChangeBubbles.css';

/** A change another open page of this move saved, as it arrived: by the customer or the team, with the customer's name
 *  or the lead's rep's name (blank when unknown). */
export type MoveChange = { id: string; change: string; by: 'customer' | 'team'; name: string; at: number };

// What each change did, after who did it ("The customer signed the estimate").
const WHAT: Record<string, string> = {
  estimate_signed: 'signed the estimate',
  estimate_signature_cancelled: 'cancelled the estimate signature',
  estimate_approved: 'approved the estimate',
  bill_of_lading_signed: 'signed the Bill of Lading',
  inventory_updated: 'updated the inventory',
  item_questions_answered: 'answered questions about items',
  inventory_report_chosen: 'chose an inventory report',
  estimate_updated: 'updated the estimate',
  packing_changed: 'changed packing or extra services',
  details_updated: 'updated the move details',
  discount_chosen: 'chose a discount',
  discounts_changed: 'changed the discounts',
  files_uploaded: 'uploaded files',
  file_deleted: 'deleted a file',
  walkthrough_requested: 'requested a virtual walkthrough',
  reschedule_requested: 'asked to reschedule',
};
const SIGNED = new Set(['estimate_signed', 'estimate_signature_cancelled', 'estimate_approved', 'bill_of_lading_signed']);
const MONEY = new Set(['estimate_updated', 'packing_changed', 'discount_chosen', 'discounts_changed']);
const FILES = new Set(['files_uploaded', 'file_deleted']);
const INVENTORY = new Set(['inventory_updated', 'item_questions_answered', 'inventory_report_chosen']);
const SHOWN = 6;

export function describeChange(item: MoveChange, repPage: boolean) {
  const what = WHAT[item.change];
  if (!what) return '';
  if (item.by === 'team') return `${item.name || (repPage ? 'Your team' : 'Your moving team')} ${what}`;
  return repPage ? `${item.name || 'The customer'} ${what}` : `You ${what} on another device`;
}

function ChangeIcon({ change }: { change: string }) {
  const path = SIGNED.has(change) ? 'M3 21h18M5 17l9.5-9.5 3 3L8 20H5v-3Zm11-11 2-2 3 3-2 2'
    : MONEY.has(change) ? 'M12 3v18M16.5 7.5c0-1.7-2-3-4.5-3s-4.5 1.3-4.5 3 2 2.6 4.5 3 4.5 1.3 4.5 3-2 3-4.5 3-4.5-1.3-4.5-3'
    : FILES.has(change) ? 'M14 3H6v18h12V7l-4-4Zm0 0v4h4'
    : INVENTORY.has(change) ? 'M3 7l9-4 9 4-9 4-9-4Zm0 0v10l9 4 9-4V7M12 11v10'
    : 'M8 3v3m8-3v3M4 8h16M5 5h14v15H5V5Z';
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>;
}

function ago(at: number, now: number) {
  const minutes = Math.floor((now - at) / 60000);
  return minutes < 1 ? 'Just now' : minutes < 60 ? `${minutes} min ago` : new Date(at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

/** Messenger-style bubbles in the bottom-left corner, newest first: each opens to say what changed, and closes. */
export default function CustomerChangeBubbles({ items, repPage, onDismiss, onClear }: { items: MoveChange[]; repPage: boolean; onDismiss: (id: string) => void; onClear: () => void }) {
  const [open, setOpen] = useState('');
  const [seen, setSeen] = useState<Set<string>>(() => new Set());
  const [now, setNow] = useState(() => Date.now());
  // The times read "Just now" or "3 min ago" when a bubble is opened.
  useEffect(() => { if (open) setNow(Date.now()); }, [open]);
  const shown = items.filter(item => describeChange(item, repPage));
  if (!shown.length) return null;
  const openItem = shown.find(item => item.id === open);
  const toggle = (id: string) => {
    setOpen(current => current === id ? '' : id);
    setSeen(current => new Set(current).add(id));
  };
  return <aside className="cm-change-bubbles" aria-label="Updates to this move">
    <p className="cm-change-live" aria-live="polite">{describeChange(shown[0], repPage)}</p>
    {openItem && <div className="cm-change-card" role="dialog" aria-label="Update">
      <p>{describeChange(openItem, repPage)}</p>
      <small>{ago(openItem.at, now)}</small>
      <div className="cm-change-card-actions">
        {shown.length > 1 && <button type="button" onClick={() => { setOpen(''); onClear(); }}>Clear all</button>}
        <button type="button" onClick={() => { setOpen(''); onDismiss(openItem.id); }}>Close</button>
      </div>
    </div>}
    <ul>
      {shown.slice(0, SHOWN).map(item => <li key={item.id}>
        <button type="button" className={`cm-change-bubble${item.id === open ? ' is-open' : ''}`} aria-expanded={item.id === open}
          aria-label={describeChange(item, repPage)} title={describeChange(item, repPage)} onClick={() => toggle(item.id)}>
          <ChangeIcon change={item.change} />
          {!seen.has(item.id) && <span className="cm-change-unread" aria-hidden="true" />}
        </button>
      </li>)}
      {shown.length > SHOWN && <li className="cm-change-more">{`+${shown.length - SHOWN}`}</li>}
    </ul>
  </aside>;
}
