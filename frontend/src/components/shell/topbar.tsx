"use client";

import { LeagueSwitcher } from "@/components/shell/league-switcher";
import { ReconnectBanner } from "@/components/shell/reconnect-banner";
import { Settings } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Topbar() {
  return (
    <header className="sticky top-0 z-20 bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70 border-b border-border">
      <div className="h-14 px-4 md:px-6 flex items-center gap-3">
        <LeagueSwitcher />
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="icon"
          aria-label="Settings"
          className="text-muted-foreground hover:text-foreground"
        >
          <Settings className="size-4" />
        </Button>
      </div>
      <ReconnectBanner />
    </header>
  );
}
