"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { useAppToday } from "@/lib/hooks/use-app-today";
import { api } from "@/lib/api";
import { toISODate, formatDateHeadline } from "@/lib/date-utils";
import type {
  LeagueResponse,
  StandingOnDate,
  StandingsOnDateResponse,
  TeamStanding,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { DateToggle } from "@/components/shared/date-toggle";
import { OpponentRosterDialog } from "./opponent-roster-dialog";

function formatNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function scoringTypeLabel(t: string): string {
  switch (t) {
    case "point":
      return "Points";
    case "headpoint":
      return "H2H Points";
    case "head":
      return "H2H Categories";
    case "roto":
      return "Rotisserie";
    default:
      return t;
  }
}

function hasRecord(t: TeamStanding): boolean {
  return t.wins !== null || t.losses !== null;
}

function MetaCard({ meta }: { meta: LeagueResponse["meta"] }) {
  return (
    <header className="grid gap-3 rounded-xl bg-card p-4 ring-1 ring-foreground/10 md:grid-cols-[1fr_auto]">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{meta.name}</h1>
        <p className="text-sm text-muted-foreground">
          {meta.season} · {scoringTypeLabel(meta.scoring_type)} ·{" "}
          {meta.num_teams} teams
          {meta.current_week !== null && ` · week ${meta.current_week}`}
        </p>
      </div>
    </header>
  );
}

function StandingsTable({
  teams,
  date,
  onDateChange,
  fpsByTeam,
  fpsLoading,
  maxDate,
  onTeamClick,
}: {
  teams: TeamStanding[];
  date: Date;
  onDateChange: (next: Date) => void;
  fpsByTeam: Map<number, number | null>;
  fpsLoading: boolean;
  maxDate?: Date;
  onTeamClick: (teamId: number) => void;
}) {
  const anyRecord = teams.some(hasRecord);
  const anyPA = teams.some((t) => t.points_against !== null);
  const dateHeader = formatDateHeadline(date);
  return (
    <section className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-foreground/10 px-4 py-2">
        <div className="flex items-baseline gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            Standings
          </h2>
          <span className="text-xs text-muted-foreground">
            {teams.length} teams
          </span>
        </div>
        <DateToggle value={date} onChange={onDateChange} maxDate={maxDate} />
      </header>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-foreground/[0.03] text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">#</th>
              <th className="px-3 py-2 text-left">Team</th>
              <th
                className="px-3 py-2 text-right"
                title={`Fantasy points on ${dateHeader}`}
              >
                FPS {dateHeader}
              </th>
              {anyRecord && <th className="px-3 py-2 text-right">W-L-T</th>}
              <th className="hidden px-3 py-2 text-right md:table-cell">
                Points For
              </th>
              {anyPA && (
                <th className="hidden px-3 py-2 text-right md:table-cell">
                  Against
                </th>
              )}
              <th className="hidden px-3 py-2 text-right lg:table-cell">
                Moves
              </th>
              <th className="hidden px-3 py-2 text-right lg:table-cell">
                Trades
              </th>
            </tr>
          </thead>
          <tbody>
            {teams.map((t) => (
              <tr
                key={t.team_id}
                onClick={() => onTeamClick(t.team_id)}
                className={cn(
                  "cursor-pointer border-b border-foreground/5 last:border-b-0",
                  "transition hover:bg-foreground/[0.04]",
                  t.is_user_team && "bg-orange-500/[0.05] hover:bg-orange-500/[0.08]",
                )}
              >
                <td className="px-3 py-2.5 text-left font-semibold tabular-nums">
                  {t.rank ?? "—"}
                </td>
                <td className="px-3 py-2.5 text-left">
                  <div className="flex items-baseline gap-2">
                    <span
                      className={cn(
                        "truncate",
                        t.is_user_team && "font-semibold",
                      )}
                    >
                      {t.name}
                    </span>
                    {t.is_user_team && (
                      <span className="shrink-0 rounded-full border border-orange-500/40 bg-orange-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-orange-400">
                        You
                      </span>
                    )}
                    {t.clinched_playoffs && (
                      <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-emerald-400">
                        Playoffs
                      </span>
                    )}
                  </div>
                  {t.manager_name && (
                    <div className="text-[11px] text-muted-foreground">
                      {t.manager_name}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right font-semibold tabular-nums">
                  {fpsLoading && !fpsByTeam.has(t.team_id) ? (
                    <span className="text-muted-foreground">…</span>
                  ) : (
                    formatNum(fpsByTeam.get(t.team_id) ?? null)
                  )}
                </td>
                {anyRecord && (
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {t.wins ?? 0}-{t.losses ?? 0}
                    {t.ties ? `-${t.ties}` : ""}
                  </td>
                )}
                <td className="hidden px-3 py-2.5 text-right font-semibold tabular-nums md:table-cell">
                  {formatNum(t.points_for)}
                </td>
                {anyPA && (
                  <td className="hidden px-3 py-2.5 text-right tabular-nums md:table-cell">
                    {formatNum(t.points_against)}
                  </td>
                )}
                <td className="hidden px-3 py-2.5 text-right tabular-nums text-muted-foreground lg:table-cell">
                  {t.number_of_moves ?? "—"}
                </td>
                <td className="hidden px-3 py-2.5 text-right tabular-nums text-muted-foreground lg:table-cell">
                  {t.number_of_trades ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ScoringCard({ rules, scoringType }: { rules: LeagueResponse["scoring"]; scoringType: string }) {
  if (rules.length === 0) return null;
  const isPoints = scoringType === "point" || scoringType === "headpoint";
  return (
    <section className="rounded-xl bg-card ring-1 ring-foreground/10">
      <header className="border-b border-foreground/10 px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider">
          Scoring
        </h2>
        <p className="text-[11px] text-muted-foreground">
          {isPoints
            ? "Each stat multiplied by its modifier to get fantasy points."
            : "Categories scored in this league."}
        </p>
      </header>
      <div className="grid gap-2 p-4 sm:grid-cols-2 md:grid-cols-3">
        {rules.map((r) => (
          <div
            key={r.stat_id}
            className="flex items-baseline justify-between rounded-md bg-background/40 px-3 py-2 ring-1 ring-foreground/5"
          >
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider">
                {r.abbr}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {r.display_name}
              </div>
            </div>
            {r.modifier !== null && (
              <span
                className={cn(
                  "text-base font-bold tabular-nums",
                  r.modifier < 0 && "text-red-400",
                )}
              >
                {r.modifier > 0 ? "+" : ""}
                {r.modifier}
              </span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function SettingsCard({ settings }: { settings: LeagueResponse["settings"] }) {
  const candidateRows: Array<[string, string | null]> = [
    ["Max teams", settings.max_teams !== null ? String(settings.max_teams) : null],
    ["Uses FAAB", settings.uses_faab ? "Yes" : "Waiver priority"],
    ["Waiver type", settings.waiver_type],
    ["Waiver days", settings.waiver_days],
    ["Waiver rule", settings.waiver_rule],
    ["Waiver time", settings.waiver_time],
    ["Playoffs", settings.uses_playoff ? "Yes" : "No"],
    ["Trade end", settings.trade_end_date],
    [
      "Max games / season",
      settings.max_games_played !== null
        ? String(settings.max_games_played)
        : null,
    ],
    ["High score wins", settings.is_highscore ? "Yes" : "No"],
  ];
  const rows = candidateRows.filter(
    (r): r is [string, string] => r[1] !== null && r[1] !== "",
  );

  return (
    <section className="rounded-xl bg-card ring-1 ring-foreground/10">
      <header className="border-b border-foreground/10 px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider">
          League settings
        </h2>
      </header>
      <dl className="grid gap-x-6 gap-y-2 p-4 text-sm sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-medium tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function LeagueView() {
  const { leagueId, isLoading: leagueLoading } = useActiveLeague();
  const { today: appToday } = useAppToday();
  const [date, setDate] = useState<Date | null>(null);
  const [openTeamId, setOpenTeamId] = useState<number | null>(null);

  // Seed the date from appToday once it resolves
  useEffect(() => {
    if (appToday && !date) setDate(appToday);
  }, [appToday, date]);

  const leagueQ = useQuery<LeagueResponse>({
    queryKey: ["league", leagueId],
    queryFn: () => api<LeagueResponse>(`/api/league/${leagueId}`),
    enabled: !!leagueId,
  });

  const dateISO = date ? toISODate(date) : null;
  const standingsQ = useQuery<StandingsOnDateResponse>({
    queryKey: ["standings-on-date", leagueId, dateISO],
    queryFn: () =>
      api<StandingsOnDateResponse>(
        `/api/standings?league_id=${leagueId}&date=${dateISO}`,
      ),
    enabled: !!leagueId && !!dateISO,
    // Keep previous data while re-fetching for new date — prevents flicker
    placeholderData: (prev) => prev,
  });

  if (leagueLoading || leagueQ.isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading league…</div>
    );
  }
  if (leagueQ.isError) {
    return (
      <div className="p-6 text-sm text-red-400">
        Couldn&apos;t load league: {(leagueQ.error as Error).message}
      </div>
    );
  }
  if (!leagueQ.data || !date) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading league…</div>
    );
  }
  const d = leagueQ.data;
  const fpsByTeam = new Map<number, number | null>();
  const standingByTeam = new Map<number, StandingOnDate>();
  for (const row of standingsQ.data?.standings ?? []) {
    fpsByTeam.set(row.team_id, row.fps_on_date);
    standingByTeam.set(row.team_id, row);
  }

  // Compose the StandingOnDate the dialog needs — prefer the live row if
  // we have it for this date; otherwise synthesize from the static league
  // row so the dialog still opens even before standings load.
  let dialogTeam: StandingOnDate | null = null;
  if (openTeamId !== null) {
    const live = standingByTeam.get(openTeamId);
    if (live) {
      dialogTeam = live;
    } else {
      const t = d.teams.find((x) => x.team_id === openTeamId);
      if (t) {
        dialogTeam = {
          team_id: t.team_id,
          team_name: t.name,
          manager_name: t.manager_name,
          fps_on_date: null,
          rank_on_date: t.rank ?? 0,
        };
      }
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <MetaCard meta={d.meta} />
      <StandingsTable
        teams={d.teams}
        date={date}
        onDateChange={setDate}
        fpsByTeam={fpsByTeam}
        fpsLoading={standingsQ.isLoading || standingsQ.isFetching}
        maxDate={appToday ?? undefined}
        onTeamClick={setOpenTeamId}
      />
      <div className="grid gap-4 md:grid-cols-2">
        <ScoringCard rules={d.scoring} scoringType={d.meta.scoring_type} />
        <SettingsCard settings={d.settings} />
      </div>

      <OpponentRosterDialog
        team={dialogTeam}
        date={date}
        open={openTeamId !== null}
        onOpenChange={(o) => {
          if (!o) setOpenTeamId(null);
        }}
      />
    </div>
  );
}
