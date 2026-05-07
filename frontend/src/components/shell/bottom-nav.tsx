"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageCircle,
  Users,
  UserSquare,
  Trophy,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Mobile bottom nav: 5 items max (drop "Trades" — it's not in the MVP day-1 flow).
const NAV_ITEMS = [
  { href: "/chat", label: "Chat", icon: MessageCircle },
  { href: "/team", label: "Team", icon: Users },
  { href: "/players", label: "Players", icon: UserSquare },
  { href: "/league", label: "League", icon: Trophy },
  { href: "/waivers", label: "Waivers", icon: Sparkles },
];

export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      className={cn(
        "md:hidden fixed bottom-0 left-0 right-0 z-30",
        "bg-sidebar/95 backdrop-blur supports-[backdrop-filter]:bg-sidebar/80",
        "border-t border-sidebar-border",
        "pb-[env(safe-area-inset-bottom)]"
      )}
    >
      <ul className="flex items-stretch justify-around h-16">
        {NAV_ITEMS.map((item) => {
          const active =
            pathname === item.href || pathname?.startsWith(item.href + "/");
          const Icon = item.icon;
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                className={cn(
                  "flex flex-col items-center justify-center gap-1 h-full text-[11px] transition-colors",
                  active
                    ? "text-primary"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Icon className="size-5" />
                <span>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
