"use client";

/**
 * Waiver Planner — pick specific calendar dates, get FA candidates whose
 * teams play on at least one of those dates, ranked by combined
 * projected FPS over the selected window.
 *
 * Per master plan §2.8: GET /api/waiver-planner/candidates?league_id&dates=
 *
 * Built on the same Phase-1 primitives as the my-team simulator —
 * shared CalendarMultiPicker + PlayerAvatar + DrawerProvider.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { useAppToday } from "@/lib/hooks/use-app-today";
import { api } from "@/lib/api";
import { addDays, toISODate, fmtDateShort } from "@/lib/date-utils";
import type { WaiverPlannerResponse } from "@/lib/api-types";
import { CalendarMultiPicker } from "@/components/shared/calendar-multi-picker";
import { PlayerAvatar } from "@/components/shared/player-avatar";
import { TeamLogo } from "@/components/shared/team-logo";
import { useDrawer } from "@/components/shared/drawer-context";
import { cn } from "@/lib/utils";

function fmtFps(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(1);
}

export function WaiverPlannerView() {
  const { leagueId } = useActiveLeague();
  const { today: appToday } = useAppToday();
  const { openPlayer } = useDrawer();
  const today = appToday ?? new Date();
  const [dates, setDates] = useState<Date[]>(() => [
    addDays(today, 1),
    addDays(today, 2),
    addDays(today, 3),
  ]);

  const datesISO = useMemo(
    () => dates.map(toISODate).sort(),
    [dates],
  );
  const datesParam = datesISO.join(",");

  const q = useQuery<WaiverPlannerResponse>({
    queryKey: ["waiver-planner", leagueId, datesParam],
    queryFn: () =>
      api<WaiverPlannerResponse>(
        `/api/waiver-planner/candidates?league_id=${leagueId}&dates=${datesParam}`,
      ),
    enabled: !!leagueId && dates.length > 0,
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  });

  return (
    <div className="space-y-4">
      {/* Picker */}
      <section className="rounded-xl bg-card ring-1 ring-foreground/10">
        <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-foreground/10 px-4 py-2">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wider">
              Pick the dates to plan for
            </h2>
            <p className="text-[11px] text-muted-foreground">
              Free agents whose NBA team plays on at least one selected date,
              ranked by projected FPS over the whole window.
            </p>
          </div>
          {dates.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {[...dates]
                .sort((a, b) => a.getTime() - b.getTime())
                .map((d) => (
                  <span
                    key={toISODate(d)}
                    className="rounded-full border border-orange-500/40 bg-orange-500/10 px-2 py-0.5 text-[11px] font-semibold text-orange-400"
                  >
                    {fmtDateShort(d)}
                  </span>
                ))}
            </div>
          )}
        </header>
        <div className="p-4">
          <CalendarMultiPicker
            value={dates}
            onChange={setDates}
            minDate={today}
          />
        </div>
      </section>

      {/* Candidates */}
      <section className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
        <header className="flex items-baseline justify-between border-b border-foreground/10 px-4 py-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            Free agents
          </h2>
          <span className="text-xs text-muted-foreground">
            {q.data
              ? `${q.data.candidates.length} candidate${q.data.candidates.length === 1 ? "" : "s"}`
              : ""}
          </span>
        </header>

        {q.isLoading && (
          <div className="py-12 text-center text-sm text-muted-foreground">
            Loading candidates…
          </div>
        )}
        {q.isError && (
          <div className="py-12 text-center text-sm text-red-400">
            Couldn&apos;t load candidates: {(q.error as Error).message}
          </div>
        )}
        {dates.length === 0 && (
          <div className="py-12 text-center text-sm text-muted-foreground">
            Pick at least one date to see candidates.
          </div>
        )}
        {q.data && q.data.candidates.length === 0 && dates.length > 0 && (
          <div className="space-y-1 py-12 text-center text-sm text-muted-foreground">
            <p>No free agents have games on these dates.</p>
            <p className="text-[11px]">
              Likely an off-day for the whole league (e.g. All-Star break) —
              pick a date when teams are scheduled to play.
            </p>
          </div>
        )}

        {q.data && q.data.candidates.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-foreground/[0.03] text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">Player</th>
                  <th className="px-3 py-2 text-right">Games</th>
                  <th className="px-3 py-2 text-right">Window FPS</th>
                  <th className="hidden px-3 py-2 text-right sm:table-cell">
                    Pos
                  </th>
                  <th className="hidden px-3 py-2 text-right sm:table-cell">
                    Team
                  </th>
                </tr>
              </thead>
              <tbody>
                {q.data.candidates.map((c) => (
                  <tr
                    key={c.player_id}
                    onClick={() => openPlayer(c.player_id, c.full_name)}
                    className={cn(
                      "cursor-pointer border-b border-foreground/5 last:border-b-0",
                      "transition hover:bg-foreground/[0.04]",
                    )}
                  >
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-3">
                        <PlayerAvatar
                          name={c.full_name}
                          headshotPath={c.headshot_path}
                          size={32}
                          className="shrink-0"
                        />
                        <span className="truncate font-medium">
                          {c.full_name}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {c.games_on_selected_dates}
                    </td>
                    <td className="px-3 py-2.5 text-right font-semibold tabular-nums">
                      {fmtFps(c.projected_fps_window)}
                    </td>
                    <td className="hidden px-3 py-2.5 text-right text-muted-foreground sm:table-cell">
                      {c.position ?? "—"}
                    </td>
                    <td className="hidden px-3 py-2.5 sm:table-cell">
                      <div className="flex items-center justify-end gap-2">
                        <TeamLogo abbr={c.nba_team_abbr} size={24} />
                        <span className="text-xs text-muted-foreground">
                          {c.nba_team_abbr ?? "—"}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
