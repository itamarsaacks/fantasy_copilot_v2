"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { api } from "@/lib/api";
import type {
  PlayerOwnership,
  PlayerSeasonStats,
  PlayerView,
  PlayersResponse,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { PlayerDetailDrawer } from "@/components/players/player-detail-drawer";
import { PlayerAvatar } from "@/components/shared/player-avatar";

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

const COMPARE_MAX = 4;

export function PlayersView() {
  const queryClient = useQueryClient();
  const { leagueId, league, isLoading: leagueLoading } = useActiveLeague();
  const [openPlayer, setOpenPlayer] = useState<{ id: number; name: string } | null>(null);
  // Compare cart — player ids selected via the row checkbox or per-row
  // Compare button. Cleared on league switch. Capped at COMPARE_MAX so
  // the compare view stays readable.
  const [compareIds, setCompareIds] = useState<number[]>([]);
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

  // Reset compare cart when leagueId changes (so you don't try to compare
  // players from another league).
  useEffect(() => {
    setCompareIds([]);
  }, [leagueId]);

  function toggleCompare(id: number) {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= COMPARE_MAX) return prev;
      return [...prev, id];
    });
  }

  // Warm the player-detail cache on hover so clicking feels instant.
  // Uses the default 30-day window the drawer opens with.
  function prefetchDetail(playerId: number) {
    if (!leagueId) return;
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);
    const toISO = (d: Date) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${day}`;
    };
    const s = toISO(start);
    const e = toISO(end);
    queryClient.prefetchQuery({
      queryKey: ["player-detail", leagueId, playerId, s, e],
      queryFn: () =>
        api(`/api/players/${leagueId}/${playerId}?start=${s}&end=${e}`),
      // Don't re-fetch on hover if we already have it
      staleTime: 60 * 1000,
    });
  }

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
        <div className="hidden grid-cols-[1.5rem_minmax(0,1fr)_repeat(6,3.5rem)_5rem_4rem] items-center gap-3 border-b border-foreground/10 px-4 py-2 md:grid">
          <span aria-hidden />
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
              onClick={() => setOpenPlayer({ id: p.id, name: p.name })}
              onHover={() => prefetchDetail(p.id)}
              compareSelected={compareIds.includes(p.id)}
              compareDisabled={
                !compareIds.includes(p.id) && compareIds.length >= COMPARE_MAX
              }
              onToggleCompare={() => toggleCompare(p.id)}
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

      <PlayerDetailDrawer
        open={openPlayer !== null}
        onOpenChange={(o) => !o && setOpenPlayer(null)}
        leagueId={leagueId}
        playerId={openPlayer?.id ?? null}
        playerName={openPlayer?.name}
      />

      {compareIds.length >= 1 && (
        <CompareBar
          ids={compareIds}
          items={items}
          onClear={() => setCompareIds([])}
          onRemove={(id) =>
            setCompareIds((prev) => prev.filter((x) => x !== id))
          }
        />
      )}
    </div>
  );
}

function CompareBar({
  ids,
  items,
  onClear,
  onRemove,
}: {
  ids: number[];
  items: PlayerView[];
  onClear: () => void;
  onRemove: (id: number) => void;
}) {
  // Resolve names from whatever we've loaded on this page. If a player
  // isn't on the current page they'll show as "#id" — fine for v1.
  const byId = useMemo(() => {
    const m = new Map<number, string>();
    for (const p of items) m.set(p.id, p.name);
    return m;
  }, [items]);
  const enoughToCompare = ids.length >= 2;
  return (
    <div className="fixed inset-x-0 bottom-4 z-40 mx-auto flex max-w-3xl flex-wrap items-center gap-2 rounded-xl border border-foreground/15 bg-card/95 px-4 py-2 shadow-lg backdrop-blur">
      <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Compare
      </span>
      <div className="flex flex-wrap gap-1">
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onRemove(id)}
            className="rounded-full border border-orange-500/40 bg-orange-500/10 px-2 py-0.5 text-xs font-medium text-orange-300 hover:bg-orange-500/20"
            title="Remove from comparison"
          >
            {byId.get(id) ?? `#${id}`} ✕
          </button>
        ))}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={onClear}
          className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-foreground/5"
        >
          Clear
        </button>
        {enoughToCompare ? (
          <Link
            href={`/players/compare?ids=${ids.join(",")}`}
            className="rounded-md bg-foreground px-3 py-1.5 text-xs font-semibold text-background hover:opacity-90"
          >
            Compare {ids.length} →
          </Link>
        ) : (
          <span className="rounded-md bg-foreground/10 px-3 py-1.5 text-xs font-medium text-muted-foreground">
            Pick at least one more
          </span>
        )}
      </div>
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
  onClick,
  onHover,
  compareSelected,
  compareDisabled,
  onToggleCompare,
}: {
  p: PlayerView;
  highlightSort: SortBy;
  isFetchingRefresh: boolean;
  onClick: () => void;
  onHover: () => void;
  compareSelected: boolean;
  compareDisabled: boolean;
  onToggleCompare: () => void;
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
      onClick={onClick}
      onMouseEnter={onHover}
      className={cn(
        "group/row cursor-pointer border-b border-foreground/5 px-3 py-3 last:border-b-0 transition hover:bg-foreground/[0.02] md:grid md:grid-cols-[1.5rem_minmax(0,1fr)_repeat(6,3.5rem)_5rem_4rem] md:items-center md:gap-3 md:px-4",
        isFetchingRefresh && "opacity-80",
        compareSelected && "bg-orange-500/[0.04]",
      )}
    >
      <input
        type="checkbox"
        checked={compareSelected}
        disabled={compareDisabled}
        onChange={onToggleCompare}
        onClick={(e) => e.stopPropagation()}
        title={
          compareDisabled
            ? "Compare cart is full (max 4)"
            : compareSelected
            ? "Remove from comparison"
            : "Add to comparison"
        }
        className="size-4 shrink-0 cursor-pointer accent-orange-500 disabled:cursor-not-allowed disabled:opacity-40"
      />
      {/* Name + meta column */}
      <div className="flex min-w-0 items-start gap-2.5">
        <PlayerAvatar
          name={p.name}
          headshotPath={p.headshot_path}
          size={32}
          className="mt-0.5 shrink-0"
        />
        <div className="min-w-0 flex-1">
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
          {/* Hover-revealed Compare button — discoverability counterpart
              to the checkbox on the left. Stops propagation so it doesn't
              also open the drawer. */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              if (!compareDisabled || compareSelected) onToggleCompare();
            }}
            disabled={compareDisabled}
            className={cn(
              "ml-auto inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-medium opacity-0 transition group-hover/row:opacity-100",
              compareSelected
                ? "border-orange-500/60 bg-orange-500/15 text-orange-300 opacity-100"
                : "border-foreground/15 bg-background hover:bg-foreground/5",
              compareDisabled && "cursor-not-allowed opacity-30",
            )}
            title={
              compareSelected
                ? "Remove from comparison"
                : compareDisabled
                ? "Compare cart is full (max 4)"
                : "Add to comparison"
            }
          >
            {compareSelected ? "✓ Compare" : "+ Compare"}
          </button>
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
