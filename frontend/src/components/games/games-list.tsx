"use client";

import { useEffect, useState } from "react";

import { TeamLogo } from "@/components/shared/team-logo";
import { api, ApiError } from "@/lib/api";
import { toISODate } from "@/lib/date-utils";

type GameTeam = {
  abbr: string;
  score: number | null;
  is_home: boolean;
};

type GameSummary = {
  game_id: string;
  game_date: string;
  status: string | null;
  tipoff_at: string | null;
  home: GameTeam;
  away: GameTeam;
};

type GamesResponse = {
  date: string;
  games: GameSummary[];
};

export interface GamesListProps {
  date: Date;
  onSelectGame?: (gameId: string) => void;
}

export function GamesList({ date, onSelectGame }: GamesListProps) {
  const iso = toISODate(date);
  const [games, setGames] = useState<GameSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setGames(null);
    setError(null);
    api<GamesResponse>(`/api/games?date=${iso}`)
      .then((res) => {
        if (!cancelled) setGames(res.games);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [iso]);

  if (error) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        Failed to load games: {error}
      </div>
    );
  }

  if (games === null) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-lg bg-slate-100" />
        ))}
      </div>
    );
  }

  if (games.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
        No NBA games on {date.toLocaleDateString()}.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {games.map((g) => (
        <GameCard key={g.game_id} game={g} onClick={() => onSelectGame?.(g.game_id)} />
      ))}
    </div>
  );
}

function GameCard({ game, onClick }: { game: GameSummary; onClick?: () => void }) {
  const isFinal = (game.status || "").toLowerCase() === "final";
  const hasScores = game.home.score !== null && game.away.score !== null;
  const homeWon = hasScores && (game.home.score ?? 0) > (game.away.score ?? 0);
  const awayWon = hasScores && (game.away.score ?? 0) > (game.home.score ?? 0);

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full flex-col gap-1 rounded-lg border border-slate-200 bg-white p-4 text-left transition hover:border-slate-300 hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
    >
      <TeamRow team={game.away} won={awayWon} />
      <TeamRow team={game.home} won={homeWon} />
      <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
        <span>{statusLabel(game)}</span>
        <span className="opacity-0 group-hover:opacity-100">Box score →</span>
      </div>
    </button>
  );
}

function TeamRow({ team, won }: { team: GameTeam; won: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <TeamLogo abbr={team.abbr} size={24} />
        <span className={`text-sm ${won ? "font-semibold text-slate-900" : "text-slate-700"}`}>
          {team.abbr}
        </span>
      </div>
      <span
        className={`tabular-nums text-base ${
          team.score === null
            ? "text-slate-400"
            : won
              ? "font-semibold text-slate-900"
              : "text-slate-700"
        }`}
      >
        {team.score ?? "—"}
      </span>
    </div>
  );
}

function statusLabel(game: GameSummary): string {
  const s = (game.status || "").toLowerCase();
  if (s === "final") return "Final";
  if (s === "live" || s === "in_progress") return "Live";
  if (game.tipoff_at) {
    try {
      return new Date(game.tipoff_at).toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
      });
    } catch {
      return "Scheduled";
    }
  }
  return "Scheduled";
}
