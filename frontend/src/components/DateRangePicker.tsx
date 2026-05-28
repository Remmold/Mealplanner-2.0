/**
 * Month calendar with two-tap range selection.
 *
 *   1. Click a day  -> sets start = end = that day; switches mode to "picking end".
 *   2. Click again  -> sets end (or, if clicked before start, swaps so the
 *                      earlier date becomes start). Mode resets to "picking start".
 *   3. Beyond max-days the end is clamped silently.
 *
 * No external dep, no popover. Designed to live inline inside step 1 of the
 * Plan-this-week wizard, but it's a self-contained component you could drop
 * anywhere with the same `start`/`end`/`onChange` contract.
 */

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { IconButton } from "./ui";

interface Props {
  start: string;          // ISO YYYY-MM-DD
  end: string;            // ISO YYYY-MM-DD
  onChange: (start: string, end: string) => void;
  maxDays?: number;       // inclusive; default 14
}

const DOW_LABELS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
const MONTH_LABELS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function parse(iso: string): Date {
  return new Date(iso + "T00:00:00");
}

function toIso(d: Date): string {
  const y = d.getFullYear();
  const m = (d.getMonth() + 1).toString().padStart(2, "0");
  const day = d.getDate().toString().padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDaysIso(iso: string, n: number): string {
  const d = parse(iso);
  d.setDate(d.getDate() + n);
  return toIso(d);
}

function diffDays(a: string, b: string): number {
  return Math.floor((parse(b).getTime() - parse(a).getTime()) / 86_400_000) + 1;
}

export default function DateRangePicker({ start, end, onChange, maxDays = 14 }: Props) {
  const startD = parse(start);
  const [viewYear, setViewYear] = useState(startD.getFullYear());
  const [viewMonth, setViewMonth] = useState(startD.getMonth());
  const [pickingEnd, setPickingEnd] = useState(false);

  const todayIso = useMemo(() => toIso(new Date()), []);

  // 6×7 grid of dates anchored on viewYear/viewMonth. Cells outside the
  // current month spill over from the neighbouring months (rendered dim).
  const cells = useMemo(() => {
    const firstOfMonth = new Date(viewYear, viewMonth, 1);
    // 0 = Monday in our Monday-first display
    const firstDow = (firstOfMonth.getDay() + 6) % 7;
    const gridStart = new Date(viewYear, viewMonth, 1 - firstDow);
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(gridStart);
      d.setDate(gridStart.getDate() + i);
      return d;
    });
  }, [viewYear, viewMonth]);

  function prevMonth() {
    if (viewMonth === 0) { setViewMonth(11); setViewYear((y) => y - 1); }
    else setViewMonth((m) => m - 1);
  }

  function nextMonth() {
    if (viewMonth === 11) { setViewMonth(0); setViewYear((y) => y + 1); }
    else setViewMonth((m) => m + 1);
  }

  function clickDay(d: Date) {
    const iso = toIso(d);
    if (!pickingEnd) {
      onChange(iso, iso);
      setPickingEnd(true);
      return;
    }
    // Picking the end.
    if (iso < start) {
      // Clicked before the current start: extend the range backwards.
      onChange(iso, start);
    } else {
      const days = diffDays(start, iso);
      if (days > maxDays) {
        // Clamp to max — don't let the user create a range the server rejects.
        onChange(start, addDaysIso(start, maxDays - 1));
      } else {
        onChange(start, iso);
      }
    }
    setPickingEnd(false);
  }

  function classFor(d: Date): string {
    const iso = toIso(d);
    const inMonth = d.getMonth() === viewMonth;
    const inRange = iso >= start && iso <= end;
    const isStart = iso === start;
    const isEnd = iso === end;
    const isToday = iso === todayIso;
    return [
      "drp-day",
      !inMonth && "drp-day-outside",
      isToday && "drp-day-today",
      inRange && "drp-day-in-range",
      isStart && "drp-day-start",
      isEnd && "drp-day-end",
      isStart && isEnd && "drp-day-single",
    ].filter(Boolean).join(" ");
  }

  return (
    <div className="drp">
      <div className="drp-header">
        <IconButton onClick={prevMonth} aria-label="Previous month" title="Previous month">
          <ChevronLeft size={16} />
        </IconButton>
        <span className="drp-month-label">
          {MONTH_LABELS[viewMonth]} {viewYear}
        </span>
        <IconButton onClick={nextMonth} aria-label="Next month" title="Next month">
          <ChevronRight size={16} />
        </IconButton>
      </div>

      <div className="drp-grid" role="grid">
        {DOW_LABELS.map((dl) => (
          <div key={dl} className="drp-dow">{dl}</div>
        ))}
        {cells.map((d) => (
          <button
            key={d.getTime()}
            type="button"
            className={classFor(d)}
            onClick={() => clickDay(d)}
          >
            {d.getDate()}
          </button>
        ))}
      </div>

      <div className="drp-hint">
        {pickingEnd
          ? "Pick the end date — click before the start to extend backwards."
          : "Click a date to start. Click again to set the end."}
      </div>
    </div>
  );
}
