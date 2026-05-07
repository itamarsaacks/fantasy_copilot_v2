"use client";

import { ChatMarkdown } from "./markdown";
import { Loader2 } from "lucide-react";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: number;
  pending?: boolean;
};

export function Message({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="space-y-1">
        <div className="text-[11px] uppercase tracking-widest text-muted-foreground">
          You
        </div>
        <div className="text-[15px] leading-7 whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="size-1.5 rounded-full bg-primary" />
        <span className="font-heading text-[14px] tracking-tight text-foreground">
          Fantasy Copilot
        </span>
        {typeof message.toolCalls === "number" && message.toolCalls > 0 && (
          <span className="text-[11px] text-muted-foreground italic">
            · used {message.toolCalls} tool{message.toolCalls === 1 ? "" : "s"}
          </span>
        )}
      </div>
      {message.pending ? (
        <PendingIndicator />
      ) : (
        <ChatMarkdown content={message.content} />
      )}
    </div>
  );
}

function PendingIndicator() {
  return (
    <div className="flex items-center gap-2 text-muted-foreground italic text-sm py-1">
      <Loader2 className="size-3.5 animate-spin" />
      Thinking…
    </div>
  );
}
