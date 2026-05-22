"use client";

import { useEffect, useState } from "react";

import { PlayerAvatar } from "@/components/shared/player-avatar";
import { TeamLogo } from "@/components/shared/team-logo";
import { useDrawer } from "@/components/shared/drawer-context";
import { api, ApiError } from "@/lib/api";

type BoxLine = {
  player_id: number;
  full_name: string;
  nba_team_abbr: string | null;
  headshot_path: string | null;
  minutes: number | null;
  stats: Record<string, number>;
  fantasy_points: number | null;
  did_not_play: boolean;
};

type BoxResponse = {
  game_id: string;
  game_date: string;
  home_abbr: string;
  away_abbr: string;
  home: BoxLine[];
  away: BoxLine[];
};

// Yahoo NBA stat id → column label. Keep this list tight — wide tables get unreadable.
const STAT_COLS: Array<{ id: string; label: string; fmt?: (v: number) => string }> = [
  { id: "12", label: "PTS" },
  { id: "15", label: "REB" },
  { id: "16", label: "AST" },
  { id: "17", label: "ST" },
  { id: "18", label: "BLK" },
  { id: "19", label: "TO" },
];

const fmt1 = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

export interface GameBoxModalProps {
  gameId: string;
  leagueId: number | null;
  onClose: () => void;
}

export function GameBoxModal({ gameId, leagueId, onClose }: GameBoxModalProps) {
  const [data, setData] = useState<BoxResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    const qs = leagueId != null ? `?league_id=${leagueId}` : "";
    api<BoxResponse>(`/api/games/${gameId}/box${qs}`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [gameId, leagueId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4 sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <div className="text-sm font-semibold text-slate-800">Box score</div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
            aria-label="Close box score"
          >
            ✕
          </button>
        </div>

        <div className="min-h-[200px] overflow-y-auto px-5 py-4">
          {error ? (
            <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
              Failed to load box score: {error}
            </div>
          ) : !data ? (
            <BoxSkeleton />
          ) : data.home.length === 0 && data.away.length === 0 ? (
            <div className="rounded-md border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-600">
              No box-score data for this game yet.
            </div>
          ) : (
            <div className="space-y-6">
              <TeamBox abbr={data.away_abbr} lines={data.away} />
              <TeamBox abbr={data.home_abbr} lines={data.home} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TeamBox({ abbr, lines }: { abbr: string; lines: BoxLine[] }) {
  const drawer = useDrawer();
  const played = lines.filter((l) => !l.did_not_play);
  const dnp = lines.filter((l) => l.did_not_play);

  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <TeamLogo abbr={abbr} size={24} />
        <h3 className="text-base font-semibold text-slate-900">{abbr}</h3>
        <span className="text-xs text-slate-500">{played.length} played</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
              <th className="py-2 pr-2 font-medium">Player</th>
              <th className="px-2 py-2 text-right font-medium">MIN</th>
              {STAT_COLS.map((c) => (
                <th key={c.id} className="px-2 py-2 text-right font-medium">
                  {c.label}
                </th>
              ))}
              <th className="px-2 py-2 text-right font-medium">FPS</th>
            </tr>
          </thead>
          <tbody>
            {played.map((line) => (
              <tr
                key={line.player_id}
                className="cursor-pointer border-b border-slate-100 last:border-b-0 hover:bg-slate-50"
                onClick={() => drawer.openPlayer(line.player_id, line.full_name)}
              >
                <td className="py-2 pr-2">
                  <div className="flex items-center gap-2">
                    <PlayerAvatar
                      name={line.full_name}
                      headshotPath={line.headshot_path}
                      size={24}
                    />
                    <span className="font-medium text-slate-800">{line.full_name}</span>
                  </div>
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-slate-700">
                  {line.minutes != null ? fmt1(line.minutes) : "—"}
                </td>
                {STAT_COLS.map((c) => (
                  <td
                    key={c.id}
                    className="px-2 py-2 text-right tabular-nums text-slate-700"
                  >
                    {line.stats[c.id] != null ? fmt1(line.stats[c.id]) : "—"}
                  </td>
                ))}
                <td className="px-2 py-2 text-right tabular-nums font-semibold text-slate-900">
                  {line.fantasy_points != null ? line.fantasy_points.toFixed(1) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {dnp.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          DNP: {dnp.map((l) => l.full_name).join(", ")}
        </div>
      )}
    </section>
  );
}

function BoxSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="h-8 animate-pulse rounded bg-slate-100" />
      ))}
    </div>
  );
}
