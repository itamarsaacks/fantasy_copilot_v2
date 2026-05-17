"use client";

import { cn } from "@/lib/utils";

/**
 * Verdict tones — shared across landing, runs, and case detail so
 * a "pass" looks the same everywhere.
 */
export function verdictClasses(verdict: string): string {
  const v = verdict.toUpperCase();
  if (v === "PASS")
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-400";
  if (v === "SOFT_PASS")
    return "border-amber-500/40 bg-amber-500/10 text-amber-400";
  if (v === "FAIL") return "border-red-500/40 bg-red-500/10 text-red-400";
  if (v === "ERROR") return "border-red-700/40 bg-red-700/15 text-red-300";
  return "border-foreground/15 bg-foreground/5 text-muted-foreground";
}

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) {
    return (
      <span className="rounded-full border border-foreground/15 bg-foreground/5 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
        no history
      </span>
    );
  }
  return (
    <span
      className={cn(
        "rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        verdictClasses(verdict),
      )}
    >
      {verdict.replace(/_/g, " ")}
    </span>
  );
}

export function formatTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "—";
  return `$${usd.toFixed(4)}`;
}

export function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}
