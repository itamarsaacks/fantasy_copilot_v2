"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageCircle,
  Calendar,
  Users,
  UserSquare,
  Trophy,
  ArrowLeftRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { RecentChats } from "@/components/shell/recent-chats";
import { useMe } from "@/lib/hooks/use-me";
import { FlaskConical } from "lucide-react";

// New tab order per master plan §1. /waivers folds into /trades as a
// sub-tab once the trades-waiver session builds it; the standalone
// /waivers route remains accessible until then so we don't break links.
const NAV_ITEMS = [
  { href: "/chat", label: "Chat", icon: MessageCircle },
  { href: "/games", label: "Games", icon: Calendar },
  { href: "/league", label: "League", icon: Trophy },
  { href: "/team", label: "My Team", icon: Users },
  { href: "/players", label: "Players", icon: UserSquare },
  { href: "/trades", label: "Trades", icon: ArrowLeftRight },
];

const ADMIN_NAV_ITEMS = [
  { href: "/eval", label: "Eval", icon: FlaskConical },
];

export function Sidebar() {
  const pathname = usePathname();
  const me = useMe();
  const isAdmin = !!me.data?.user?.is_admin;
  return (
    <aside
      className={cn(
        "hidden md:flex flex-col w-56 shrink-0",
        "bg-sidebar border-r border-sidebar-border",
        "h-dvh sticky top-0"
      )}
    >
      <div className="px-5 pt-6 pb-8">
        <div className="font-heading text-xl tracking-tight leading-none">
          Fantasy
          <span className="block text-primary">Copilot</span>
        </div>
        <div className="mt-1 text-[11px] uppercase tracking-widest text-muted-foreground">
          v2.0
        </div>
      </div>

      <nav className="px-2">
        <ul className="space-y-0.5">
          {NAV_ITEMS.map((item) => {
            const active =
              pathname === item.href || pathname?.startsWith(item.href + "/");
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                    active
                      ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                      : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  <span>{item.label}</span>
                  {active && (
                    <span className="ml-auto size-1.5 rounded-full bg-primary" />
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
        {isAdmin && (
          <>
            <div className="mt-4 px-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Admin
            </div>
            <ul className="mt-1 space-y-0.5">
              {ADMIN_NAV_ITEMS.map((item) => {
                const active =
                  pathname === item.href || pathname?.startsWith(item.href + "/");
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={cn(
                        "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                        active
                          ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                          : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
                      )}
                    >
                      <Icon className="size-4 shrink-0" />
                      <span>{item.label}</span>
                      {active && (
                        <span className="ml-auto size-1.5 rounded-full bg-primary" />
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </nav>

      {/* Recent chats — only visible while on /chat to keep other tabs
          uncluttered. Easy to lift later. */}
      {pathname?.startsWith("/chat") && <RecentChats />}

      <div className="px-5 py-3 border-t border-sidebar-border mt-auto">
        <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
          Local · Replay
        </div>
      </div>
    </aside>
  );
}
