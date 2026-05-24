"use client";

/**
 * Opponent roster dialog — opens when a user clicks any team row in the
 * League standings table. Shows that team's roster reconstructed for the
 * selected date via /api/teams/{team_id}/roster?date=YYYY-MM-DD.
 *
 * Caveats (acknowledged in the master plan §2.5):
 *   - Lineup slots (BN/PG/etc.) are NOT historically reconstructed —
 *     Yahoo doesn't expose that cleanly. We list the roster only.
 *   - `players.nba_team_abbr` is current; players who were traded
 *     mid-season will show their *current* team next to their name even
 *     on past dates (master plan §2.5b).
 *
 * Click a player row → opens the shared PlayerDrawer via DrawerProvider.
 *
 * Responsive: desktop side-modal-ish (~640px) / mobile full-screen sheet
 * (matches PlayerDrawer pattern).
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PlayerAvatar } from "@/components/shared/player-avatar";
import { TeamLogo } from "@/components/shared/team-logo";
import { useDrawer } from "@/components/shared/drawer-context";
import { api } from "@/lib/api";
import { formatDateHeadline, toISODate } from "@/lib/date-utils";
import { cn } from "@/lib/utils";
import type { StandingOnDate } from "@/lib/api-types";

type RosterPlayerView = {
  player_id: number;
  full_name: string;
  nba_team_abbr: string | null;
  headshot_path: string | null;
};

type TeamRosterResponse = {
  team_id: number;
  team_name: string;
  on_date: string;
  players: RosterPlayerView[];
};

export interface OpponentRosterDialogProps {
  /** Team to display. `null` → dialog closed. */
  team: StandingOnDate | null;
  /** Date the roster should be reconstructed for. */
  date: Date;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatFps(v: number | null): string {
  if (v === null) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

export function OpponentRosterDialog({
  team,
  date,
  open,
  onOpenChange,
}: OpponentRosterDialogProps) {
  const { openPlayer } = useDrawer();
  const dateISO = toISODate(date);
  const dateHeader = formatDateHeadline(date);

  const rosterQ = useQuery<TeamRosterResponse>({
    queryKey: ["opponent-roster", team?.team_id, dateISO],
    queryFn: () =>
      api<TeamRosterResponse>(
        `/api/teams/${team!.team_id}/roster?date=${dateISO}`,
      ),
    enabled: !!team && open,
    // Cache by date so toggling reuses
    staleTime: 60_000,
  });

  // Responsive sizing (mirror PlayerDrawer)
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(max-width: 640px)");
    const sync = () => setIsMobile(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  if (!team) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={
          isMobile
            ? "h-[92vh] w-[96vw] max-w-none overflow-y-auto rounded-xl p-4"
            : "max-h-[88vh] w-[min(640px,90vw)] max-w-none overflow-y-auto p-6"
        }
      >
        <DialogHeader>
          <DialogTitle>
            <span className="flex items-baseline gap-3">
              <span>{team.team_name}</span>
              {team.fps_on_date !== null && (
                <span className="text-base font-semibold tabular-nums text-orange-400">
                  {formatFps(team.fps_on_date)} FPS
                </span>
              )}
            </span>
          </DialogTitle>
          <DialogDescription>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {team.manager_name && <span>Manager: {team.manager_name}</span>}
              <span>·</span>
              <span>Roster on {dateHeader}</span>
              <span>·</span>
              <span>Season rank #{team.rank_on_date}</span>
            </span>
          </DialogDescription>
        </DialogHeader>

        <div className="mt-2">
          {rosterQ.isLoading && (
            <div className="py-12 text-center text-sm text-muted-foreground">
              Loading roster…
            </div>
          )}
          {rosterQ.isError && (
            <div className="py-12 text-center text-sm text-red-400">
              Couldn&apos;t load roster.
            </div>
          )}
          {rosterQ.data && rosterQ.data.players.length === 0 && (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No roster reconstructed for this date.
            </div>
          )}
          {rosterQ.data && rosterQ.data.players.length > 0 && (
            <>
              <p className="mb-2 px-1 text-[11px] text-muted-foreground">
                Lineup slots not reconstructed historically · NBA team shown is
                current
              </p>
              <ul className="divide-y divide-foreground/5">
                {rosterQ.data.players.map((p) => (
                  <li key={p.player_id}>
                    <button
                      type="button"
                      onClick={() => openPlayer(p.player_id, p.full_name)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-md px-2 py-2 text-left",
                        "transition hover:bg-foreground/5 active:bg-foreground/10",
                      )}
                    >
                      <PlayerAvatar
                        name={p.full_name}
                        headshotPath={p.headshot_path}
                        size={32}
                        className="shrink-0"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">
                          {p.full_name}
                        </div>
                      </div>
                      <div className="shrink-0">
                        <TeamLogo abbr={p.nba_team_abbr} size={24} />
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
