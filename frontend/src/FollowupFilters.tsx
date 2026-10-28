import './FollowupFilters.css';
import ReportControls from './ReportControls';
import './ReportsPage.css';
import { useState } from 'react';
import { PRIORITY_LABELS } from './leadUtils';

export const localDate = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const priorities = [
  ['all', 'All priorities'], ...Object.entries(PRIORITY_LABELS), ['none', 'No priority assigned'],
];

export default function FollowupFilters({ priority, from, to, onPriority, onDates, counts, loading, datesOnly = false }: {
  datesOnly?: boolean;
  counts: Record<string, number>; loading: boolean;
  priority: string; from: string; to: string; onPriority: (value: string) => void;
  onDates: (from: string, to: string) => void;
}) {
  const [rangeLabel, setRangeLabel] = useState('');
  // `priority` is "all" or a comma-separated selection such as "1,3,none".
  const selected = new Set(priority === 'all' ? [] : priority.split(',').filter(Boolean));
  const toggle = (value: string) => {
    if (value === 'all') return onPriority('all');
    const next = new Set(selected);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    const ordered = priorities.map(([option]) => option).filter(option => next.has(option));
    onPriority(ordered.length ? ordered.join(',') : 'all');
  };
  const isPressed = (value: string) => value === 'all' ? selected.size === 0 : selected.has(value);
  const displayDate = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  const label = rangeLabel || (from === localDate() && to === from ? 'Today' : from === to ? displayDate(from) : `${displayDate(from)} - ${displayDate(to)}`);
  return <div className={datesOnly ? 'followup-date-toolbar' : 'followup-filters'}>
    {!datesOnly && <div className="followup-priorities" role="group" aria-label="Priority (pick one or more)">
      {priorities.map(([value, label]) => <button key={value} type="button" className="slds-button" aria-pressed={isPressed(value)} title={value === 'all' ? 'Show every priority' : `${label} - click to add or remove`} onClick={() => toggle(value)}>
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
