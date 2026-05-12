"use client";

import { useQuery } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { api } from "@/lib/api";
import type {
  RosterBucket,
  TeamPlayerView,
  TeamResponse,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";

function formatFps(v: number | null): string {
  if (v === null) return "—";
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

function formatGameDate(iso: string): string {
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function GameCell({ player }: { player: TeamPlayerView }) {
  const g = player.next_game;
  if (!g) {
    return <span className="text-xs text-muted-foreground/60">No upcoming game</span>;
  }
  const homeSymbol = g.home ? "vs" : "@";
  const day = g.is_today ? "Today" : formatGameDate(g.date);
  const time = formatTipoff(g.tipoff_at);
  return (
    <div className="text-xs">
      <span className="text-foreground/80">
        {homeSymbol} {g.opponent}
      </span>
      <span className="ml-2 text-muted-foreground">
        {day}
        {time && ` · ${time}`}
      </span>
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

function PlayerRow({ p }: { p: TeamPlayerView }) {
  const tone = statusTone(p.status);
  const s = p.season_stats;
  return (
    <div className="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-foreground/5 px-3 py-3 last:border-b-0 hover:bg-foreground/[0.02]">
      {/* Slot */}
      <div className="text-center">
        <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {p.selected_position ?? "—"}
        </div>
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
                  "border-foreground/15 bg-foreground/5 text-muted-foreground"
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

      {/* Stat columns + fantasy total — desktop only */}
      <div className="hidden items-center gap-4 md:flex">
        <div className="grid grid-cols-6 gap-3">
          <StatCell label="PTS" value={s.pts} />
          <StatCell label="REB" value={s.reb} />
          <StatCell label="AST" value={s.ast} />
          <StatCell label="ST" value={s.stl} />
          <StatCell label="BLK" value={s.blk} />
          <StatCell label="TO" value={s.tov} />
        </div>
        <div className="w-14 border-l border-foreground/10 pl-3 text-right">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            FPS/g
          </div>
          <div className="text-base font-bold tabular-nums">
            {formatFps(p.projected_fps_per_game)}
          </div>
        </div>
      </div>

      {/* Mobile: compact stats inline */}
      <div className="md:hidden text-right">
        <div className="text-base font-bold tabular-nums">
          {formatFps(p.projected_fps_per_game)}
        </div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
          FPS/g
        </div>
      </div>
    </div>
  );
}

function MobileStatRow({ p }: { p: TeamPlayerView }) {
  const s = p.season_stats;
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

function Bucket({ bucket }: { bucket: RosterBucket }) {
  if (bucket.players.length === 0) return null;
  return (
    <section className="rounded-xl bg-card ring-1 ring-foreground/10">
      <header className="flex items-baseline justify-between border-b border-foreground/10 px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider">
          {bucket.label}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {bucket.players.length}{" "}
            {bucket.players.length === 1 ? "player" : "players"}
          </span>
        </h2>
        <span className="text-xs tabular-nums text-muted-foreground">
          {bucket.total_projected_fps_per_game.toFixed(1)} fps/g
        </span>
      </header>
      <div>
        {bucket.players.map((p) => (
          <div key={p.name}>
            <PlayerRow p={p} />
            <MobileStatRow p={p} />
          </div>
        ))}
      </div>
    </section>
  );
}

export function TeamView() {
  const { leagueId, league, isLoading: leagueLoading } = useActiveLeague();
  const teamQ = useQuery<TeamResponse>({
    queryKey: ["team", leagueId],
    queryFn: () => api<TeamResponse>(`/api/team/${leagueId}`),
    enabled: !!leagueId,
  });

  if (leagueLoading || teamQ.isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading roster…</div>
    );
  }
  if (teamQ.isError) {
    return (
      <div className="p-6 text-sm text-red-400">
        Couldn't load roster: {(teamQ.error as Error).message}
      </div>
    );
  }
  if (!teamQ.data) return null;
  const t = teamQ.data;

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
        <div className="rounded-lg bg-card px-3 py-2 ring-1 ring-foreground/10">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Total projected
          </div>
          <div className="text-xl font-semibold tabular-nums">
            {t.total_projected_fps_per_game.toFixed(1)}
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              fps/g
            </span>
          </div>
        </div>
      </header>

      <Bucket bucket={t.starters} />
      <Bucket bucket={t.bench} />
      <Bucket bucket={t.ir} />
    </div>
  );
}
