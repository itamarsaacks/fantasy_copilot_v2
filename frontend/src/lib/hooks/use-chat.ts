"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

export type ChatRequest = {
  message: string;
  league_id: number;
  thread_id?: string | null;
};

export type ChatResponse = {
  reply: string;
  tool_calls: number;
  league_name: string;
  thread_id: string;
  conversation_id: number;
  title: string;
};

export function useChat() {
  const qc = useQueryClient();
  return useMutation<ChatResponse, ApiError | Error, ChatRequest>({
    mutationFn: (body) =>
      api<ChatResponse>("/api/chat", { method: "POST", body }),
    onSuccess: () => {
      // Refresh the recent-chats sidebar — title or last_message_at may have changed.
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}
