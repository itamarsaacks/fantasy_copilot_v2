"use client";

/**
 * Games tab — Phase 1 skeleton.
 *
 * Sub-tabs: Scores (per-day scoreboard) + NBA Standings.
 * Real content lands in later phases — see docs/plans/games.md.
 *
 * Backend endpoints already in place:
 *   GET /api/games?date=YYYY-MM-DD
 *   GET /api/games/{game_id}/box?league_id=N
 * NBA standings endpoint ships in Phase 4.
 */

import { useEffect, useState } from "react";

import { DateToggle } from "@/components/shared/date-toggle";
import { NestedTabs } from "@/components/shared/nested-tabs";
import { useAppToday } from "@/lib/hooks/use-app-today";

export default function GamesPage() {
  const { today: appToday, loading } = useAppToday();
  const [date, setDate] = useState<Date | null>(null);
  const [tab, setTab] = useState("scores");

  useEffect(() => {
    if (appToday && !date) setDate(appToday);
  }, [appToday, date]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between gap-4">
          <h1 className="text-2xl font-semibold tracking-tight">Games</h1>
          {date ? (
            <DateToggle value={date} onChange={setDate} maxDate={appToday ?? undefined} />
          ) : (
            <div className="h-10 w-[228px] animate-pulse rounded-md bg-slate-100" />
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
          <ScoresPanel date={date} loading={loading} />
        ) : (
          <StandingsPanel />
        )}
      </div>
    </div>
  );
}

function ScoresPanel({ date, loading }: { date: Date | null; loading: boolean }) {
  if (loading || !date) {
    return <PanelSkeleton />;
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
      Scoreboard for {date.toLocaleDateString()} — coming in Phase 2.
    </div>
  );
}

function StandingsPanel() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
      NBA standings — coming in Phase 4.
    </div>
  );
}

function PanelSkeleton() {
  return <div className="h-48 animate-pulse rounded-lg bg-slate-100" />;
}
