"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import type { PlayerDetailResponse } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { PlayerAvatar } from "@/components/shared/player-avatar";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function daysAgoISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return toISODate(d);
}

function daysAheadISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return toISODate(d);
}

function fmt(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(digits);
}

const PRESETS = [
  { id: "l7", label: "Last 7", compute: () => ({ start: daysAgoISO(7), end: toISODate(new Date()) }) },
  { id: "l14", label: "Last 14", compute: () => ({ start: daysAgoISO(14), end: toISODate(new Date()) }) },
  { id: "l30", label: "Last 30", compute: () => ({ start: daysAgoISO(30), end: toISODate(new Date()) }) },
  { id: "l90", label: "Last 90", compute: () => ({ start: daysAgoISO(90), end: toISODate(new Date()) }) },
  { id: "next7", label: "Next 7", compute: () => ({ start: toISODate(new Date()), end: daysAheadISO(7) }) },
  { id: "next14", label: "Next 14", compute: () => ({ start: toISODate(new Date()), end: daysAheadISO(14) }) },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ComparePage() {
  const { leagueId, league, isLoading: leagueLoading } = useActiveLeague();
  const searchParams = useSearchParams();
  const rawIds = searchParams.get("ids") ?? "";
  const playerIds = rawIds
    .split(",")
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isInteger(n) && n > 0);

  const [start, setStart] = useState<string>(daysAgoISO(30));
  const [end, setEnd] = useState<string>(toISODate(new Date()));

  const queries = useQueries({
    queries: playerIds.map((pid) => ({
      queryKey: ["compare", leagueId, pid, start, end],
      queryFn: () =>
        api<PlayerDetailResponse>(
          `/api/players/${leagueId}/${pid}?start=${start}&end=${end}`,
        ),
      enabled: !!leagueId,
    })),
  });

  const loaded = queries
    .map((q) => q.data)
    .filter((d): d is PlayerDetailResponse => !!d);
  const anyLoading = queries.some((q) => q.isLoading);
  const anyError = queries.find((q) => q.isError);

  if (leagueLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }

  if (playerIds.length < 2) {
    return (
      <div className="mx-auto max-w-3xl space-y-3 p-6 text-sm text-muted-foreground">
        <p>
          Pick at least 2 players on the{" "}
          <Link href="/players" className="underline">
            Players tab
          </Link>{" "}
          (use the checkboxes), then click &quot;Compare&quot;.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <Link
            href="/players"
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← back to players
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            Compare {playerIds.length} players
          </h1>
          <p className="text-sm text-muted-foreground">
            {league?.name} · same date range applied to everyone
          </p>
        </div>
      </header>

      {/* Date range */}
      <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
        <div className="mb-2 flex flex-wrap items-center gap-1">
          {PRESETS.map((p) => {
            const r = p.compute();
            const active = r.start === start && r.end === end;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setStart(r.start);
                  setEnd(r.end);
                }}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium ring-1 transition",
                  active
                    ? "bg-foreground text-background ring-foreground"
                    : "bg-background text-muted-foreground ring-foreground/15 hover:bg-foreground/5",
                )}
              >
                {p.label}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <label className="text-muted-foreground">From</label>
          <input
            type="date"
            value={start}
            onChange={(e) => e.target.value && setStart(e.target.value)}
            className="h-8 rounded-md border border-foreground/10 bg-background px-2"
          />
          <label className="text-muted-foreground">to</label>
          <input
            type="date"
            value={end}
            onChange={(e) => e.target.value && setEnd(e.target.value)}
            className="h-8 rounded-md border border-foreground/10 bg-background px-2"
          />
        </div>
      </section>

      {anyError && (
        <div className="rounded-md bg-red-500/10 p-3 text-xs text-red-400">
          {(anyError.error as Error).message}
        </div>
      )}

      {anyLoading && (
        <div className="text-xs text-muted-foreground">Loading players…</div>
      )}

      {/* Stat row — each player gets a column */}
      <section className="overflow-x-auto rounded-xl bg-card ring-1 ring-foreground/10">
        <table className="w-full text-sm">
          <thead className="bg-foreground/[0.03] text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-4 py-2 text-left">Metric</th>
              {loaded.map((d) => (
                <th key={d.player.id} className="px-4 py-2 text-left">
                  <div className="flex items-center gap-2.5">
                    <PlayerAvatar
                      name={d.player.name}
                      headshotPath={d.player.headshot_path}
                      size={48}
                      className="shrink-0"
                    />
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-foreground">
                        {d.player.name}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {d.player.nba_team ?? "—"} ·{" "}
                        {d.ownership.state === "my_team"
                          ? "On my team"
                          : d.ownership.state === "on_team"
                          ? `on ${d.ownership.team_name}`
                          : d.ownership.state === "waivers"
                          ? "Waivers"
                          : "Free agent"}
                      </span>
                    </div>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <ComparisonSection title="Actual — period averages" />
            <ComparisonRow
              label="GP"
              cells={loaded.map((d) => String(d.actual.games_played))}
            />
            <ComparisonRow
              label="MIN/g"
              cells={loaded.map((d) => fmt(d.actual.per_game.min))}
            />
            <ComparisonRow
              label="PTS/g"
              cells={loaded.map((d) => fmt(d.actual.per_game.pts))}
              best
            />
            <ComparisonRow
              label="REB/g"
              cells={loaded.map((d) => fmt(d.actual.per_game.reb))}
              best
            />
            <ComparisonRow
              label="AST/g"
              cells={loaded.map((d) => fmt(d.actual.per_game.ast))}
              best
            />
            <ComparisonRow
              label="ST/g"
              cells={loaded.map((d) => fmt(d.actual.per_game.stl))}
              best
            />
            <ComparisonRow
              label="BLK/g"
              cells={loaded.map((d) => fmt(d.actual.per_game.blk))}
              best
            />
            <ComparisonRow
              label="TO/g"
              cells={loaded.map((d) => fmt(d.actual.per_game.tov))}
              best="low"
            />
            <ComparisonRow
              label="FPS/g (actual)"
              cells={loaded.map((d) => fmt(d.actual.fantasy_points_per_game))}
              emphasize
              best
            />
            <ComparisonRow
              label="FPS total"
              cells={loaded.map((d) => fmt(d.actual.fantasy_points_total))}
            />

            <ComparisonSection title="Projection — future portion of range" />
            <ComparisonRow
              label="Games projected"
              cells={loaded.map((d) => String(d.projection.games_projected))}
            />
            <ComparisonRow
              label="Proj FPS total"
              cells={loaded.map((d) => fmt(d.projection.fantasy_points_total))}
              best
            />
            <ComparisonRow
              label="Proj FPS/g"
              cells={loaded.map((d) => fmt(d.projection.fantasy_points_per_game))}
              emphasize
              best
            />
            <ComparisonRow
              label="Base per-game"
              cells={loaded.map((d) => fmt(d.base_projection_per_game))}
            />
          </tbody>
        </table>
      </section>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Bold cell = leader in that stat across the comparison set. Actuals come
        from Yahoo&apos;s per-date stats (cached after first fetch). Projections
        are the league&apos;s per-game value adjusted for home/away, B2B rest,
        and availability — no agent involved.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ComparisonSection({ title }: { title: string }) {
  return (
    <tr className="bg-foreground/[0.04]">
      <td
        colSpan={20}
        className="px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
      >
        {title}
      </td>
    </tr>
  );
}

function ComparisonRow({
  label,
  cells,
  emphasize = false,
  best,
}: {
  label: string;
  cells: string[];
  emphasize?: boolean;
  best?: boolean | "low";
}) {
  // For "best" rows, find the leader so we can highlight it. "low" inverts
  // the comparison (TO — lower is better).
  const leaderIndex = useMemo(() => {
    if (!best) return -1;
    const numeric = cells.map((c) => {
      const n = Number(c);
      return Number.isFinite(n) ? n : null;
    });
    let bestIdx = -1;
    let bestVal: number | null = null;
    numeric.forEach((v, i) => {
      if (v === null) return;
      if (bestVal === null) {
        bestVal = v;
        bestIdx = i;
        return;
      }
      const better = best === "low" ? v < bestVal : v > bestVal;
      if (better) {
        bestVal = v;
        bestIdx = i;
      }
    });
    return bestIdx;
  }, [cells, best]);

  return (
    <tr className="border-t border-foreground/5">
      <td
        className={cn(
          "px-4 py-2 text-xs",
          emphasize
            ? "font-semibold text-foreground"
            : "text-muted-foreground",
        )}
      >
        {label}
      </td>
      {cells.map((c, i) => (
        <td
          key={i}
          className={cn(
            "px-4 py-2 tabular-nums",
            emphasize ? "text-base font-bold" : "text-sm",
            best && i === leaderIndex && "text-emerald-400",
          )}
        >
          {c}
        </td>
      ))}
    </tr>
  );
}
