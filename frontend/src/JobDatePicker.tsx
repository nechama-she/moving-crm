import { useEffect, useRef, useState } from "react";
import "./JobDatePicker.css";

interface JobDatePickerProps {
  value: string; // ISO format "YYYY-MM-DD" or ""
  onChange: (dateStr: string) => void;
  disabled?: boolean;
  type?: "move" | "booked";
  placeholder?: string;
  alignRight?: boolean;
}

const formatDisplay = (isoStr: string): string => {
  if (!isoStr) return "";
  const parts = isoStr.trim().split("-");
  if (parts.length === 3 && parts[0].length === 4) {
    return `${parts[1]}/${parts[2]}/${parts[0]}`;
  }
  return isoStr;
};

const toIso = (d: Date): string => {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const parseIso = (isoStr: string): Date => {
  if (!isoStr) return new Date();
  const parts = isoStr.split("-").map(Number);
  if (parts.length === 3 && !isNaN(parts[0]) && !isNaN(parts[1]) && !isNaN(parts[2])) {
    return new Date(parts[0], parts[1] - 1, parts[2], 12, 0, 0);
  }
  return new Date();
};

const formatFullLabel = (isoStr: string): string => {
  if (!isoStr) return "No date selected";
  const d = parseIso(isoStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

export default function JobDatePicker({
  value,
  onChange,
  disabled = false,
  type = "move",
  placeholder = "mm/dd/yyyy",
  alignRight = false,
}: JobDatePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState(value || "");
  const [viewDate, setViewDate] = useState<Date>(() => parseIso(value));
  const containerRef = useRef<HTMLDivElement>(null);

  // Sync state when external value changes or dropdown opens
  useEffect(() => {
    setSelectedDate(value || "");
    if (value) {
      setViewDate(parseIso(value));
    }
  }, [value, isOpen]);

  // Close when clicking outside
  useEffect(() => {
    if (!isOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const year = viewDate.getFullYear();
  const monthIndex = viewDate.getMonth();
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const firstDayOffset = new Date(year, monthIndex, 1).getDay();

  const prevMonth = () => {
    setViewDate(new Date(year, monthIndex - 1, 1, 12, 0, 0));
  };

  const nextMonth = () => {
    setViewDate(new Date(year, monthIndex + 1, 1, 12, 0, 0));
  };

  const handleDaySelect = (dayNum: number) => {
    const next = new Date(year, monthIndex, dayNum, 12, 0, 0);
    const nextIso = toIso(next);
    setSelectedDate(nextIso);
  };

  const handleApply = () => {
    onChange(selectedDate);
    setIsOpen(false);
  };

  const handleClear = () => {
    setSelectedDate("");
    onChange("");
    setIsOpen(false);
  };

  // Presets tailored to move date vs booked date
  const now = new Date();
  const todayIso = toIso(now);

  const getPresets = () => {
    const y = now.getFullYear();
    const m = now.getMonth();
    const d = now.getDate();

    if (type === "booked") {
      const yesterday = new Date(y, m, d - 1, 12, 0, 0);
      const twoDaysAgo = new Date(y, m, d - 2, 12, 0, 0);
      const lastWeek = new Date(y, m, d - 7, 12, 0, 0);
      const lastMonth = new Date(y, m - 1, d, 12, 0, 0);
      return [
        { label: "Today", iso: todayIso },
        { label: "Yesterday", iso: toIso(yesterday) },
        { label: "2 Days Ago", iso: toIso(twoDaysAgo) },
        { label: "Last Week", iso: toIso(lastWeek) },
        { label: "Last Month", iso: toIso(lastMonth) },
      ];
    } else {
      const tomorrow = new Date(y, m, d + 1, 12, 0, 0);
      // Next Saturday
      const daysToSat = (6 - now.getDay() + 7) % 7 || 7;
      const thisWeekend = new Date(y, m, d + daysToSat, 12, 0, 0);
      const nextWeek = new Date(y, m, d + 7, 12, 0, 0);
      const inTwoWeeks = new Date(y, m, d + 14, 12, 0, 0);
      const nextMonth = new Date(y, m + 1, d, 12, 0, 0);
      return [
        { label: "Today", iso: todayIso },
        { label: "Tomorrow", iso: toIso(tomorrow) },
        { label: "This Weekend", iso: toIso(thisWeekend) },
        { label: "Next Week", iso: toIso(nextWeek) },
        { label: "In 2 Weeks", iso: toIso(inTwoWeeks) },
        { label: "Next Month", iso: toIso(nextMonth) },
      ];
    }
  };

  const presets = getPresets();

  const monthYearString = viewDate.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });

  return (
    <div className="job-date-picker" ref={containerRef}>
      <button
        type="button"
        disabled={disabled}
        className={`job-date-picker-trigger ${value ? "has-value" : ""} ${isOpen ? "is-open" : ""}`}
        onClick={() => setIsOpen((prev) => !prev)}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
      >
        <span className={value ? "job-date-value" : "job-date-placeholder"}>
          {value ? formatDisplay(value) : placeholder}
        </span>
        <svg className="job-date-trigger-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <rect x="3" y="4" width="18" height="18" rx="2" />
          <path d="M16 2v4M8 2v4M3 10h18" />
        </svg>
      </button>

      {isOpen && (
        <div
          className={`job-date-calendar-popover ${alignRight ? "align-right" : ""}`}
          role="dialog"
          aria-label="Choose date"
        >
          <div className="job-date-presets">
            <span className="job-date-presets-title">Quick Select</span>
            {presets.map((preset) => {
              const isSelected = selectedDate === preset.iso;
              return (
                <button
                  type="button"
                  key={preset.label}
                  className={`job-date-preset-btn ${isSelected ? "selected" : ""}`}
                  onClick={() => {
                    setSelectedDate(preset.iso);
                    setViewDate(parseIso(preset.iso));
                  }}
                >
                  {preset.label}
                </button>
              );
            })}
            <button
              type="button"
              className="job-date-preset-btn clear-btn"
              onClick={handleClear}
            >
              Clear Date
            </button>
          </div>

          <div className="job-date-main">
            <div className="job-date-month-nav">
              <button
                type="button"
                className="job-date-nav-arrow"
                onClick={prevMonth}
                aria-label="Previous month"
              >
                &lsaquo;
              </button>
              <div className="job-date-month-display">
                <span>{monthYearString}</span>
                <input
                  type="month"
                  className="job-date-month-native-picker"
                  aria-label="Jump to month and year"
                  value={`${year}-${String(monthIndex + 1).padStart(2, "0")}`}
                  onChange={(e) => {
                    if (e.target.value) {
                      const [y, m] = e.target.value.split("-").map(Number);
                      setViewDate(new Date(y, m - 1, 1, 12, 0, 0));
                    }
                  }}
                />
              </div>
              <button
                type="button"
                className="job-date-nav-arrow"
                onClick={nextMonth}
                aria-label="Next month"
              >
                &rsaquo;
              </button>
            </div>

            <div className="job-date-grid">
              {["S", "M", "T", "W", "T", "F", "S"].map((dayName, idx) => (
                <span key={`header-${idx}`} className="job-date-col-header">
                  {dayName}
                </span>
              ))}
              {Array.from({ length: firstDayOffset }, (_, idx) => (
                <span key={`offset-${idx}`} className="job-date-empty-cell" />
              ))}
              {Array.from({ length: daysInMonth }, (_, idx) => {
                const dayNum = idx + 1;
                const dateIso = toIso(new Date(year, monthIndex, dayNum, 12, 0, 0));
                const isSelected = selectedDate === dateIso;
                const isToday = dateIso === todayIso;

                return (
                  <button
                    type="button"
                    key={`day-${dayNum}`}
                    className={`job-date-day-btn ${isSelected ? "selected" : ""} ${isToday ? "today" : ""}`}
                    onClick={() => handleDaySelect(dayNum)}
                  >
                    {dayNum}
                  </button>
                );
              })}
            </div>

            <p className="job-date-hint">Click a date, or choose a shortcut from the left.</p>

            <div className="job-date-footer">
              <small className="job-date-footer-label">{formatFullLabel(selectedDate)}</small>
              <div className="job-date-footer-actions">
                <button
                  type="button"
                  className="job-date-btn-secondary"
                  onClick={() => setIsOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="job-date-btn-primary"
                  onClick={handleApply}
                >
                  Apply
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
