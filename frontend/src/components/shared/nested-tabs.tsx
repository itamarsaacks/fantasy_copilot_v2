"use client";

/**
 * Generic nested-tabs pattern for sub-tabs inside a top-level tab.
 * Used by Games (scores / standings), Trades+Waiver (trades / planner),
 * Players (analytics / compare / leaders / timeline / EOS) per master plan §3.
 *
 * Controlled (parent owns active tab). URL syncing left to the parent —
 * this is a presentation primitive only.
 */
import { ReactNode } from "react";

export interface NestedTabItem {
  id: string;
  label: string;
  icon?: ReactNode;
  count?: number; // optional badge ("23 candidates")
}

export interface NestedTabsProps {
  items: NestedTabItem[];
  activeId: string;
  onChange: (id: string) => void;
  className?: string;
}

export function NestedTabs({ items, activeId, onChange, className = "" }: NestedTabsProps) {
  return (
    <div
      className={`flex items-center gap-1 border-b border-slate-200 ${className}`}
      role="tablist"
    >
      {items.map((item) => {
        const active = item.id === activeId;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.id)}
            className={`relative inline-flex items-center gap-1.5 px-4 py-2 text-sm transition-colors ${
              active
                ? "border-b-2 border-sky-600 font-semibold text-sky-700 -mb-px"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            {item.icon}
            <span>{item.label}</span>
            {item.count !== undefined && (
              <span
                className={`ml-1 rounded-full px-2 py-0.5 text-xs ${
                  active ? "bg-sky-100 text-sky-700" : "bg-slate-100 text-slate-600"
                }`}
              >
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
