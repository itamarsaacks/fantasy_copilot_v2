"use client";

import { useQuery } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { api } from "@/lib/api";
import type { TeamPlayerView, TeamResponse } from "@/lib/api-types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// Order positions in the grid: guards → forwards → centers → bench/util → other
const POSITION_ORDER = ["G", "G,FC", "F", "FC", "C", "Util", "BN", "IR", "OTHER"];

function positionWeight(pos: string): number {
  const idx = POSITION_ORDER.indexOf(pos);
  return idx === -1 ? 99 : idx;
}

function formatFps(v: number | null): string {
  if (v === null) return "—";
  return v.toFixed(1);
}

function statusTone(status: string | null): "default" | "warning" | "danger" {
  if (!status) return "default";
  const s = status.toUpperCase();
  if (["OUT", "O", "IL", "IL-LT", "NA", "SUSP"].includes(s)) return "danger";
  if (["INJ", "GTD", "DTD", "Q"].includes(s)) return "warning";
  return "default";
}

function PlayerCard({ p }: { p: TeamPlayerView }) {
  const tone = statusTone(p.status);
  return (
    <Card size="sm" className="hover:ring-foreground/20 transition-shadow">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <CardTitle className="truncate text-sm font-semibold">
              {p.name}
            </CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {p.nba_team ?? "—"} · {p.eligible_positions.join("/")}
            </p>
          </div>
          {p.status && (
            <Badge
              variant="outline"
              className={cn(
                "shrink-0 text-[10px] uppercase tracking-wider",
                tone === "danger" &&
                  "border-red-500/40 bg-red-500/10 text-red-300",
                tone === "warning" &&
                  "border-amber-500/40 bg-amber-500/10 text-amber-300"
              )}
            >
              {p.status}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-3">
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <div>
            <div className="text-muted-foreground">FPS/g</div>
            <div className="text-base font-semibold tabular-nums">
              {formatFps(p.projected_fps_per_game)}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground">This week</div>
            <div className="text-base font-semibold tabular-nums">
              {p.games_this_week}
              {p.back_to_back_count > 0 && (
                <span className="ml-1 text-[10px] font-normal text-amber-400">
                  ({p.back_to_back_count} B2B)
                </span>
              )}
            </div>
          </div>
        </div>
        {p.injury_note && (
          <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground">
            {p.injury_note}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function PositionGroup({
  position,
  players,
}: {
  position: string;
  players: TeamPlayerView[];
}) {
  const groupFps = players.reduce(
    (acc, p) => acc + (p.projected_fps_per_game ?? 0),
    0
  );
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          {position}
          <span className="ml-2 text-xs font-normal text-muted-foreground/70">
            {players.length} {players.length === 1 ? "player" : "players"}
          </span>
        </h2>
        <span className="text-xs tabular-nums text-muted-foreground">
          {groupFps.toFixed(1)} fps/g total
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {players.map((p) => (
          <PlayerCard key={p.name} p={p} />
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
  const sortedPositions = Object.keys(t.by_position).sort(
    (a, b) => positionWeight(a) - positionWeight(b)
  );

  return (
    <div className="mx-auto max-w-7xl space-y-8 p-4 md:p-6">
      <header className="flex flex-col gap-1 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t.team_name}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t.manager_name ? `Manager: ${t.manager_name} · ` : ""}
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

      {sortedPositions.map((pos) => (
        <PositionGroup
          key={pos}
          position={pos}
          players={t.by_position[pos]}
        />
      ))}
    </div>
  );
}
