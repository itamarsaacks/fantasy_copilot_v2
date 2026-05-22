"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { useAppToday } from "@/lib/hooks/use-app-today";
import { api } from "@/lib/api";
import type { TeamPlayerView, TeamResponse } from "@/lib/api-types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function toISODate(d: Date): string {
  // YYYY-MM-DD in local time
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseISODate(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function formatDateHeadline(d: Date, today: Date): string {
  if (isSameDay(d, today)) return "Today";
  const yest = new Date(today);
  yest.setDate(today.getDate() - 1);
  if (isSameDay(d, yest)) return "Yesterday";
  const tom = new Date(today);
  tom.setDate(today.getDate() + 1);
  if (isSameDay(d, tom)) return "Tomorrow";
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

function formatTipoff(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function formatFps(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(1);
}

function formatStat(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(1);
}

function statusTone(status: string | null): "default" | "warning" | "danger" {
  if (!status) return "default";
  const s = status.toUpperCase();
  if (["OUT", "O", "IL", "IL-LT", "NA", "SUSP"].includes(s)) return "danger";
  if (["INJ", "GTD", "DTD", "Q"].includes(s)) return "warning";
  return "default";
}

// ---------------------------------------------------------------------------
// Slot logic
// ---------------------------------------------------------------------------

const SLOT_ORDER = [
  "PG", "SG", "G", "SF", "PF", "F", "C", "Util",
  "BN",
  "IR", "IR+", "IL", "IL+", "NA",
];
const BENCH_SLOTS = new Set(["BN"]);
const IR_SLOTS = new Set(["IR", "IR+", "IL", "IL+", "NA"]);

function slotBucket(slot: string | null): "starters" | "bench" | "ir" {
  if (!slot) return "starters";
  const s = slot.toUpperCase();
  if (BENCH_SLOTS.has(s)) return "bench";
  if (IR_SLOTS.has(s)) return "ir";
  return "starters";
}

function slotWeight(slot: string | null): number {
  if (!slot) return 999;
  const idx = SLOT_ORDER.indexOf(slot);
  return idx === -1 ? 998 : idx;
}

const IR_ELIGIBLE_STATUSES = new Set([
  "OUT", "O", "IL", "IL-LT", "INJ", "GTD", "DTD", "Q", "NA", "SUSP",
]);

/** Can `player` legally occupy `slot`? Matches Yahoo's eligibility rules. */
function canFillSlot(player: TeamPlayerView, slot: string): boolean {
  const s = slot.toUpperCase();
  if (s === "BN" || s === "UTIL") return true;
  if (IR_SLOTS.has(s)) {
    return IR_ELIGIBLE_STATUSES.has((player.status ?? "").toUpperCase());
  }
  const elig = player.eligible_positions ?? [];
  if (s === "G") return elig.includes("PG") || elig.includes("SG");
  if (s === "F") return elig.includes("SF") || elig.includes("PF");
  return elig.includes(s);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DateStrip({
  date,
  onChange,
  today,
}: {
  date: Date;
  onChange: (d: Date) => void;
  today: Date;
}) {
  function shift(days: number) {
    const next = new Date(date);
    next.setDate(date.getDate() + days);
    onChange(next);
  }
  const isToday = isSameDay(date, today);

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl bg-card px-3 py-2 ring-1 ring-foreground/10">
      <button
        type="button"
        onClick={() => shift(-1)}
        className="flex h-9 w-9 items-center justify-center rounded-md text-lg ring-1 ring-foreground/10 transition hover:bg-foreground/5"
        aria-label="Previous day"
      >
        ‹
      </button>
      <div className="flex min-w-0 flex-1 flex-col items-center px-2 sm:flex-row sm:items-baseline sm:gap-3">
        <span className="text-sm font-semibold tracking-tight">
          {formatDateHeadline(date, today)}
        </span>
        <span className="text-xs text-muted-foreground">
          {date.toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          })}
        </span>
      </div>
      <button
        type="button"
        onClick={() => shift(1)}
        className="flex h-9 w-9 items-center justify-center rounded-md text-lg ring-1 ring-foreground/10 transition hover:bg-foreground/5"
        aria-label="Next day"
      >
        ›
      </button>
      <input
        type="date"
        value={toISODate(date)}
        onChange={(e) => e.target.value && onChange(parseISODate(e.target.value))}
        className="h-9 rounded-md border border-foreground/10 bg-background px-2 text-sm"
      />
      {!isToday && (
        <button
          type="button"
          onClick={() => onChange(new Date(today))}
          className="h-9 rounded-md px-3 text-xs font-medium text-muted-foreground ring-1 ring-foreground/10 transition hover:bg-foreground/5"
        >
          Today
        </button>
      )}
    </div>
  );
}

function GameCell({ player }: { player: TeamPlayerView }) {
  const g = player.game_on_date;
  if (!g) {
    return (
      <span className="text-xs text-muted-foreground/60">No game</span>
    );
  }
  const homeSymbol = g.home ? "vs" : "@";
  const time = formatTipoff(g.tipoff_at);
  return (
    <div className="text-xs">
      <span className="text-foreground/80">
        {homeSymbol} {g.opponent}
      </span>
      {time && <span className="ml-2 text-muted-foreground">{time}</span>}
      {g.is_back_to_back && (
        <span className="ml-2 rounded border border-amber-500/30 bg-amber-500/10 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-500">
          B2B
        </span>
      )}
    </div>
  );
}

function StatCell({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="text-center">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="text-sm font-semibold tabular-nums">
        {formatStat(value)}
      </div>
    </div>
  );
}

function PlayerRow({
  p,
  effectiveSlot,
  isPast,
  isSwapSource,
  isSwapCandidate,
  isModified,
  swapDisabledReason,
  onClickSwap,
  onClickRow,
}: {
  p: TeamPlayerView;
  effectiveSlot: string | null;
  isPast: boolean;
  isSwapSource: boolean;
  isSwapCandidate: boolean;
  isModified: boolean;
  swapDisabledReason: string | null;
  onClickSwap: () => void;
  onClickRow: () => void;
}) {
  const tone = statusTone(p.status);
  // On past dates, prefer the actual-game stat line. If we have no actuals
  // (player wasn't on a team that played, or Yahoo returned nothing) we
  // fall back to the season averages so the row isn't blank.
  const usingActuals = isPast && p.actual_stats !== null;
  const s = usingActuals && p.actual_stats ? p.actual_stats : p.season_stats;
  const rightNumber = isPast ? p.actual_fps_on_date : p.projected_fps_on_date;
  const rightLabel = isPast ? "Actual" : "Proj";
  const showHighlight = isSwapSource || isSwapCandidate;
  const clickable = isSwapSource || isSwapCandidate || swapDisabledReason === null;

  return (
    <div
      onClick={clickable ? onClickRow : undefined}
      className={cn(
        "grid grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-foreground/5 px-3 py-3 last:border-b-0 transition",
        "hover:bg-foreground/[0.02]",
        isSwapSource && "bg-orange-500/10 ring-1 ring-inset ring-orange-500/40",
        isSwapCandidate &&
          "bg-emerald-500/[0.06] ring-1 ring-inset ring-emerald-500/30 cursor-pointer",
        swapDisabledReason && "opacity-40",
        isModified && !showHighlight && "bg-blue-500/[0.04]",
      )}
      title={swapDisabledReason ?? undefined}
    >
      {/* Slot pill — clickable to initiate swap */}
      <div className="text-center">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onClickSwap();
          }}
          className={cn(
            "min-w-[2.5rem] rounded-md px-2 py-1 text-xs font-bold uppercase tracking-wider transition",
            "ring-1 ring-foreground/15 hover:bg-foreground/10",
            isSwapSource && "bg-orange-500 text-white ring-orange-500",
            isModified && !isSwapSource && "bg-blue-500/15 ring-blue-500/40 text-blue-400",
          )}
        >
          {effectiveSlot ?? "—"}
        </button>
      </div>

      {/* Player meta + game */}
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-semibold">{p.name}</span>
          {p.status && (
            <span
              className={cn(
                "shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
                tone === "danger" &&
                  "border-red-500/40 bg-red-500/10 text-red-400",
                tone === "warning" &&
                  "border-amber-500/40 bg-amber-500/10 text-amber-500",
                tone === "default" &&
                  "border-foreground/15 bg-foreground/5 text-muted-foreground",
              )}
            >
              {p.status}
            </span>
          )}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {p.nba_team ?? "—"} · {p.eligible_positions.join(", ")}
        </div>
        <div className="mt-1">
          <GameCell player={p} />
        </div>
        {p.injury_note && (
          <p className="mt-1 line-clamp-1 text-[11px] text-muted-foreground/80">
            {p.injury_note}
          </p>
        )}
      </div>

      {/* Stat columns + per-date projection — desktop only */}
      <div className="hidden items-center gap-4 md:flex">
        <div className="grid grid-cols-6 gap-3">
          <StatCell label="PTS" value={s.pts} />
          <StatCell label="REB" value={s.reb} />
          <StatCell label="AST" value={s.ast} />
          <StatCell label="ST" value={s.stl} />
          <StatCell label="BLK" value={s.blk} />
          <StatCell label="TO" value={s.tov} />
        </div>
        <div className="w-16 border-l border-foreground/10 pl-3 text-right">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            {rightLabel}
          </div>
          <div className="text-base font-bold tabular-nums">
            {formatFps(rightNumber)}
          </div>
        </div>
      </div>

      {/* Mobile: just the right-side number */}
      <div className="md:hidden text-right">
        <div className="text-base font-bold tabular-nums">
          {formatFps(rightNumber)}
        </div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
          {rightLabel}
        </div>
      </div>
    </div>
  );
}

