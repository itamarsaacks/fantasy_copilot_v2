"use client";

/**
 * Multi-select calendar — pick specific calendar dates (used by the
 * Waiver Planner sub-tab per master plan §3 / §6 Tab 6).
 *
 * Minimal MVP shape: month view, click to toggle selection, header with
 * prev/next month buttons. Returns `Date[]`.
 *
 * Future polish (in the Trades+Waiver tab session): drag-to-select range,
 * "select all weekdays this week" shortcuts, keyboard navigation.
 */
import { useMemo, useState } from "react";

import { addDays, formatDateHeadline, isSameDay, toISODate } from "@/lib/date-utils";

export interface CalendarMultiPickerProps {
  value: Date[];
  onChange: (next: Date[]) => void;
  minDate?: Date;
  maxDate?: Date;
  className?: string;
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function daysInMonthGrid(monthStart: Date): Date[] {
  // 6 rows × 7 days, padded with prior-month days for the first week.
  const startDayOfWeek = monthStart.getDay(); // 0 = Sun
  const gridStart = addDays(monthStart, -startDayOfWeek);
  return Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
}

export function CalendarMultiPicker({
  value,
  onChange,
  minDate,
  maxDate,
  className = "",
}: CalendarMultiPickerProps) {
  const [viewMonth, setViewMonth] = useState<Date>(startOfMonth(new Date()));
  const grid = useMemo(() => daysInMonthGrid(viewMonth), [viewMonth]);

  const selectedKeys = useMemo(
    () => new Set(value.map(toISODate)),
    [value]
  );

  const toggle = (d: Date) => {
    const key = toISODate(d);
    if (selectedKeys.has(key)) {
      onChange(value.filter((x) => toISODate(x) !== key));
    } else {
      onChange([...value, d].sort((a, b) => toISODate(a).localeCompare(toISODate(b))));
    }
  };

  const monthLabel = viewMonth.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });

  return (
    <div className={`inline-block rounded-md border border-slate-200 p-3 ${className}`}>
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          onClick={() =>
            setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() - 1, 1))
          }
          className="h-8 w-8 rounded hover:bg-slate-100"
          aria-label="Previous month"
        >
          ‹
        </button>
        <div className="text-sm font-medium">{monthLabel}</div>
        <button
          type="button"
          onClick={() =>
            setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 1))
          }
          className="h-8 w-8 rounded hover:bg-slate-100"
          aria-label="Next month"
        >
          ›
        </button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center text-xs text-slate-500">
        {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
          <div key={i} className="py-1">
            {d}
          </div>
        ))}
        {grid.map((d) => {
          const key = toISODate(d);
          const selected = selectedKeys.has(key);
          const outOfMonth = d.getMonth() !== viewMonth.getMonth();
          const tooEarly = minDate && toISODate(d) < toISODate(minDate);
          const tooLate = maxDate && toISODate(d) > toISODate(maxDate);
          const disabled = tooEarly || tooLate;
          return (
            <button
              key={key}
              type="button"
              onClick={() => !disabled && toggle(d)}
              disabled={disabled}
              className={`h-9 w-9 rounded text-sm transition-colors ${
                selected
                  ? "bg-sky-600 font-semibold text-white"
                  : outOfMonth
                  ? "text-slate-300 hover:bg-slate-50"
                  : "text-slate-700 hover:bg-slate-100"
              } disabled:cursor-not-allowed disabled:opacity-30`}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>
      {value.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-600">
          {value.length} date{value.length === 1 ? "" : "s"} selected:{" "}
          {value.map(formatDateHeadline).join(", ")}
        </div>
      )}
    </div>
  );
}
