"use client";

/**
 * Games tab — Phase 2 scoreboard.
 *
 * Sub-tabs: Scores (per-day scoreboard) + NBA Standings.
 * NBA standings endpoint ships in Phase 4. Box-score drill-in ships in Phase 3.
 */

import { useEffect, useState } from "react";

import { DateToggle } from "@/components/shared/date-toggle";
import { GamesList } from "@/components/games/games-list";
import { GameBoxModal } from "@/components/games/game-box-modal";
import { NestedTabs } from "@/components/shared/nested-tabs";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { useAppToday } from "@/lib/hooks/use-app-today";
import { toISODate } from "@/lib/date-utils";

export default function GamesPage() {
  const { today: appToday, loading } = useAppToday();
  const { leagueId } = useActiveLeague();
  const [date, setDate] = useState<Date | null>(null);
  const [tab, setTab] = useState("scores");
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null);

  useEffect(() => {
    if (appToday && !date) setDate(appToday);
  }, [appToday, date]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between gap-4">
          <h1 className="text-2xl font-semibold tracking-tight">Games</h1>
          {date ? (
            <div className="flex items-center gap-2">
              <DateToggle value={date} onChange={setDate} maxDate={appToday ?? undefined} />
              <button
                type="button"
                onClick={() => appToday && setDate(appToday)}
                disabled={!appToday || toISODate(date) === toISODate(appToday)}
                className="inline-flex h-10 items-center rounded-md border border-slate-200 px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-30 disabled:hover:bg-transparent"
                aria-label="Jump to today"
              >
                Today
              </button>
            </div>
          ) : (
            <div className="h-10 w-[320px] animate-pulse rounded-md bg-slate-100" />
          )}
        </div>

        <NestedTabs
          items={[
            { id: "scores", label: "Scores" },
            { id: "standings", label: "NBA Standings" },
          ]}
          activeId={tab}
          onChange={setTab}
          className="mb-6"
        />

        {tab === "scores" ? (
          <ScoresPanel
            date={date}
            loading={loading}
            onSelectGame={setSelectedGameId}
          />
        ) : (
          <StandingsPanel />
        )}
      </div>
      {selectedGameId && (
        <GameBoxModal
          gameId={selectedGameId}
          leagueId={leagueId}
          onClose={() => setSelectedGameId(null)}
        />
      )}
    </div>
  );
}

function ScoresPanel({
  date,
  loading,
  onSelectGame,
}: {
  date: Date | null;
  loading: boolean;
  onSelectGame: (id: string) => void;
}) {
  if (loading || !date) {
    return <div className="h-48 animate-pulse rounded-lg bg-slate-100" />;
  }
  return <GamesList date={date} onSelectGame={onSelectGame} />;
}

function StandingsPanel() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
      NBA standings — coming in Phase 4.
    </div>
  );
}
