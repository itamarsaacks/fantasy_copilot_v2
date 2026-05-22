"use client";

/**
 * Games tab — placeholder route.
 *
 * The full implementation ships in the dedicated session (`/tab-session
 * games`, branch `feature/games-tab`). See docs/plans/games.md for the
 * phase plan. This stub exists so the new sidebar entry doesn't 404 +
 * to give the next session a starting file.
 *
 * Data is already available — backend endpoints exist:
 *   GET /api/games?date=YYYY-MM-DD
 *   GET /api/games/{game_id}/box?league_id=N
 * Frontend primitives are ready: <DateToggle/>, <TeamLogo/>, <PlayerAvatar/>,
 * <PlayerChip/>, <NestedTabs/>, <DrawerProvider/> (via app shell).
 */

import { useEffect, useState } from "react";

import { DateToggle } from "@/components/shared/date-toggle";
import { NestedTabs } from "@/components/shared/nested-tabs";
import { useAppToday } from "@/lib/hooks/use-app-today";

export default function GamesPage() {
  const { today: appToday } = useAppToday();
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
          {date && (
            <DateToggle value={date} onChange={setDate} maxDate={appToday ?? undefined} />
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

        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center text-slate-600">
          <div className="text-base font-medium">Games tab — coming soon</div>
          <div className="mt-2 max-w-md mx-auto text-sm text-slate-500">
            This route is a placeholder so the new sidebar entry resolves.
            The full Games tab (scoreboard with team logos, click-game → box
            score, click-player → drawer, NBA standings sub-tab) builds in
            the next dedicated session — see <code>docs/plans/games.md</code>.
          </div>
          <div className="mt-4 text-xs text-slate-400">
            Wanted date: {date?.toLocaleDateString() ?? "—"} · Active sub-tab: {tab}
          </div>
        </div>
      </div>
    </div>
  );
}
