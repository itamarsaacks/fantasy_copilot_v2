"use client";

/**
 * Standard date toggle used by Games, League, My Team tabs.
 * `[<] [Mon, Mar 22 ▾] [>]` with the middle button opening a popover
 * with the last-7 quick-pick list per master plan §3.
 *
 * Stateless: parent owns the selected date and the onChange handler.
 *
 * Mobile-friendly: touch targets are 40px+, hit areas extend beyond
 * the visible glyph.
 */
import { useState } from "react";

import {
  addDays,
  formatDateHeadline,
  isFutureDate,
  lastNDays,
  toISODate,
} from "@/lib/date-utils";

export interface DateToggleProps {
  value: Date;
  onChange: (next: Date) => void;
  /** If set, disable forward navigation past this date. */
  maxDate?: Date;
  /** If set, disable backward navigation before this date. */
  minDate?: Date;
  className?: string;
}

export function DateToggle({
  value,
  onChange,
  maxDate,
  minDate,
  className = "",
}: DateToggleProps) {
  const [open, setOpen] = useState(false);

  const canGoBack = !minDate || toISODate(addDays(value, -1)) >= toISODate(minDate);
  const canGoFwd = !maxDate || toISODate(addDays(value, 1)) <= toISODate(maxDate);

  return (
    <div className={`relative inline-flex items-center gap-1 ${className}`}>
      <button
        type="button"
        onClick={() => onChange(addDays(value, -1))}
        disabled={!canGoBack}
        className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-30 disabled:hover:bg-transparent"
        aria-label="Previous day"
      >
        ‹
      </button>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex h-10 min-w-[140px] items-center justify-center gap-1.5 rounded-md border border-slate-200 px-3 text-sm font-medium text-slate-800 hover:bg-slate-50"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {formatDateHeadline(value)}
        <span aria-hidden className="text-xs text-slate-500">
          ▾
        </span>
      </button>
      <button
        type="button"
        onClick={() => onChange(addDays(value, 1))}
        disabled={!canGoFwd}
        className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-30 disabled:hover:bg-transparent"
        aria-label="Next day"
      >
        ›
      </button>
      {open && (
        <div
          className="absolute top-12 left-1/2 z-30 -translate-x-1/2 rounded-md border border-slate-200 bg-white p-1 shadow-lg"
          role="listbox"
        >
          {lastNDays(7).map((d) => {
            const isSelected = toISODate(d) === toISODate(value);
            return (
              <button
                key={d.toISOString()}
                type="button"
                onClick={() => {
                  onChange(d);
                  setOpen(false);
                }}
                disabled={isFutureDate(d, maxDate ?? new Date())}
                className={`block w-44 rounded px-3 py-2 text-left text-sm hover:bg-slate-100 ${
                  isSelected ? "bg-sky-50 font-semibold text-sky-700" : ""
                }`}
              >
                {formatDateHeadline(d)}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
