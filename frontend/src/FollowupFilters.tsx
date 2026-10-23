import './FollowupFilters.css';

export const localDate = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const priorities = [
  ['all', 'All priorities'], ['0', 'New lead - not yet contacted'],
  ['1', 'Estimate sent - likely to book'], ['2', 'Estimate sent - unlikely to book'],
  ['3', 'Contacted - estimate not yet sent'], ['4', 'Priority 4'],
  ['5', 'Home for sale - awaiting contract'], ['6', 'Unqualified lead'], ['none', 'No priority assigned'],
];

export default function FollowupFilters({ priority, from, to, onPriority, onDates }: {
  priority: string; from: string; to: string; onPriority: (value: string) => void;
  onDates: (from: string, to: string) => void;
}) {
  function shortcut(offset: number, length = 1) {
    const start = new Date(); start.setDate(start.getDate() + offset);
    const end = new Date(start); end.setDate(end.getDate() + length - 1);
    onDates(localDate(start), localDate(end));
  }
  return <div className="followup-filters">
    <div className="followup-priorities" role="group" aria-label="Priority">
      {priorities.map(([value, label]) => <button key={value} type="button" className="slds-button" aria-pressed={priority === value} title={label} onClick={() => onPriority(value)}>
        <span className="followup-priority-title">{value === 'all' ? 'All priorities' : value === 'none' ? 'No priority' : `Priority ${value}`}</span>
        {value !== 'all' && value !== '4' && <span className="followup-priority-label">{label}</span>}
      </button>)}
    </div>
    <div className="followup-calendar">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18"/></svg>
      <label>From<input type="date" value={from} onChange={e => {if(e.target.value) onDates(e.target.value, e.target.value > to ? e.target.value : to);}} /></label>
      <label>Through<input type="date" value={to} min={from} onChange={e => {if(e.target.value >= from) onDates(from, e.target.value);}} /></label>
      <div className="followup-date-shortcuts">
        <button type="button" className="slds-button" onClick={() => shortcut(-1)}>Yesterday</button>
        <button type="button" className="slds-button" onClick={() => shortcut(0)}>Today</button>
        <button type="button" className="slds-button" onClick={() => shortcut(1)}>Tomorrow</button>
        <button type="button" className="slds-button" onClick={() => shortcut(0, 7)}>Next 7 days</button>
      </div>
    </div>
  </div>;
}
