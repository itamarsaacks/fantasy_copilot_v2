"use client";

/**
 * What-if simulator panel — Phase 4 of the my-team tab.
 *
 * Lets the user replace a current roster player with any league-eligible
 * player (typically a FA) and see the projected FPS delta over a window
 * of NBA dates. Hits POST /api/team/simulate (master plan §2.8).
 *
 * Lightweight MVP:
 *   - One swap at a time (out → in)
 *   - Date window via shared <CalendarMultiPicker/>
 *   - Search the "in" player by name (mention-context endpoint)
 *
 * Result: baseline_fps / simulated_fps / delta over the selected dates.
 */
import { useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { toISODate, addDays } from "@/lib/date-utils";
import type {
  MentionContextResponse,
  TeamPlayerView,
  TeamResponse,
} from "@/lib/api-types";
import { CalendarMultiPicker } from "@/components/shared/calendar-multi-picker";
import { PlayerAvatar } from "@/components/shared/player-avatar";
import { cn } from "@/lib/utils";

type SimulateResponse = {
  league_id: number;
  dates: string[];
  baseline_fps: number;
  simulated_fps: number;
  delta: number;
  per_player_delta: Record<number, number>;
};

export interface SimulatorPanelProps {
  leagueId: number;
  today: Date;
  team: TeamResponse;
}

function allRosterPlayers(t: TeamResponse): TeamPlayerView[] {
  return [...t.starters.players, ...t.bench.players, ...t.ir.players];
}

function fmtFps(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(1);
}

export function SimulatorPanel({ leagueId, today, team }: SimulatorPanelProps) {
  const [open, setOpen] = useState(false);
  const [outPlayerId, setOutPlayerId] = useState<number | null>(null);
  const [inSearch, setInSearch] = useState("");
  const [inPlayer, setInPlayer] = useState<{
    player_id: number;
    full_name: string;
    headshot_path?: string | null;
  } | null>(null);
  const [dates, setDates] = useState<Date[]>(() => [
    addDays(today, 1),
    addDays(today, 2),
    addDays(today, 3),
  ]);

  // Roster pool (out side)
  const rosterPool = useMemo(() => allRosterPlayers(team), [team]);
  const rosterById = useMemo(
    () => new Map(rosterPool.map((p) => [p.player_id, p])),
    [rosterPool],
  );

  // Player search pool (in side) — mention-context endpoint returns ~700
  // players for the league. Filter client-side, exclude any player
  // already on this roster.
  const mentionsQ = useQuery<MentionContextResponse>({
    queryKey: ["mention-context", leagueId],
    queryFn: () =>
      api<MentionContextResponse>(
        `/api/players/${leagueId}/mention-context`,
      ),
    enabled: open && !!leagueId,
    staleTime: 10 * 60_000,
  });

  const inMatches = useMemo(() => {
    if (!inSearch.trim() || !mentionsQ.data) return [];
    const q = inSearch.trim().toLowerCase();
    const exclude = new Set(rosterPool.map((p) => p.player_id));
    return mentionsQ.data.players
      .filter((p) => !exclude.has(p.player_id))
      .filter((p) => p.full_name.toLowerCase().includes(q))
      .slice(0, 10);
  }, [inSearch, mentionsQ.data, rosterPool]);

  const simulateMut = useMutation<SimulateResponse>({
    mutationFn: () =>
      api<SimulateResponse>("/api/team/simulate", {
        method: "POST",
        body: {
          league_id: leagueId,
          dates: dates.map(toISODate),
          swaps:
            outPlayerId !== null && inPlayer !== null
              ? [{ out_player_id: outPlayerId, in_player_id: inPlayer.player_id }]
              : [],
        },
      }),
  });

  const canSimulate =
    outPlayerId !== null && inPlayer !== null && dates.length > 0;
  const outPlayer = outPlayerId !== null ? rosterById.get(outPlayerId) : null;

  return (
    <section className="rounded-xl bg-card ring-1 ring-foreground/10">
      <header
        onClick={() => setOpen((p) => !p)}
        className="flex cursor-pointer items-center justify-between border-b border-foreground/10 px-4 py-3 transition hover:bg-foreground/[0.02]"
      >
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            What-if simulator
          </h2>
          <p className="text-[11px] text-muted-foreground">
            Plan a pickup — drop a roster player for a FA over selected dates
          </p>
        </div>
        <span
          className={cn(
            "text-xl text-muted-foreground transition",
            open && "rotate-180",
          )}
        >
          ⌄
        </span>
      </header>

      {open && (
        <div className="space-y-4 p-4">
          {/* Out + In selectors */}
          <div className="grid gap-4 md:grid-cols-2">
            {/* OUT */}
            <div>
              <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Drop (from your roster)
              </label>
              <select
                value={outPlayerId ?? ""}
                onChange={(e) =>
                  setOutPlayerId(e.target.value ? Number(e.target.value) : null)
                }
                className="h-10 w-full rounded-md border border-foreground/15 bg-background px-3 text-sm"
              >
                <option value="">Pick a player…</option>
                {rosterPool.map((p) => (
                  <option key={p.player_id} value={p.player_id}>
                    {p.name}
                    {p.selected_position ? ` · ${p.selected_position}` : ""}
                  </option>
                ))}
              </select>
              {outPlayer && (
                <div className="mt-2 flex items-center gap-2 rounded-md bg-red-500/[0.06] p-2 ring-1 ring-red-500/20">
                  <PlayerAvatar
                    name={outPlayer.name}
                    headshotPath={outPlayer.headshot_path}
                    size={24}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {outPlayer.name}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      {outPlayer.nba_team ?? "—"} ·{" "}
                      {outPlayer.eligible_positions.join(", ") || "—"}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* IN */}
            <div>
              <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Add (search players)
              </label>
              <input
                value={inSearch}
                onChange={(e) => {
                  setInSearch(e.target.value);
                  setInPlayer(null);
                }}
                placeholder="Start typing a name…"
                className="h-10 w-full rounded-md border border-foreground/15 bg-background px-3 text-sm"
              />
              {!inPlayer && inMatches.length > 0 && (
                <ul className="mt-1 max-h-48 overflow-y-auto rounded-md border border-foreground/10 bg-background">
                  {inMatches.map((p) => (
                    <li key={p.player_id}>
                      <button
                        type="button"
                        onClick={() => {
                          setInPlayer({
                            player_id: p.player_id,
                            full_name: p.full_name,
                            headshot_path: p.headshot_path ?? null,
                          });
                          setInSearch(p.full_name);
                        }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition hover:bg-foreground/5"
                      >
                        <PlayerAvatar
                          name={p.full_name}
                          headshotPath={p.headshot_path}
                          size={24}
                        />
                        <span className="truncate">{p.full_name}</span>
                        {p.nba_team_abbr && (
                          <span className="ml-auto text-[11px] text-muted-foreground">
                            {p.nba_team_abbr}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {inPlayer && (
                <div className="mt-2 flex items-center gap-2 rounded-md bg-emerald-500/[0.06] p-2 ring-1 ring-emerald-500/20">
                  <PlayerAvatar
                    name={inPlayer.full_name}
                    headshotPath={inPlayer.headshot_path}
                    size={24}
                  />
                  <div className="min-w-0 flex-1 truncate text-sm font-medium">
                    {inPlayer.full_name}
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setInPlayer(null);
                      setInSearch("");
                    }}
                    className="rounded px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-foreground/10"
                  >
                    clear
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Date picker */}
          <div>
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Dates to compare ({dates.length} selected)
            </label>
            <CalendarMultiPicker
              value={dates}
              onChange={setDates}
              minDate={today}
            />
          </div>

          {/* Run + result */}
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => simulateMut.mutate()}
              disabled={!canSimulate || simulateMut.isPending}
              className={cn(
                "rounded-md px-4 py-2 text-sm font-semibold transition",
                "bg-orange-500 text-white",
                "disabled:cursor-not-allowed disabled:opacity-50",
                "hover:bg-orange-600",
              )}
            >
              {simulateMut.isPending ? "Simulating…" : "Run simulation"}
            </button>
            {!canSimulate && (
              <span className="text-xs text-muted-foreground">
                Pick a drop, an add, and at least one date
              </span>
            )}
            {simulateMut.isError && (
              <span className="text-xs text-red-400">
                {(simulateMut.error as Error).message}
              </span>
            )}
          </div>

          {simulateMut.data && (
            <div className="grid gap-3 rounded-lg bg-foreground/[0.03] p-4 sm:grid-cols-3">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Baseline
                </div>
                <div className="text-2xl font-bold tabular-nums">
                  {fmtFps(simulateMut.data.baseline_fps)}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Current roster · {simulateMut.data.dates.length}{" "}
                  {simulateMut.data.dates.length === 1 ? "date" : "dates"}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Simulated
                </div>
                <div className="text-2xl font-bold tabular-nums">
                  {fmtFps(simulateMut.data.simulated_fps)}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  After your swap
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Delta
                </div>
                <div
                  className={cn(
                    "text-2xl font-bold tabular-nums",
                    simulateMut.data.delta > 0
                      ? "text-emerald-400"
                      : simulateMut.data.delta < 0
                        ? "text-red-400"
                        : "",
                  )}
                >
                  {simulateMut.data.delta > 0 ? "+" : ""}
                  {fmtFps(simulateMut.data.delta)}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Projected FPS change
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