function MobileStatRow({ p, isPast }: { p: TeamPlayerView; isPast: boolean }) {
  const s =
    isPast && p.actual_stats ? p.actual_stats : p.season_stats;
  return (
    <div className="grid grid-cols-6 border-b border-foreground/5 bg-foreground/[0.015] px-3 py-2 md:hidden">
      <StatCell label="PTS" value={s.pts} />
      <StatCell label="REB" value={s.reb} />
      <StatCell label="AST" value={s.ast} />
      <StatCell label="ST" value={s.stl} />
      <StatCell label="BLK" value={s.blk} />
      <StatCell label="TO" value={s.tov} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function TeamView() {
  const { leagueId, league, isLoading: leagueLoading } = useActiveLeague();
  // appToday is replay-aware. SSR / before-resolve falls back to wall-clock
  // so the component renders something; useEffect re-seeds `date` once
  // appToday actually arrives.
  const { today: appToday } = useAppToday();
  const today = appToday ?? new Date();
  const [date, setDate] = useState<Date | null>(null);

  useEffect(() => {
    if (appToday && !date) setDate(appToday);
  }, [appToday, date]);

  // Local what-if slot overrides: playerName -> custom slot.
  // Persisted only in component state. Not pushed to Yahoo.
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [swapSource, setSwapSource] = useState<string | null>(null);

  const dateISO = date ? toISODate(date) : "";
  const teamQ = useQuery<TeamResponse>({
    queryKey: ["team", leagueId, dateISO],
    queryFn: () =>
      api<TeamResponse>(`/api/team/${leagueId}?date=${dateISO}`),
    enabled: !!leagueId && !!dateISO,
  });

  // Flatten the three buckets to a single list — we re-bucket on the client
  // after applying overrides.
  const allPlayers: TeamPlayerView[] = useMemo(() => {
    if (!teamQ.data) return [];
    return [
      ...teamQ.data.starters.players,
      ...teamQ.data.bench.players,
      ...teamQ.data.ir.players,
    ];
  }, [teamQ.data]);

  function effectiveSlot(p: TeamPlayerView): string | null {
    return overrides[p.name] ?? p.selected_position;
  }

  const sourcePlayer = swapSource
    ? allPlayers.find((x) => x.name === swapSource) ?? null
    : null;

  /**
   * Reason a swap with `target` is disallowed, or null if it's allowed.
   * BN/IR moves are unilateral (the source's old slot is filled by anyone
   * already in the target slot — but bench is many-slotted in NBA fantasy,
   * so we always allow swaps with bench/IR-eligible players).
   */
  function swapBlockedReason(target: TeamPlayerView): string | null {
    if (!sourcePlayer) return null;
    if (target.name === sourcePlayer.name) return null;
    const srcSlot = effectiveSlot(sourcePlayer);
    const tgtSlot = effectiveSlot(target);
    if (!srcSlot || !tgtSlot) return "missing slot";
    if (!canFillSlot(target, srcSlot)) {
      return `${target.name} can't fill ${srcSlot}`;
    }
    if (!canFillSlot(sourcePlayer, tgtSlot)) {
      return `${sourcePlayer.name} can't fill ${tgtSlot}`;
    }
    return null;
  }

  function applySwap(target: TeamPlayerView) {
    if (!sourcePlayer || target.name === sourcePlayer.name) {
      setSwapSource(null);
      return;
    }
    const srcSlot = effectiveSlot(sourcePlayer);
    const tgtSlot = effectiveSlot(target);
    if (!srcSlot || !tgtSlot) {
      setSwapSource(null);
      return;
    }
    setOverrides((prev) => ({
      ...prev,
      [sourcePlayer.name]: tgtSlot,
      [target.name]: srcSlot,
    }));
    setSwapSource(null);
  }

  function onClickSlot(playerName: string) {
    setSwapSource((prev) => (prev === playerName ? null : playerName));
  }

  function onClickRow(target: TeamPlayerView) {
    if (!swapSource) return;
    if (swapSource === target.name) {
      setSwapSource(null);
      return;
    }
    if (swapBlockedReason(target) !== null) return;
    applySwap(target);
  }

  function resetOverrides() {
    setOverrides({});
    setSwapSource(null);
  }

  const hasOverrides = Object.keys(overrides).length > 0;

  // Re-bucket players based on effective (possibly overridden) slot
  const bucketed = useMemo(() => {
    const out = { starters: [] as TeamPlayerView[], bench: [] as TeamPlayerView[], ir: [] as TeamPlayerView[] };
    for (const p of allPlayers) {
      const slot = effectiveSlot(p);
      out[slotBucket(slot)].push(p);
    }
    for (const k of Object.keys(out) as Array<keyof typeof out>) {
      out[k].sort(
        (a, b) => slotWeight(effectiveSlot(a)) - slotWeight(effectiveSlot(b)),
      );
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allPlayers, overrides]);

  if (leagueLoading || teamQ.isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading roster…</div>
    );
  }
  if (teamQ.isError) {
    return (
      <div className="p-6 text-sm text-red-400">
        Couldn&apos;t load roster: {(teamQ.error as Error).message}
      </div>
    );
  }
  if (!teamQ.data) return null;
  const t = teamQ.data;
  const isPast = t.is_past_date;

  function renderBucket(label: string, players: TeamPlayerView[]) {
    if (players.length === 0) return null;
    return (
      <section className="rounded-xl bg-card ring-1 ring-foreground/10">
        <header className="flex items-baseline justify-between border-b border-foreground/10 px-4 py-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            {label}
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {players.length} {players.length === 1 ? "player" : "players"}
            </span>
          </h2>
        </header>
        <div>
          {players.map((p) => {
            const isSrc = swapSource === p.name;
            const blocked = swapSource && !isSrc ? swapBlockedReason(p) : null;
            const isCandidate = !!swapSource && !isSrc && blocked === null;
            return (
              <div key={p.name}>
                <PlayerRow
                  p={p}
                  effectiveSlot={effectiveSlot(p)}
                  isPast={isPast}
                  isSwapSource={isSrc}
                  isSwapCandidate={isCandidate}
                  isModified={overrides[p.name] !== undefined}
                  swapDisabledReason={blocked}
                  onClickSwap={() => onClickSlot(p.name)}
                  onClickRow={() => onClickRow(p)}
                />
                <MobileStatRow p={p} isPast={isPast} />
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t.team_name}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t.manager_name ? `${t.manager_name} · ` : ""}
            {league?.name}
          </p>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        {date ? (
          <DateStrip date={date} onChange={setDate} today={today} />
        ) : (
          <div className="h-13 w-64 animate-pulse rounded-xl bg-foreground/5" />
        )}
        {isPast && (
          <span className="rounded-full border border-foreground/15 bg-foreground/5 px-2 py-1 text-[11px] font-medium text-muted-foreground">
            Past date — showing actual stats
          </span>
        )}
      </div>

      {(swapSource || hasOverrides) && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-orange-500/30 bg-orange-500/[0.06] px-4 py-2">
          <div className="text-xs">
            {swapSource ? (
              <span>
                <span className="font-semibold text-orange-400">
                  Pick a player to swap with {swapSource}
                </span>
                <span className="ml-2 text-muted-foreground">
                  · Green rows are eligible · Tap the slot pill again to cancel
                </span>
              </span>
            ) : (
              <span className="text-muted-foreground">
                Lineup what-if active — changes are local only, not sent to
                Yahoo
              </span>
            )}
          </div>
          {hasOverrides && (
            <button
              type="button"
              onClick={resetOverrides}
              className="rounded-md border border-foreground/20 bg-background px-3 py-1 text-xs font-medium hover:bg-foreground/5"
            >
              Reset to Yahoo lineup
            </button>
          )}
        </div>
      )}

      {renderBucket("Starters", bucketed.starters)}
      {renderBucket("Bench", bucketed.bench)}
      {renderBucket("Injured Reserve", bucketed.ir)}
    </div>
  );
}
