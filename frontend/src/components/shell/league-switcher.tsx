"use client";

import { useActiveLeague } from "@/lib/hooks/use-active-league";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChevronDown, Check, Trophy } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

const SCORING_LABELS: Record<string, string> = {
  point: "Points · season-long",
  headpoint: "H2H · points",
  head: "H2H · categories",
  roto: "Rotisserie",
};

export function LeagueSwitcher() {
  const { leagues, league, select, isLoading } = useActiveLeague();

  if (isLoading) {
    return <Skeleton className="h-9 w-48" />;
  }

  if (!leagues.length) {
    return (
      <div className="text-sm text-muted-foreground italic">
        No leagues connected
      </div>
    );
  }

  return (
    <DropdownMenu>
      {/* DropdownMenuTrigger renders its OWN <button> (Base UI). Don't wrap
          it in another <Button asChild> — that produces nested <button>s.
          Style the trigger directly via className. */}
      <DropdownMenuTrigger
        className="inline-flex items-center gap-2 h-9 px-2 -ml-2 max-w-[280px] rounded-md
                   text-sm font-medium hover:bg-accent/60 transition-colors
                   focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
      >
        <Trophy className="size-4 text-primary shrink-0" />
        <span className="truncate">{league?.name ?? "Select league"}</span>
        <span className="text-muted-foreground text-xs font-normal hidden sm:inline">
          {league
            ? SCORING_LABELS[league.scoring_type] ?? league.scoring_type
            : ""}
        </span>
        <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        {/* Base UI requires Group as the parent of GroupLabel. */}
        <DropdownMenuGroup>
          <div className="px-2 py-1.5 text-[10px] uppercase tracking-widest text-muted-foreground">
            Your leagues
          </div>
          <DropdownMenuSeparator />
          {leagues.map((lg) => {
            const active = lg.league_key === league?.league_key;
            return (
              <DropdownMenuItem
                key={lg.league_key}
                onClick={() => select(lg.league_key)}
                className="flex items-start gap-2 py-2"
              >
                <Check
                  className={`size-4 mt-0.5 shrink-0 ${
                    active ? "opacity-100 text-primary" : "opacity-0"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate">{lg.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {SCORING_LABELS[lg.scoring_type] ?? lg.scoring_type} ·{" "}
                    {lg.num_teams} teams · {lg.season}
                  </div>
                </div>
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
