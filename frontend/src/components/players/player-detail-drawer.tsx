"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  PlayerDetailResponse,
  PlayerGameLogRow,
  PlayerProjectedGameRow,
} from "@/lib/api-types";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseISO(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function fmtDateShort(iso: string): string {
  try {
    return parseISO(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(digits);
}

function statusTone(status: string | null): "default" | "warning" | "danger" {
  if (!status) return "default";
  const s = status.toUpperCase();
  if (["OUT", "O", "IL", "IL-LT", "NA", "SUSP"].includes(s)) return "danger";
  if (["INJ", "GTD", "DTD", "Q"].includes(s)) return "warning";
  return "default";
}

// ---------------------------------------------------------------------------
// Range presets
// ---------------------------------------------------------------------------

type Preset = {
  id: string;
  label: string;
  compute: () => { start: string; end: string };
};

function todayISO(): string {
  return toISODate(new Date());
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

const PRESETS: Preset[] = [
  {
    id: "l7",
    label: "Last 7",
    compute: () => ({ start: daysAgoISO(7), end: todayISO() }),
  },
  {
    id: "l14",
    label: "Last 14",
    compute: () => ({ start: daysAgoISO(14), end: todayISO() }),
  },
  {
    id: "l30",
    label: "Last 30",
    compute: () => ({ start: daysAgoISO(30), end: todayISO() }),
  },
  {
    id: "season",
    label: "Last 90",
    compute: () => ({ start: daysAgoISO(90), end: todayISO() }),
  },
  {
    id: "next7",
    label: "Next 7",
    compute: () => ({ start: todayISO(), end: daysAheadISO(7) }),
  },
  {
    id: "next14",
    label: "Next 14",
    compute: () => ({ start: todayISO(), end: daysAheadISO(14) }),
  },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function DateRangePicker({
  start,
  end,
  onChange,
}: {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1">
        {PRESETS.map((p) => {
          const r = p.compute();
          const active = r.start === start && r.end === end;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => onChange(r.start, r.end)}
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
          onChange={(e) => onChange(e.target.value || start, end)}
          className="h-8 rounded-md border border-foreground/10 bg-background px-2"
        />
        <label className="text-muted-foreground">to</label>
        <input
          type="date"
          value={end}
          onChange={(e) => onChange(start, e.target.value || end)}
          className="h-8 rounded-md border border-foreground/10 bg-background px-2"
        />
      </div>
    </div>
  );
}

function StatCell({
  label,
  value,
  emphasize = false,
}: {
  label: string;
  value: string;
  emphasize?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-foreground/10 bg-background/40 px-3 py-2 text-center",
        emphasize && "border-orange-500/30 bg-orange-500/[0.06]",
      )}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "mt-0.5 text-lg font-bold tabular-nums",
          emphasize && "text-orange-400",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function GameLogTable({
  rows,
  kind,
}: {
  rows: PlayerGameLogRow[] | PlayerProjectedGameRow[];
  kind: "actual" | "projected";
}) {
  if (rows.length === 0) {
    return (
      <p className="px-1 text-xs text-muted-foreground">
        No {kind === "actual" ? "games played" : "projected games"} in this
        range.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-md border border-foreground/10">
      <table className="w-full text-xs">
        <thead className="bg-foreground/[0.04] text-[10px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 text-left">Date</th>
            <th className="px-2 py-1.5 text-left">Opp</th>
            {kind === "actual" && (
              <>
                <th className="px-2 py-1.5 text-right">MIN</th>
                <th className="px-2 py-1.5 text-right">PTS</th>
                <th className="px-2 py-1.5 text-right">REB</th>
                <th className="px-2 py-1.5 text-right">AST</th>
                <th className="px-2 py-1.5 text-right">ST</th>
                <th className="px-2 py-1.5 text-right">BLK</th>
                <th className="px-2 py-1.5 text-right">TO</th>
              </>
            )}
            <th className="px-2 py-1.5 text-right">
              {kind === "actual" ? "FPS" : "Proj"}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((g, i) => {
            const homeStr =
              g.home === true ? "vs" : g.home === false ? "@" : "—";
            const fps =
              kind === "actual"
                ? (g as PlayerGameLogRow).fantasy_points
                : (g as PlayerProjectedGameRow).projected_fps;
            const stats =
              kind === "actual"
                ? (g as PlayerGameLogRow).stats
                : ({} as Record<string, number>);
            return (
              <tr
                key={`${g.date}-${i}`}
                className="border-t border-foreground/5"
              >
                <td className="px-2 py-1.5">{fmtDateShort(g.date)}</td>
                <td className="px-2 py-1.5">
                  {homeStr} {g.opponent ?? "—"}
                  {g.is_back_to_back && (
                    <span className="ml-1 rounded border border-amber-500/30 bg-amber-500/10 px-1 py-0.5 text-[8px] font-semibold uppercase tracking-wider text-amber-500">
                      B2B
                    </span>
                  )}
                </td>
                {kind === "actual" && (
                  <>
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                      {fmtNum((g as PlayerGameLogRow).minutes, 0)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtNum(stats.pts, 0)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtNum(stats.reb, 0)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtNum(stats.ast, 0)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtNum(stats.stl, 0)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtNum(stats.blk, 0)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtNum(stats.tov, 0)}
                    </td>
                  </>
                )}
                <td className="px-2 py-1.5 text-right font-semibold tabular-nums">
                  {fmtNum(fps)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main drawer
// ---------------------------------------------------------------------------

export function PlayerDetailDrawer({
  open,
  onOpenChange,
  leagueId,
  playerId,
  playerName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leagueId: number | null;
  playerId: number | null;
  playerName?: string;
}) {
  const [start, setStart] = useState<string>(daysAgoISO(30));
  const [end, setEnd] = useState<string>(todayISO());
  const [tab, setTab] = useState<"stats" | "schedule" | "news">("stats");

  const detailQ = useQuery<PlayerDetailResponse>({
    queryKey: ["player-detail", leagueId, playerId, start, end],
    queryFn: () =>
      api<PlayerDetailResponse>(
        `/api/players/${leagueId}/${playerId}?start=${start}&end=${end}`,
      ),
    enabled: open && !!leagueId && !!playerId,
  });

  const onPickRange = (s: string, e: string) => {
    setStart(s);
    setEnd(e);
  };

  const data = detailQ.data;
  const p = data?.player;
  const a = data?.actual;
  const proj = data?.projection;
  const tone = statusTone(p?.status ?? null);

  // Heuristic: if the range is entirely in the past, show actuals first.
  // If entirely future, show projection. Otherwise show both.
  const isFutureOnly = useMemo(() => {
    const todayD = new Date();
    return parseISO(start) > todayD;
  }, [start]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full overflow-y-auto sm:max-w-2xl"
      >
        <SheetHeader>
          <SheetTitle>{p?.name ?? playerName ?? "Player"}</SheetTitle>
          <SheetDescription>
            {p ? (
              <span className="flex flex-wrap items-center gap-2 text-xs">
                <span>{p.nba_team ?? "—"}</span>
                {p.eligible_positions.length > 0 && (
                  <span className="text-muted-foreground">
                    {p.eligible_positions.join(", ")}
                  </span>
                )}
                {p.status && (
                  <span
                    className={cn(
                      "rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
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
                {data?.ownership.state === "my_team" && (
                  <span className="rounded-full border border-orange-500/40 bg-orange-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-orange-400">
                    On my team
                  </span>
                )}
                {data?.ownership.state === "on_team" && data.ownership.team_name && (
                  <span className="text-[11px] text-muted-foreground">
                    on {data.ownership.team_name}
                  </span>
                )}
                {data?.ownership.state === "free_agent" && (
                  <span className="rounded-full border border-blue-500/40 bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-400">
                    Free agent
                  </span>
                )}
              </span>
            ) : (
              "Loading…"
            )}
            {p?.injury_note && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                {p.injury_note}
              </p>
            )}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 px-4 pb-6">
          {/* Date range picker */}
          <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Date range
            </div>
            <DateRangePicker start={start} end={end} onChange={onPickRange} />
          </section>

          {detailQ.isError && (
            <div className="rounded-md bg-red-500/10 p-3 text-xs text-red-400">
              {(detailQ.error as Error).message}
            </div>
          )}

          {/* Tab switcher */}
          <div className="flex flex-wrap gap-1 rounded-xl bg-card p-1 ring-1 ring-foreground/10">
            {(["stats", "schedule", "news"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium transition",
                  tab === t
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:bg-foreground/5",
                )}
              >
                {t === "stats"
                  ? "Stats"
                  : t === "schedule"
                  ? "Schedule"
                  : `News${data ? ` (${data.news.length})` : ""}`}
              </button>
            ))}
            {detailQ.isFetching && (
              <span className="ml-auto self-center text-[10px] text-muted-foreground">
                Loading…
              </span>
            )}
          </div>

          {tab === "stats" && (
            <section className="space-y-4">
              {/* Actuals summary (when range overlaps past) */}
              {!isFutureOnly && a && (
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Actual — {a.games_played} game
                    {a.games_played === 1 ? "" : "s"} played
                  </h3>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                    <StatCell
                      label="FPS/g"
                      value={fmtNum(a.fantasy_points_per_game)}
                      emphasize
                    />
                    <StatCell label="MIN" value={fmtNum(a.per_game.min, 1)} />
                    <StatCell label="PTS" value={fmtNum(a.per_game.pts)} />
                    <StatCell label="REB" value={fmtNum(a.per_game.reb)} />
                    <StatCell label="AST" value={fmtNum(a.per_game.ast)} />
                    <StatCell label="ST" value={fmtNum(a.per_game.stl)} />
                    <StatCell label="BLK" value={fmtNum(a.per_game.blk)} />
                    <StatCell label="TO" value={fmtNum(a.per_game.tov)} />
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                    <span>
                      Total FPS:{" "}
                      <span className="font-semibold text-foreground">
                        {fmtNum(a.fantasy_points_total)}
                      </span>
                    </span>
                    <span>
                      Totals — pts {fmtNum(a.totals.pts, 0)} / reb{" "}
                      {fmtNum(a.totals.reb, 0)} / ast {fmtNum(a.totals.ast, 0)}
                    </span>
                  </div>

                  <div className="mt-3">
                    <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Game log
                    </h4>
                    <GameLogTable rows={a.games_log} kind="actual" />
                  </div>
                </div>
              )}

              {/* Projection summary (when range overlaps future) */}
              {proj && proj.games_projected > 0 && (
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Projection — {proj.games_projected} game
                    {proj.games_projected === 1 ? "" : "s"} ahead
                  </h3>
                  <div className="grid grid-cols-3 gap-2">
                    <StatCell
                      label="Proj total"
                      value={fmtNum(proj.fantasy_points_total)}
                      emphasize
                    />
                    <StatCell
                      label="Proj/g"
                      value={fmtNum(proj.fantasy_points_per_game)}
                    />
                    <StatCell
                      label="Base per-game"
                      value={fmtNum(data?.base_projection_per_game)}
                    />
                  </div>
                  <div className="mt-3">
                    <GameLogTable rows={proj.games_log} kind="projected" />
                  </div>
                </div>
              )}

              {(!a || a.games_played === 0) &&
                (!proj || proj.games_projected === 0) && (
                  <div className="rounded-md bg-card p-6 text-center text-xs text-muted-foreground ring-1 ring-foreground/10">
                    No games found in this range. Try a wider window or a
                    different date.
                  </div>
                )}
            </section>
          )}

          {tab === "schedule" && (
            <section>
              {proj && proj.games_log.length > 0 ? (
                <>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Upcoming in range
                  </h3>
                  <GameLogTable rows={proj.games_log} kind="projected" />
                </>
              ) : a && a.games_log.length > 0 ? (
                <>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Games played
                  </h3>
                  <GameLogTable rows={a.games_log} kind="actual" />
                </>
              ) : (
                <p className="text-xs text-muted-foreground">
                  No games in this range.
                </p>
              )}
            </section>
          )}

          {tab === "news" && (
            <section className="space-y-2">
              {data && data.news.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No recent news.
                </p>
              )}
              {data?.news.map((n, i) => (
                <article
                  key={i}
                  className="rounded-md border border-foreground/10 bg-card p-3"
                >
                  <header className="flex items-baseline justify-between gap-2">
                    <h4 className="text-sm font-semibold">{n.title}</h4>
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(n.published_at).toLocaleDateString()}
                    </span>
                  </header>
                  {n.body && (
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-3">
                      {n.body}
                    </p>
                  )}
                  <footer className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span className="rounded border border-foreground/10 bg-foreground/5 px-1 py-0.5 uppercase tracking-wider">
                      {n.kind}
                    </span>
                    <span>{n.source}</span>
                    {n.url && (
                      <a
                        href={n.url}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-auto text-blue-400 hover:underline"
                      >
                        read ↗
                      </a>
                    )}
                  </footer>
                </article>
              ))}
            </section>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
