import { useId, useState } from "react";
import "./CalendarDateRange.css";
import { rangeDays } from "./aurora/dateRange";
import { getUiMode } from "./aurora/uiMode";

type Range = { from: string; to: string };
const dateKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const displayDate = (value: string) => new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

export default function CalendarDateRange({ value, month, onChange }: {
  value: Range | null;
  month: Date;
  onChange: (value: Range | null) => void;
}) {
  const id = useId();
  // The new look replaces the browser's date fields with this calendar, applied as soon as a range is picked.
  const aurora = getUiMode() === "aurora";
  const [draft, setDraft] = useState<Range>(() => value || {
    from: dateKey(new Date(month.getFullYear(), month.getMonth(), 1)),
    to: dateKey(new Date(month.getFullYear(), month.getMonth() + 1, 0)),
  });
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [pickerMonth, setPickerMonth] = useState(() => new Date(`${(value?.from || dateKey(month)).slice(0, 7)}-01T00:00:00`));
  const [anchor, setAnchor] = useState<string | null>(null);
  const [hoverDate, setHoverDate] = useState<string | null>(null);
  const preview = anchor ? { from: anchor < (hoverDate || anchor) ? anchor : (hoverDate || anchor), to: anchor > (hoverDate || anchor) ? anchor : (hoverDate || anchor) } : draft;
  function selectDate(day: string) {
    if (!anchor) {
      setAnchor(day);
      setHoverDate(null);
    } else {
      const next = { from: day < anchor ? day : anchor, to: day > anchor ? day : anchor };
      setDraft(next);
      setAnchor(null);
      setHoverDate(null);
      if (aurora) {
        onChange(next);
        setCalendarOpen(false);
      }
    }
  }
  const invalid = Boolean(draft.from && draft.to && draft.to < draft.from);
  const unchanged = value?.from === draft.from && value?.to === draft.to;
  function presetRange(days: number) {
    const start = new Date();
    const end = new Date(start);
    end.setDate(end.getDate() + days - 1);
    return { from: dateKey(start), to: dateKey(end) };
  }
  function preset(days: number) {
    const next = presetRange(days);
    setDraft(next);
    onChange(next);
  }
  // The new look also marks Today / Next 7 days while they are the active range.
  const presetActive = (days: number) => aurora && value?.from === presetRange(days).from && value?.to === presetRange(days).to;
  return <section className="calendar-range" aria-label="Calendar date filter">
    <div className="calendar-range-heading">
      <span className="calendar-range-icon" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 4h3m2 0h3"/></svg></span>
      <div><h2>Date range</h2><p aria-live="polite">{value ? `${displayDate(value.from)} – ${displayDate(value.to)}` : month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</p></div>
    </div>
    <div className="calendar-range-presets" aria-label="Quick dates">
      <button type="button" aria-expanded={calendarOpen} aria-controls={`${id}-calendar`} onClick={() => { setCalendarOpen(!calendarOpen); setAnchor(null); setHoverDate(null); }}>Select on calendar</button>
      <button type="button" className={presetActive(1) ? "is-selected" : ""} aria-pressed={aurora ? presetActive(1) : undefined} onClick={() => preset(1)}>Today</button>
      <button type="button" className={presetActive(7) ? "is-selected" : ""} aria-pressed={aurora ? presetActive(7) : undefined} onClick={() => preset(7)}>Next 7 days</button>
      <button type="button" className={!value ? "is-selected" : ""} aria-pressed={!value} onClick={() => {
        setDraft({ from: dateKey(new Date(month.getFullYear(), month.getMonth(), 1)), to: dateKey(new Date(month.getFullYear(), month.getMonth() + 1, 0)) });
        onChange(null);
      }}>Full month</button>
    </div>
    {calendarOpen ? <div className="calendar-range-picker" id={`${id}-calendar`}>
      <div className="calendar-range-picker-nav">
        <button type="button" aria-label="Previous month" onClick={() => setPickerMonth(new Date(pickerMonth.getFullYear(), pickerMonth.getMonth() - 1, 1))}><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m15 6-6 6 6 6"/></svg></button>
        <strong aria-live="polite">{pickerMonth.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</strong>
        <button type="button" aria-label="Next month" onClick={() => setPickerMonth(new Date(pickerMonth.getFullYear(), pickerMonth.getMonth() + 1, 1))}><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m9 6 6 6-6 6"/></svg></button>
      </div>
      <p className="calendar-range-picker-help" aria-live="polite">{anchor ? `Start: ${displayDate(anchor)}. Choose the end date.` : aurora ? "Choose a start date, then an end date." : "Choose a start date, then an end date. Apply dates to update the results."}</p>
      <div className="calendar-range-days" onMouseLeave={() => setHoverDate(null)}>
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(day => <span className="calendar-range-weekday" key={day}>{day}</span>)}
        {Array.from({ length: pickerMonth.getDay() }, (_, index) => <span key={`blank-${index}`} />)}
        {Array.from({ length: new Date(pickerMonth.getFullYear(), pickerMonth.getMonth() + 1, 0).getDate() }, (_, index) => {
          const day = dateKey(new Date(pickerMonth.getFullYear(), pickerMonth.getMonth(), index + 1));
          const selected = day >= preview.from && day <= preview.to;
          const edge = day === preview.from || day === preview.to;
          return <button type="button" key={day} className={`${selected ? "in-range" : ""} ${edge ? "range-edge" : ""}`} aria-label={displayDate(day)} aria-pressed={selected} aria-current={day === dateKey(new Date()) ? "date" : undefined} onMouseEnter={() => { if (anchor) setHoverDate(day); }} onClick={() => selectDate(day)}>{index + 1}</button>;
        })}
      </div>
    </div> : null}
    {aurora ? <div className="calendar-range-form aur-range-fields">
      {(["from", "to"] as const).map(edge => <button key={edge} type="button" className="aur-range-field" aria-expanded={calendarOpen} aria-controls={`${id}-calendar`} onClick={() => {
        setCalendarOpen(!calendarOpen);
        setAnchor(null);
        setHoverDate(null);
        setPickerMonth(new Date(`${draft[edge].slice(0, 7)}-01T00:00:00`));
      }}>
        <span>{edge === "from" ? "Start date" : "End date"}</span>
        <strong>{displayDate(draft[edge])}</strong>
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18"/></svg>
      </button>)}
    </div> : <form className="calendar-range-form" onSubmit={event => {
      event.preventDefault();
      if (draft.from && draft.to && !invalid && !anchor) onChange(draft);
    }}>
      <label htmlFor={`${id}-from`}>Start date<input id={`${id}-from`} type="date" required value={draft.from} onChange={event => setDraft({ ...draft, from: event.target.value })} /></label>
      <label htmlFor={`${id}-to`}>End date<input id={`${id}-to`} type="date" required min={draft.from || undefined} value={draft.to} aria-invalid={invalid} aria-describedby={invalid ? `${id}-error` : undefined} onChange={event => setDraft({ ...draft, to: event.target.value })} /></label>
      <button className="calendar-range-apply" type="submit" disabled={!draft.from || !draft.to || invalid || unchanged || Boolean(anchor)}>Apply dates<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14m-6-6 6 6-6 6"/></svg></button>
    </form>}
    {invalid ? <p className="calendar-range-error" id={`${id}-error`} role="alert">End date must be on or after start date.</p> : value && !(aurora && rangeDays(value)) ? <p className="calendar-range-hint">Totals include the entire range. Browse months below to see each day's jobs.</p> : null}
  </section>;
}
