"use client";

import { useMemo } from "react";
import type { OwnershipInterval } from "@/lib/api-types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Color palette — stable per team_id so the colors stay consistent across
// every player's timeline within the league.
// ---------------------------------------------------------------------------

const TEAM_PALETTE = [
  "bg-amber-500",
  "bg-rose-500",
  "bg-emerald-500",
  "bg-violet-500",
  "bg-sky-500",
  "bg-fuchsia-500",
  "bg-lime-500",
  "bg-cyan-500",
  "bg-orange-500",
  "bg-pink-500",
  "bg-teal-500",
  "bg-indigo-500",
];

const FREE_AGENT_BG = "bg-zinc-700/60";
const USER_TEAM_RING = "ring-2 ring-orange-300";

function teamColor(team_id: number | null): string {
  if (team_id === null) return FREE_AGENT_BG;
  return TEAM_PALETTE[team_id % TEAM_PALETTE.length];
}

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function parseISO(s: string): Date {
  return new Date(s);
}

function fmtShort(d: Date): string {
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function isoDay(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function HorizontalOwnershipTimeline({
  intervals,
  selectedRange,
  onPickRange,
}: {
  intervals: OwnershipInterval[];
  selectedRange?: { start: string; end: string } | null;
  onPickRange: (start: string, end: string) => void;
}) {
  // Compute timeline bounds.
  const { start, end, segs } = useMemo(() => {
    if (intervals.length === 0) {
      const now = new Date();
      return { start: now, end: now, segs: [] };
    }
    const startD = parseISO(intervals[0].started_at);
    const endD = (() => {
      const last = intervals[intervals.length - 1];
      return last.ended_at ? parseISO(last.ended_at) : new Date();
    })();
    const totalMs = Math.max(endD.getTime() - startD.getTime(), 1);
    const segs = intervals.map((iv, i) => {
      const s = parseISO(iv.started_at);
      const e = iv.ended_at ? parseISO(iv.ended_at) : new Date();
      const left = ((s.getTime() - startD.getTime()) / totalMs) * 100;
      const width = Math.max(
        ((e.getTime() - s.getTime()) / totalMs) * 100,
        // Floor very-short intervals at 1.5% so they're still clickable.
        1.5,
      );
      return { ...iv, left, width, key: `${iv.started_at}-${i}`, sIso: isoDay(s), eIso: isoDay(e) };
    });
    return { start: startD, end: endD, segs };
  }, [intervals]);

  // Today marker position
  const todayLeft = useMemo(() => {
    const totalMs = Math.max(end.getTime() - start.getTime(), 1);
    const now = Date.now();
    if (now < start.getTime()) return null;
    if (now > end.getTime()) return null;
    return ((now - start.getTime()) / totalMs) * 100;
  }, [start, end]);

  if (intervals.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No ownership history yet. Open the History tab on a player who&apos;s been
        traded or dropped to see the timeline.
      </p>
    );
  }

  const isSelected = (sIso: string, eIso: string) =>
    selectedRange?.start === sIso && selectedRange?.end === eIso;

  return (
    <div className="space-y-2">
      {/* Axis dates */}
      <div className="flex justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
        <span>{fmtShort(start)}</span>
        {todayLeft !== null && todayLeft > 8 && todayLeft < 92 && (
          <span>Today</span>
        )}
        <span>{end > new Date() ? fmtShort(end) : "Now"}</span>
      </div>

      {/* The bar */}
      <div className="relative h-9 overflow-hidden rounded-md bg-foreground/[0.03] ring-1 ring-foreground/10">
        {segs.map((s) => {
          const tone = teamColor(s.team_id);
          const sel = isSelected(s.sIso, s.eIso);
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => onPickRange(s.sIso, s.eIso)}
              title={`${s.team_name ?? "Free agent"}\n${fmtShort(parseISO(s.started_at))} → ${
                s.ended_at ? fmtShort(parseISO(s.ended_at)) : "now"
              }`}
              style={{ left: `${s.left}%`, width: `${s.width}%` }}
              className={cn(
                "absolute top-0 bottom-0 transition hover:brightness-110",
                tone,
                s.is_user_team && USER_TEAM_RING,
                sel && "ring-2 ring-foreground brightness-110",
              )}
            />
          );
        })}
        {/* Today marker */}
        {todayLeft !== null && (
          <div
            className="pointer-events-none absolute top-[-3px] bottom-[-3px] w-[2px] bg-foreground"
            style={{ left: `${todayLeft}%` }}
          />
        )}
      </div>

      {/* Legend — one chip per interval, click to select. Helpful for very-narrow segments. */}
      <ul className="flex flex-wrap gap-1.5">
        {segs.map((s) => {
          const sel = isSelected(s.sIso, s.eIso);
          return (
            <li key={s.key}>
              <button
                type="button"
                onClick={() => onPickRange(s.sIso, s.eIso)}
                className={cn(
                  "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition",
                  sel
                    ? "border-foreground bg-foreground/10"
                    : "border-foreground/10 hover:bg-foreground/5",
                  s.is_user_team && !sel && "border-orange-500/40 bg-orange-500/[0.06]",
                )}
              >
                <span
                  className={cn(
                    "size-2 shrink-0 rounded-sm",
                    teamColor(s.team_id),
                  )}
                />
                <span
                  className={cn(
                    "font-medium",
                    s.is_user_team && "text-orange-400",
                    s.team_id === null && "text-muted-foreground",
                  )}
                >
                  {s.team_name ?? "Free agent"}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {fmtShort(parseISO(s.started_at))} →{" "}
                  {s.ended_at ? fmtShort(parseISO(s.ended_at)) : "now"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
