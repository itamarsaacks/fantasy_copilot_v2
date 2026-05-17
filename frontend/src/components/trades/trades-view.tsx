"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { api } from "@/lib/api";
import type {
  TradePlayer,
  TradeTeam,
  TradesBuilderResponse,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";

function formatFps(v: number | null | undefined, digits = 1): string {
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

function sumFps(players: TradePlayer[]): number {
  return players.reduce((s, p) => s + (p.projected_fps_per_game ?? 0), 0);
}

function verdictLabel(delta: number): { label: string; tone: string } {
  if (delta > 5) return { label: "Favors you strongly", tone: "text-emerald-400" };
  if (delta > 1) return { label: "Favors you", tone: "text-emerald-400/90" };
  if (delta < -5) return { label: "Favors them strongly", tone: "text-red-400" };
  if (delta < -1) return { label: "Favors them", tone: "text-red-400/90" };
  return { label: "Roughly even", tone: "text-amber-400" };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PlayerCheckRow({
  p,
  selected,
  onToggle,
}: {
  p: TradePlayer;
  selected: boolean;
  onToggle: () => void;
}) {
  const tone = statusTone(p.status);
  return (
    <label
      className={cn(
        "flex cursor-pointer items-center gap-3 border-b border-foreground/5 px-3 py-2.5 last:border-b-0 transition",
        selected
          ? "bg-orange-500/[0.08] ring-1 ring-inset ring-orange-500/30"
          : "hover:bg-foreground/[0.02]",
      )}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="h-4 w-4 shrink-0 accent-orange-500"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-semibold">{p.name}</span>
          {p.status && (
            <span
              className={cn(
                "shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
                tone === "danger" && "border-red-500/40 bg-red-500/10 text-red-400",
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
        <div className="text-[11px] text-muted-foreground">
          {p.nba_team ?? "—"} ·{" "}
          {p.eligible_positions.length > 0
            ? p.eligible_positions.join(", ")
            : "—"}
          {p.selected_position && ` · slot ${p.selected_position}`}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="text-sm font-bold tabular-nums">
          {formatFps(p.projected_fps_per_game)}
        </div>
        <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
          fps/g
        </div>
      </div>
    </label>
  );
}

function TeamRosterColumn({
  team,
  selectedIds,
  onToggle,
  sideLabel,
}: {
  team: TradeTeam;
  selectedIds: Set<number>;
  onToggle: (player_id: number) => void;
  sideLabel: string;
}) {
  const selectedPlayers = team.players.filter((p) =>
    selectedIds.has(p.player_id),
  );
  const sum = sumFps(selectedPlayers);
  return (
    <section className="rounded-xl bg-card ring-1 ring-foreground/10">
      <header className="border-b border-foreground/10 px-4 py-2">
        <div className="flex items-baseline justify-between gap-2">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {sideLabel}
            </div>
            <h2 className="truncate text-sm font-semibold">{team.name}</h2>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Sum
            </div>
            <div className="text-lg font-bold tabular-nums">
              {sum.toFixed(1)}
            </div>
          </div>
        </div>
        {team.manager_name && (
          <p className="text-[11px] text-muted-foreground">
            {team.manager_name}
          </p>
        )}
      </header>
      <div className="max-h-[60vh] overflow-y-auto">
        {team.players.length === 0 && (
          <div className="p-6 text-sm text-muted-foreground">No players.</div>
        )}
        {team.players.map((p) => (
          <PlayerCheckRow
            key={p.player_id}
            p={p}
            selected={selectedIds.has(p.player_id)}
            onToggle={() => onToggle(p.player_id)}
          />
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function TradesView() {
  const { leagueId, isLoading: leagueLoading } = useActiveLeague();
  const tradesQ = useQuery<TradesBuilderResponse>({
    queryKey: ["trades-builder", leagueId],
    queryFn: () => api<TradesBuilderResponse>(`/api/trades/${leagueId}`),
    enabled: !!leagueId,
  });

  const [partnerId, setPartnerId] = useState<number | null>(null);
  const [giveIds, setGiveIds] = useState<Set<number>>(new Set());
  const [receiveIds, setReceiveIds] = useState<Set<number>>(new Set());

  // Default partner = first one when data loads.
  useEffect(() => {
    if (!tradesQ.data) return;
    if (partnerId === null && tradesQ.data.partners.length > 0) {
      setPartnerId(tradesQ.data.partners[0].team_id);
    }
  }, [tradesQ.data, partnerId]);

  // Clear receive-side selection if user switches partner.
  useEffect(() => {
    setReceiveIds(new Set());
  }, [partnerId]);

  const myTeam = tradesQ.data?.my_team ?? null;
  const partner = useMemo(() => {
    if (!tradesQ.data || partnerId === null) return null;
    return tradesQ.data.partners.find((t) => t.team_id === partnerId) ?? null;
  }, [tradesQ.data, partnerId]);

  function toggleGive(id: number) {
    setGiveIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleReceive(id: number) {
    setReceiveIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function resetSelections() {
    setGiveIds(new Set());
    setReceiveIds(new Set());
  }

  const givePlayers = useMemo(
    () =>
      myTeam ? myTeam.players.filter((p) => giveIds.has(p.player_id)) : [],
    [myTeam, giveIds],
  );
  const receivePlayers = useMemo(
    () =>
      partner ? partner.players.filter((p) => receiveIds.has(p.player_id)) : [],
    [partner, receiveIds],
  );

  const giveSum = sumFps(givePlayers);
  const receiveSum = sumFps(receivePlayers);
  const delta = receiveSum - giveSum;
  const verdict = verdictLabel(delta);
  const hasSelection = givePlayers.length > 0 || receivePlayers.length > 0;
  const countsMismatch =
    hasSelection && givePlayers.length !== receivePlayers.length;

  if (leagueLoading || tradesQ.isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    );
  }
  if (tradesQ.isError) {
    return (
      <div className="p-6 text-sm text-red-400">
        Couldn&apos;t load trade builder: {(tradesQ.error as Error).message}
      </div>
    );
  }
  if (!tradesQ.data) return null;
  if (!myTeam) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Your team wasn&apos;t found in this league.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Trade builder
          </h1>
          <p className="text-sm text-muted-foreground">
            Pick a trading partner, select players each side. Net fps shows
            who comes out ahead on per-game projection.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor="partner"
            className="text-xs font-medium uppercase tracking-wider text-muted-foreground"
          >
            Partner
          </label>
          <select
            id="partner"
            value={partnerId ?? ""}
            onChange={(e) =>
              setPartnerId(e.target.value ? Number(e.target.value) : null)
            }
            className="h-9 rounded-md border border-foreground/10 bg-background px-2 text-sm"
          >
            {tradesQ.data.partners.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.name}
                {t.manager_name ? ` — ${t.manager_name}` : ""}
              </option>
            ))}
          </select>
          {hasSelection && (
            <button
              type="button"
              onClick={resetSelections}
              className="h-9 rounded-md border border-foreground/15 px-3 text-xs font-medium hover:bg-foreground/5"
            >
              Reset
            </button>
          )}
        </div>
      </header>

      {/* Summary bar — always visible, even at zero, so users see what it does */}
      <section
        className={cn(
          "rounded-xl border p-4",
          hasSelection
            ? "border-orange-500/30 bg-orange-500/[0.04]"
            : "border-foreground/10 bg-card",
        )}
      >
        <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto]">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              You give
            </div>
            <div className="text-2xl font-bold tabular-nums">
              {giveSum.toFixed(1)}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {givePlayers.length} player{givePlayers.length === 1 ? "" : "s"}
            </div>
          </div>
          <div className="hidden self-center text-2xl text-muted-foreground md:block">
            →
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              You receive
            </div>
            <div className="text-2xl font-bold tabular-nums">
              {receiveSum.toFixed(1)}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {receivePlayers.length} player
              {receivePlayers.length === 1 ? "" : "s"}
            </div>
          </div>
          <div className="self-center text-right">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Net (per game)
            </div>
            <div
              className={cn(
                "text-3xl font-bold tabular-nums",
                delta > 0 && "text-emerald-400",
                delta < 0 && "text-red-400",
              )}
            >
              {delta > 0 ? "+" : ""}
              {delta.toFixed(1)}
            </div>
            {hasSelection && (
              <div className={cn("text-xs font-medium", verdict.tone)}>
                {verdict.label}
              </div>
            )}
          </div>
        </div>
        {countsMismatch && (
          <p className="mt-3 text-[11px] text-amber-400">
            Heads up — Yahoo trades typically need the same number of players
            on each side ({givePlayers.length} vs {receivePlayers.length}).
            You can still use this view for analysis; you&apos;d need to add
            another player on the smaller side to make it a real proposal.
          </p>
        )}
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <TeamRosterColumn
          team={myTeam}
          selectedIds={giveIds}
          onToggle={toggleGive}
          sideLabel="Give from"
        />
        {partner && (
          <TeamRosterColumn
            team={partner}
            selectedIds={receiveIds}
            onToggle={toggleReceive}
            sideLabel="Receive from"
          />
        )}
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Per-game projection comes from your league&apos;s cached projection
        engine. Doesn&apos;t factor in schedule density, slot eligibility, or
        whether you&apos;d still have a viable lineup — that&apos;s on the
        backlog. Use the chat tab for a deeper take on a specific proposal.
      </p>
    </div>
  );
}
