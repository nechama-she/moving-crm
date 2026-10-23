import './FollowupFilters.css';
import CalendarDateRange from './CalendarDateRange';

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
  return <div className="followup-filters">
    <div className="followup-priorities" role="group" aria-label="Priority">
      {priorities.map(([value, label]) => <button key={value} type="button" className="slds-button" aria-pressed={priority === value} title={label} onClick={() => onPriority(value)}>
        <span className="followup-priority-title">{value === 'all' ? 'All priorities' : value === 'none' ? 'No priority' : `Priority ${value}`}</span>
        {value !== 'all' && value !== '4' && <span className="followup-priority-label">{label}</span>}
      </button>)}
    </div>
    <CalendarDateRange key={`${from}:${to}`} value={{ from, to }} month={new Date(`${from}T00:00:00`)} onChange={range => {
      if (range) onDates(range.from, range.to);
      else {
        const month = new Date(`${from}T00:00:00`);
        onDates(localDate(new Date(month.getFullYear(), month.getMonth(), 1)), localDate(new Date(month.getFullYear(), month.getMonth() + 1, 0)));
      }
    }} />
  </div>;
}
