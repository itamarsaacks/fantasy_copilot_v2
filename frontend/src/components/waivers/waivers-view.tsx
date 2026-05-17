"use client";

import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { api } from "@/lib/api";
import type {
  SuggestedSwap,
  WaiverCandidate,
  WaiversResponse,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";

const WINDOW_OPTIONS = [3, 5, 7, 10, 14];

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

function formatWindowRange(start: string, end: string): string {
  try {
    const s = new Date(start + "T00:00:00");
    const e = new Date(end + "T00:00:00");
    const fmt = (d: Date) =>
      d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    return `${fmt(s)} – ${fmt(e)}`;
  } catch {
    return `${start} – ${end}`;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusPill({ status }: { status: string | null }) {
  if (!status) return null;
  const tone = statusTone(status);
  return (
    <span
      className={cn(
        "rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
        tone === "danger" && "border-red-500/40 bg-red-500/10 text-red-400",
        tone === "warning" &&
          "border-amber-500/40 bg-amber-500/10 text-amber-500",
        tone === "default" &&
          "border-foreground/15 bg-foreground/5 text-muted-foreground",
      )}
    >
      {status}
    </span>
  );
}

function CandidateRow({
  c,
  side,
}: {
  c: WaiverCandidate;
  side: "pickup" | "drop";
}) {
  const detail = side === "drop" ? c.selected_position : c.waiver_status;
  return (
    <div className="border-b border-foreground/5 px-4 py-3 last:border-b-0 transition hover:bg-foreground/[0.02]">
      <div className="flex items-baseline gap-2">
        <span className="truncate font-semibold">{c.name}</span>
        <StatusPill status={c.status} />
        {detail && (
          <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/80">
            {detail}
          </span>
        )}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">
        {c.nba_team ?? "—"} · {c.eligible_positions.join(", ") || "—"}
      </div>
      {c.injury_note && (
        <p className="mt-1 line-clamp-1 text-[11px] text-muted-foreground/80">
          {c.injury_note}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs">
        <div>
          <span className="text-muted-foreground">FPS/g </span>
          <span className="font-semibold tabular-nums">
            {formatFps(c.projected_fps_per_game)}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">Games </span>
          <span className="font-semibold tabular-nums">{c.games_in_window}</span>
        </div>
        {c.back_to_back_count > 0 && (
          <div>
            <span className="text-muted-foreground">B2B </span>
            <span className="font-semibold tabular-nums">{c.back_to_back_count}</span>
          </div>
        )}
        <div className="ml-auto">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Window fps
          </span>{" "}
          <span className="text-sm font-bold tabular-nums">
            {formatFps(c.window_fps)}
          </span>
        </div>
      </div>
    </div>
  );
}

function SuggestedSwapCard({ s }: { s: SuggestedSwap }) {
  return (
    <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/[0.04] p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-emerald-400">
          Net swing
        </span>
        <span className="text-lg font-bold tabular-nums text-emerald-400">
          +{s.delta_window_fps.toFixed(1)} fps
        </span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg bg-background/40 p-2.5 ring-1 ring-foreground/10">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Add
          </div>
          <div className="font-semibold">{s.pickup.name}</div>
          <div className="text-xs text-muted-foreground">
            {s.pickup.nba_team} · {s.pickup.games_in_window} games ·{" "}
            {formatFps(s.pickup.projected_fps_per_game)} fps/g
          </div>
        </div>
        <div className="rounded-lg bg-background/40 p-2.5 ring-1 ring-foreground/10">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Drop
          </div>
          <div className="font-semibold">{s.drop.name}</div>
          <div className="text-xs text-muted-foreground">
            {s.drop.nba_team ?? "—"} · {s.drop.games_in_window} games ·{" "}
            {formatFps(s.drop.projected_fps_per_game)} fps/g
            {s.drop.selected_position && ` · ${s.drop.selected_position}`}
          </div>
        </div>
      </div>
      <div className="mt-2 text-[11px] text-muted-foreground">
        Per-game delta: {s.delta_per_game >= 0 ? "+" : ""}
        {s.delta_per_game.toFixed(1)} fps
      </div>
    </div>
  );
}

function ColumnHeader({
  title,
  subtitle,
  count,
}: {
  title: string;
  subtitle: string;
  count: number;
}) {
  return (
    <header className="flex items-baseline justify-between border-b border-foreground/10 px-4 py-2">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider">
          {title}
        </h2>
        <p className="text-[11px] text-muted-foreground">{subtitle}</p>
      </div>
      <span className="text-xs text-muted-foreground">{count}</span>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function WaiversView() {
  const { leagueId, league, isLoading: leagueLoading } = useActiveLeague();
  const [windowDays, setWindowDays] = useState(7);

  const waiversQ = useQuery<WaiversResponse>({
    queryKey: ["waivers", leagueId, windowDays],
    queryFn: () =>
      api<WaiversResponse>(
        `/api/waivers/${leagueId}?days_ahead=${windowDays}&limit_pickups=15&limit_drops=15&limit_swaps=6`,
      ),
    enabled: !!leagueId,
    placeholderData: keepPreviousData,
  });

  if (leagueLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    );
  }

  const data = waiversQ.data;

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Waivers</h1>
          <p className="text-sm text-muted-foreground">
            Pickup recommendations and drop candidates for {league?.name}, ranked
            by projected fantasy points over the next {windowDays} days
            {data && ` (${formatWindowRange(data.window_start, data.window_end)})`}.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-1 rounded-xl bg-card p-1 ring-1 ring-foreground/10">
          {WINDOW_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setWindowDays(d)}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition",
                windowDays === d
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:bg-foreground/5",
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </header>

      {waiversQ.isError && (
        <div className="rounded-xl bg-card p-6 text-sm text-red-400 ring-1 ring-foreground/10">
          Couldn&apos;t load waivers: {(waiversQ.error as Error).message}
        </div>
      )}

      {/* Suggested swaps */}
      {data && data.suggested_swaps.length > 0 && (
        <section>
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider">
              Suggested swaps
            </h2>
            <span className="text-[11px] text-muted-foreground">
              Top combinations by net projected fps over the window
            </span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {data.suggested_swaps.map((s, i) => (
              <SuggestedSwapCard key={i} s={s} />
            ))}
          </div>
        </section>
      )}

      {data && data.suggested_swaps.length === 0 && !waiversQ.isLoading && (
        <section className="rounded-xl border border-dashed border-foreground/15 p-4 text-sm text-muted-foreground">
          No swap suggestions for this window. Either no free agent beats a
          player on your roster, or none of your players have games scheduled
          in this range.
        </section>
      )}

      {/* Two columns: pickups + drops */}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-xl bg-card ring-1 ring-foreground/10">
          <ColumnHeader
            title="Top pickups"
            subtitle="Free agents ranked by projected fps over the window"
            count={data?.pickups.length ?? 0}
          />
          <div>
            {data?.pickups.map((p) => (
              <CandidateRow key={p.player_id} c={p} side="pickup" />
            ))}
            {data && data.pickups.length === 0 && (
              <div className="p-6 text-sm text-muted-foreground">
                No free agents in this league.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-xl bg-card ring-1 ring-foreground/10">
          <ColumnHeader
            title="Drop candidates"
            subtitle="Your roster, worst window-fps first (IR excluded)"
            count={data?.drops.length ?? 0}
          />
          <div>
            {data?.drops.map((p) => (
              <CandidateRow key={p.player_id} c={p} side="drop" />
            ))}
            {data && data.drops.length === 0 && (
              <div className="p-6 text-sm text-muted-foreground">
                Nothing rosterable to drop.
              </div>
            )}
          </div>
        </section>
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Window fps = season per-game projection × games in the window ×
        availability factor (0 if OUT/IL, 0.7 if GTD, 1.0 otherwise). Stage 2
        will fold in opponent strength and minutes trend. Slot eligibility
        isn&apos;t enforced on swap suggestions yet — see the backlog.
      </p>
    </div>
  );
}
