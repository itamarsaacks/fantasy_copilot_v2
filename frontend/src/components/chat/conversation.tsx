"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { useMe } from "@/lib/hooks/use-me";
import { useChat } from "@/lib/hooks/use-chat";
import { useChatThread } from "@/lib/hooks/use-chat-thread";
import { api } from "@/lib/api";
import type { ConversationDetail } from "@/lib/hooks/use-conversations";
import { Composer } from "./composer";
import { Message, type ChatMessage } from "./message";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { buttonVariants } from "@/components/ui/button";

const SUGGESTIONS = [
  "Where am I ranked in this league?",
  "Top 5 free agents worth picking up",
  "What's on my roster right now?",
  "Did I make the playoffs?",
];

function newId() {
  return Math.random().toString(36).slice(2, 10);
}

export function Conversation() {
  const me = useMe();
  const { league, leagueId } = useActiveLeague();
  const chat = useChat();
  const { activeThreadId, setActiveThreadId, newChatRequestId } = useChatThread();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages]);

  // Wipe conversation + thread when the league changes — different DB context.
  const leagueKey = league?.league_key ?? null;
  const lastLeagueKey = useRef<string | null>(null);
  useEffect(() => {
    if (lastLeagueKey.current && lastLeagueKey.current !== leagueKey) {
      setMessages([]);
      setActiveThreadId(null);
    }
    lastLeagueKey.current = leagueKey;
  }, [leagueKey, setActiveThreadId]);

  // "New chat" button (in sidebar) bumps newChatRequestId — clear here.
  const lastNewChatId = useRef<number>(newChatRequestId);
  useEffect(() => {
    if (lastNewChatId.current !== newChatRequestId) {
      setMessages([]);
      lastNewChatId.current = newChatRequestId;
    }
  }, [newChatRequestId]);

  // When the user clicks an existing conversation in the sidebar, fetch its
  // history and load it into the message list.
  const conversationDetailQuery = useQuery<ConversationDetail | null>({
    queryKey: ["conversation-by-thread", activeThreadId],
    enabled: !!activeThreadId,
    queryFn: async () => {
      // We have thread_id but need the numeric id for the detail endpoint.
      // List + match. Fine since the list is already cached.
      const list = await api<{ id: number; thread_id: string }[]>(
        `/api/conversations?league_id=${leagueId}`
      );
      const match = list.find((c) => c.thread_id === activeThreadId);
      if (!match) return null;
      return api<ConversationDetail>(`/api/conversations/${match.id}`);
    },
    staleTime: 0,
  });

  // Hydrate messages from server when a thread is opened.
  const lastHydratedThread = useRef<string | null>(null);
  useEffect(() => {
    if (!activeThreadId) return;
    if (lastHydratedThread.current === activeThreadId) return;
    if (!conversationDetailQuery.data) return;
    const hydrated: ChatMessage[] = conversationDetailQuery.data.messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .filter((m) => m.content && m.content.trim().length > 0)
      .map((m) => ({
        id: newId(),
        role: m.role as "user" | "assistant",
        content: m.content,
      }));
    setMessages(hydrated);
    lastHydratedThread.current = activeThreadId;
  }, [activeThreadId, conversationDetailQuery.data]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || !me.data?.user || !league || !leagueId) return;

    const userMsg: ChatMessage = {
      id: newId(),
      role: "user",
      content: text.trim(),
    };
    const pendingMsg: ChatMessage = {
      id: newId(),
      role: "assistant",
      content: "",
      pending: true,
    };
    setMessages((m) => [...m, userMsg, pendingMsg]);
    setDraft("");

    try {
      const res = await chat.mutateAsync({
        message: text,
        league_id: leagueId,
        thread_id: activeThreadId ?? undefined,
      });
      // Adopt the thread_id the server tells us (new conversations need this).
      if (res.thread_id !== activeThreadId) {
        setActiveThreadId(res.thread_id);
        lastHydratedThread.current = res.thread_id;
      }
      setMessages((m) =>
        m.map((msg) =>
          msg.id === pendingMsg.id
            ? { ...msg, content: res.reply, toolCalls: res.tool_calls, pending: false }
            : msg
        )
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      setMessages((m) =>
        m.map((msg) =>
          msg.id === pendingMsg.id
            ? { ...msg, content: `_Error:_ ${message}`, pending: false }
            : msg
        )
      );
      toast.error(message);
    }
  };

  // Three states: not signed in (no /auth/me), signed in but no leagues (rare),
  // signed in with leagues (the normal path).
  const isUnauthenticated = !me.isLoading && !me.data;

  return (
    <div className="flex flex-col h-full">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-4 md:px-8 py-8 md:py-12">
          {isUnauthenticated ? (
            <SignInPrompt />
          ) : messages.length === 0 ? (
            <EmptyState
              leagueName={league?.name}
              onPick={(s) => sendMessage(s)}
              disabled={!league || chat.isPending}
            />
          ) : (
            <div className="space-y-8">
              {messages.map((msg) => (
                <Message key={msg.id} message={msg} />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-border bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
        <div className="max-w-2xl mx-auto px-4 md:px-8 py-4">
          <Composer
            value={draft}
            onChange={setDraft}
            onSubmit={() => sendMessage(draft)}
            disabled={!league}
            pending={chat.isPending}
            placeholder={
              league
                ? `Ask anything about ${league.name}…`
                : "Connect a league to start"
            }
          />
          <div className="mt-2 px-2 flex items-center justify-between text-[11px] text-muted-foreground">
            <span>
              <kbd className="font-mono text-[10px] bg-muted px-1 py-0.5 rounded">
                Enter
              </kbd>{" "}
              to send · <kbd className="font-mono text-[10px] bg-muted px-1 py-0.5 rounded">Shift+Enter</kbd> for new line
            </span>
            {league && (
              <span className="hidden sm:inline">
                replying about <span className="text-foreground">{league.name}</span>
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function SignInPrompt() {
  return (
    <div className="py-16 md:py-24 space-y-8">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 text-xs uppercase tracking-widest text-primary">
          <Sparkles className="size-3.5" />
          Fantasy Copilot
        </div>
        <h1 className="font-heading text-3xl md:text-4xl leading-tight tracking-tight text-foreground">
          Sign in with Yahoo to{" "}
          <span className="italic text-primary">talk to your team.</span>
        </h1>
        <p className="text-muted-foreground text-[15px] leading-7 max-w-xl">
          I'll pull your roster, league rules, free agents, and projections.
          Read-only access — I never post on your behalf.
        </p>
      </div>
      <div>
        <a
          href="/auth/yahoo/login"
          className={buttonVariants({ size: "lg" }) + " h-11 px-5"}
        >
          Connect Yahoo
        </a>
      </div>
    </div>
  );
}

function EmptyState({
  leagueName,
  onPick,
  disabled,
}: {
  leagueName?: string;
  onPick: (s: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="py-16 md:py-24 space-y-8">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 text-xs uppercase tracking-widest text-primary">
          <Sparkles className="size-3.5" />
          Fantasy Copilot
        </div>
        <h1 className="font-heading text-3xl md:text-4xl leading-tight tracking-tight text-foreground">
          {leagueName ? (
            <>
              What would you like to know about{" "}
              <span className="italic text-primary">{leagueName}</span>?
            </>
          ) : (
            <>What would you like to know about your team?</>
          )}
        </h1>
        <p className="text-muted-foreground text-[15px] leading-7 max-w-xl">
          I have your roster, league rules, free agents, and projections.
          I'll never make up a stat — every number comes from a real lookup.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            disabled={disabled}
            className="px-3 py-1.5 text-sm rounded-full border border-border bg-card hover:border-primary/40 hover:text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
