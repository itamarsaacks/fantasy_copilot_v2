"use client";

import { useConversations } from "@/lib/hooks/use-conversations";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { useChatThread } from "@/lib/hooks/use-chat-thread";
import { Plus, MessageCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

const RELATIVE_THRESHOLDS = [
  { unit: "minute", ms: 60_000, max: 60 },
  { unit: "hour", ms: 3_600_000, max: 24 },
  { unit: "day", ms: 86_400_000, max: 7 },
] as const;

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  if (diff < 0 || diff < 30_000) return "just now";
  for (const tier of RELATIVE_THRESHOLDS) {
    const n = Math.round(diff / tier.ms);
    if (n < tier.max) return `${n}${tier.unit[0]}`;
  }
  const days = Math.round(diff / 86_400_000);
  if (days < 30) return `${days}d`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function RecentChats() {
  const { league, leagueId } = useActiveLeague();
  const { data, isLoading } = useConversations(leagueId);
  const { activeThreadId, startNewChat, openThread } = useChatThread();

  if (!league) return null;

  return (
    <div className="px-2 mt-4 flex-1 min-h-0 flex flex-col">
      <div className="flex items-center justify-between px-3 mb-1">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          Recent
        </span>
        <button
          type="button"
          onClick={startNewChat}
          aria-label="New chat"
          className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-md hover:bg-sidebar-accent/60"
        >
          <Plus className="size-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto -mx-2 px-2 space-y-0.5">
        {isLoading ? (
          <div className="px-3 space-y-1.5">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-5/6" />
            <Skeleton className="h-6 w-4/6" />
          </div>
        ) : !data || data.length === 0 ? (
          <div className="px-3 text-[12px] text-muted-foreground italic">
            No conversations yet
          </div>
        ) : (
          data.map((c) => {
            const active = c.thread_id === activeThreadId;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => openThread(c.thread_id)}
                className={cn(
                  "w-full text-left flex items-start gap-2 px-3 py-1.5 rounded-md text-sm transition-colors group",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
                )}
              >
                <MessageCircle className="size-3.5 mt-0.5 shrink-0 opacity-60 group-hover:opacity-100" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] leading-tight">
                    {c.title}
                  </div>
                  <div className="text-[10px] text-muted-foreground/80 mt-0.5">
                    {relativeTime(c.last_message_at ?? c.created_at)}
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
