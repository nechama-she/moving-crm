import { useEffect, useState } from 'react';
import './CustomerChangeBubbles.css';

/** A change another open page of this move saved, as it arrived: by the customer or the team, with the customer's name
 *  or the lead's rep's name (blank when unknown). */
export type MoveChange = { id: string; change: string; by: 'customer' | 'team'; name: string; at: number };

// The signature changes shown as bubbles, and what each did, after who did it ("The customer signed the estimate").
const WHAT: Record<string, string> = {
  estimate_signed: 'signed the estimate',
  estimate_signature_cancelled: 'cancelled the estimate signature',
  estimate_approved: 'made the estimate ready to sign',
  bill_of_lading_signed: 'signed the Bill of Lading',
};
export const SIGNATURE_CHANGES = new Set(Object.keys(WHAT));
const SHOWN = 6;

export function describeChange(item: MoveChange, repPage: boolean) {
  const what = WHAT[item.change];
  if (!what) return '';
  if (item.by === 'team') return `${item.name || (repPage ? 'Your team' : 'Your moving team')} ${what}`;
  return repPage ? `${item.name || 'The customer'} ${what}` : `You ${what} on another device`;
}

function SignatureIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 21h18M5 17l9.5-9.5 3 3L8 20H5v-3Zm11-11 2-2 3 3-2 2" /></svg>;
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
          <SignatureIcon />
          {!seen.has(item.id) && <span className="cm-change-unread" aria-hidden="true" />}
        </button>
      </li>)}
      {shown.length > SHOWN && <li className="cm-change-more">{`+${shown.length - SHOWN}`}</li>}
    </ul>
  </aside>;
}
