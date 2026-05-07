"use client";

import { useActiveLeague } from "@/lib/hooks/use-active-league";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChevronDown, Check, Trophy } from "lucide-react";
import { Button } from "@/components/ui/button";
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
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="h-9 px-2 -ml-2 gap-2 max-w-[280px]"
        >
          <Trophy className="size-4 text-primary shrink-0" />
          <span className="font-medium truncate">{league?.name ?? "Select league"}</span>
          <span className="text-muted-foreground text-xs hidden sm:inline">
            {league
              ? SCORING_LABELS[league.scoring_type] ?? league.scoring_type
              : ""}
          </span>
          <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel className="text-xs uppercase tracking-wide text-muted-foreground">
          Your leagues
        </DropdownMenuLabel>
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
                className={`size-4 mt-0.5 shrink-0 ${active ? "opacity-100 text-primary" : "opacity-0"}`}
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
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
