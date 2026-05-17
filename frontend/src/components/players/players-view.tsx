"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { api } from "@/lib/api";
import type {
  PlayerOwnership,
  PlayerSeasonStats,
  PlayerView,
  PlayersResponse,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Availability = "all" | "available" | "owned" | "my_team";
type SortBy = "proj" | "owned" | "pts" | "reb" | "ast" | "stl" | "blk" | "name";
type SortDir = "asc" | "desc";

const AVAIL_TABS: Array<{ id: Availability; label: string }> = [
  { id: "all", label: "All" },
  { id: "available", label: "Available" },
  { id: "owned", label: "Owned" },
  { id: "my_team", label: "My team" },
];

const SORT_COLS: Array<{ id: SortBy; label: string; numeric: boolean }> = [
  { id: "name", label: "Player", numeric: false },
  { id: "pts", label: "PTS", numeric: true },
  { id: "reb", label: "REB", numeric: true },
  { id: "ast", label: "AST", numeric: true },
  { id: "stl", label: "ST", numeric: true },
  { id: "blk", label: "BLK", numeric: true },
  { id: "owned", label: "Own %", numeric: true },
  { id: "proj", label: "Proj", numeric: true },
];

const PAGE_SIZE = 50;

function formatNum(v: number | null | undefined, digits = 1): string {
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

function ownershipBadge(o: PlayerOwnership): { label: string; tone: string } {
  if (o.state === "my_team") {
    return {
      label: "On my team",
      tone: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
    };
  }
  if (o.state === "on_team") {
    return {
      label: o.team_name ?? "Rostered",
      tone: "border-foreground/20 bg-foreground/5 text-muted-foreground",
    };
  }
  if (o.state === "waivers") {
    return {
      label: "Waivers",
      tone: "border-amber-500/40 bg-amber-500/10 text-amber-500",
    };
  }
  return {
    label: "Free agent",
    tone: "border-blue-500/40 bg-blue-500/10 text-blue-400",
  };
}

function statByCol(s: PlayerSeasonStats, col: SortBy): number | null {
  switch (col) {
    case "pts":
      return s.pts;
    case "reb":
      return s.reb;
    case "ast":
      return s.ast;
    case "stl":
      return s.stl;
    case "blk":
      return s.blk;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function PlayersView() {
  const { leagueId, league, isLoading: leagueLoading } = useActiveLeague();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [position, setPosition] = useState<string | null>(null);
  const [availability, setAvailability] = useState<Availability>("all");
  const [sortBy, setSortBy] = useState<SortBy>("proj");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [offset, setOffset] = useState(0);

  // Debounce the search box: 250ms after the last keystroke triggers a query.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  // Reset pagination whenever filters change.
  useEffect(() => {
    setOffset(0);
  }, [debouncedSearch, position, availability, sortBy, sortDir]);

  const params = useMemo(() => {
    const sp = new URLSearchParams();
    if (debouncedSearch) sp.set("search", debouncedSearch);
    if (position) sp.set("position", position);
    if (availability !== "all") sp.set("availability", availability);
    sp.set("sort_by", sortBy);
    sp.set("sort_dir", sortDir);
    sp.set("limit", String(PAGE_SIZE));
    sp.set("offset", String(offset));
    return sp.toString();
  }, [debouncedSearch, position, availability, sortBy, sortDir, offset]);

  const playersQ = useQuery<PlayersResponse>({
    queryKey: ["players", leagueId, params],
    queryFn: () => api<PlayersResponse>(`/api/players/${leagueId}?${params}`),
    enabled: !!leagueId,
    placeholderData: keepPreviousData,
  });

  function toggleSort(col: SortBy) {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      // Default: name asc, numeric desc
      setSortDir(col === "name" ? "asc" : "desc");
    }
  }

  if (leagueLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    );
  }

  const data = playersQ.data;
  const availablePositions = data?.available_positions ?? [];
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const canLoadMore = offset + items.length < total;

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Players</h1>
        <p className="text-sm text-muted-foreground">
          Every NBA player in {league?.name}. Search, filter, sort.
        </p>
      </header>

      {/* Search + position chips */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl bg-card p-3 ring-1 ring-foreground/10">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name…"
          className="h-9 flex-1 min-w-[12rem] rounded-md border border-foreground/10 bg-background px-3 text-sm"
        />
        <div className="flex flex-wrap items-center gap-1">
          <Chip
            label="All pos"
            active={position === null}
            onClick={() => setPosition(null)}
          />
          {availablePositions.map((p) => (
            <Chip
              key={p}
              label={p}
              active={position === p}
              onClick={() => setPosition(p)}
            />
          ))}
        </div>
      </div>

      {/* Availability tabs */}
      <div className="flex flex-wrap gap-1 rounded-xl bg-card p-1 ring-1 ring-foreground/10">
        {AVAIL_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setAvailability(t.id)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition",
              availability === t.id
                ? "bg-foreground/10 text-foreground"
                : "text-muted-foreground hover:bg-foreground/5",
            )}
          >
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex items-center px-3 text-xs text-muted-foreground">
          {playersQ.isLoading || playersQ.isFetching
            ? "Loading…"
            : `${items.length} of ${total}`}
        </div>
      </div>

      {/* Table */}
      <section className="rounded-xl bg-card ring-1 ring-foreground/10">
        {/* Header row — desktop only */}
        <div className="hidden grid-cols-[minmax(0,1fr)_repeat(6,3.5rem)_5rem_4rem] items-center gap-3 border-b border-foreground/10 px-4 py-2 md:grid">
          {SORT_COLS.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => toggleSort(c.id)}
              className={cn(
                "text-[10px] font-semibold uppercase tracking-wider transition",
                c.numeric ? "text-right tabular-nums" : "text-left",
                sortBy === c.id
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {c.label}
              {sortBy === c.id && (
                <span className="ml-1 opacity-70">
                  {sortDir === "desc" ? "↓" : "↑"}
                </span>
              )}
            </button>
          ))}
        </div>

        {playersQ.isError && (
          <div className="p-6 text-sm text-red-400">
            Couldn&apos;t load players: {(playersQ.error as Error).message}
          </div>
        )}
        {!playersQ.isError && items.length === 0 && !playersQ.isLoading && (
          <div className="p-6 text-sm text-muted-foreground">
            No players match these filters.
          </div>
        )}

        <div>
          {items.map((p) => (
            <PlayerRow
              key={p.id}
              p={p}
              highlightSort={sortBy}
              isFetchingRefresh={playersQ.isFetching && !playersQ.isLoading}
            />
          ))}
        </div>

        {canLoadMore && (
          <div className="flex justify-center border-t border-foreground/10 px-4 py-3">
            <button
              type="button"
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
              disabled={playersQ.isFetching}
              className="rounded-md border border-foreground/15 bg-background px-4 py-1.5 text-sm font-medium hover:bg-foreground/5 disabled:opacity-50"
            >
              {playersQ.isFetching ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-2.5 py-1 text-xs font-medium ring-1 transition",
        active
          ? "bg-foreground text-background ring-foreground"
          : "bg-background text-muted-foreground ring-foreground/15 hover:bg-foreground/5",
      )}
    >
      {label}
    </button>
  );
}

function PlayerRow({
  p,
  highlightSort,
  isFetchingRefresh,
}: {
  p: PlayerView;
  highlightSort: SortBy;
  isFetchingRefresh: boolean;
}) {
  const s = p.season_stats;
  const tone = statusTone(p.status);
  const own = ownershipBadge(p.ownership);

  const cells: Array<{ id: SortBy; value: string }> = [
    { id: "pts", value: formatNum(s.pts) },
    { id: "reb", value: formatNum(s.reb) },
    { id: "ast", value: formatNum(s.ast) },
    { id: "stl", value: formatNum(s.stl) },
    { id: "blk", value: formatNum(s.blk) },
    { id: "owned", value: p.percent_owned !== null ? `${p.percent_owned.toFixed(0)}%` : "—" },
    { id: "proj", value: formatNum(p.projected_fps_per_game) },
  ];

  return (
    <div
      className={cn(
        "border-b border-foreground/5 px-3 py-3 last:border-b-0 transition hover:bg-foreground/[0.02] md:grid md:grid-cols-[minmax(0,1fr)_repeat(6,3.5rem)_5rem_4rem] md:items-center md:gap-3 md:px-4",
        isFetchingRefresh && "opacity-80",
      )}
    >
      {/* Name + meta column */}
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-2">
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
          <span
            className={cn(
              "shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
              own.tone,
            )}
          >
            {own.label}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {p.nba_team ?? "—"} · {p.eligible_positions.join(", ") || "—"}
        </div>
        {p.injury_note && (
          <p className="mt-1 line-clamp-1 text-[11px] text-muted-foreground/80">
            {p.injury_note}
          </p>
        )}

        {/* Mobile: stats inline */}
        <div className="mt-2 grid grid-cols-7 gap-1 text-center md:hidden">
          {cells.map((c) => (
            <div key={c.id}>
              <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
                {SORT_COLS.find((sc) => sc.id === c.id)?.label}
              </div>
              <div
                className={cn(
                  "text-sm font-semibold tabular-nums",
                  highlightSort === c.id && "text-foreground",
                )}
              >
                {c.value}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Desktop: numeric columns */}
      {cells.map((c) => (
        <div
          key={c.id}
          className={cn(
            "hidden text-right text-sm tabular-nums md:block",
            highlightSort === c.id ? "font-bold text-foreground" : "font-medium text-foreground/90",
          )}
        >
          {c.value}
        </div>
      ))}
    </div>
  );
}
