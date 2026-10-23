import './FollowupFilters.css';
import ReportControls from './ReportControls';
import './ReportsPage.css';
import { useState } from 'react';

export const localDate = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const priorities = [
  ['all', 'All priorities'], ['0', 'New lead - not yet contacted'],
  ['1', 'Estimate sent - likely to book'], ['2', 'Estimate sent - unlikely to book'],
  ['3', 'Contacted - estimate not yet sent'], ['4', 'Online estimate - no calls'],
  ['5', 'Home for sale - awaiting contract'], ['6', 'Unqualified lead'], ['none', 'No priority assigned'],
];

export default function FollowupFilters({ priority, from, to, onPriority, onDates, counts, loading, datesOnly = false }: {
  datesOnly?: boolean;
  counts: Record<string, number>; loading: boolean;
  priority: string; from: string; to: string; onPriority: (value: string) => void;
  onDates: (from: string, to: string) => void;
}) {
  const [rangeLabel, setRangeLabel] = useState('');
  const displayDate = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  const label = rangeLabel || (from === localDate() && to === from ? 'Today' : from === to ? displayDate(from) : `${displayDate(from)} - ${displayDate(to)}`);
  return <div className={datesOnly ? 'followup-date-toolbar' : 'followup-filters'}>
    {!datesOnly && <div className="followup-priorities" role="group" aria-label="Priority">
      {priorities.map(([value, label]) => <button key={value} type="button" className="slds-button" aria-pressed={priority === value} title={label} onClick={() => onPriority(value)}>
        <span className="followup-priority-title">{value === 'all' ? 'All priorities' : value === 'none' ? 'No priority' : `Priority ${value}`}<span className="followup-priority-count" aria-label={loading ? 'Loading count' : `${counts[value] || 0} leads`}>{loading ? '...' : (counts[value] || 0).toLocaleString()}</span></span>
        {value !== 'all' && <span className="followup-priority-label">{label}</span>}
      </button>)}
    </div>}
    {datesOnly && <div className="reports-page followup-date-control" style={{ padding: 0, margin: 0, maxWidth: 'none' }}>
      <ReportControls datesOnly range={{ start: from, end: to, label }} companies={[]} reps={[]} options={{ companies: [], reps: [] }} onApply={range => {
        setRangeLabel(range.label === 'Custom range' ? '' : range.label);
        onDates(range.start, range.end);
      }} />
    </div>}
  </div>;
}
