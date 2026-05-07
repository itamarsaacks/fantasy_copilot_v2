"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type ConversationListItem = {
  id: number;
  thread_id: string;
  title: string;
  last_message_at: string | null;
  created_at: string;
};

export type ConversationDetail = {
  id: number;
  thread_id: string;
  title: string;
  league_id: number;
  last_message_at: string | null;
  messages: Array<{
    role: "user" | "assistant" | "tool" | string;
    content: string;
    tool_name?: string | null;
  }>;
};

const KEY_LIST = (leagueId: number | null) => ["conversations", leagueId] as const;
const KEY_DETAIL = (id: number | null) => ["conversation", id] as const;

/** List recent conversations for the active league. */
export function useConversations(leagueId: number | null) {
  return useQuery<ConversationListItem[]>({
    queryKey: KEY_LIST(leagueId),
    enabled: leagueId !== null,
    queryFn: () =>
      api<ConversationListItem[]>(
        `/api/conversations?league_id=${leagueId}`,
        { silent401: true }
      ).then((rows) => rows ?? []),
    staleTime: 15 * 1000,
  });
}

export function useConversationDetail(conversationId: number | null) {
  return useQuery<ConversationDetail>({
    queryKey: KEY_DETAIL(conversationId),
    enabled: conversationId !== null,
    queryFn: () =>
      api<ConversationDetail>(`/api/conversations/${conversationId}`),
    staleTime: 0,
  });
}

export function useArchiveConversation() {
  const qc = useQueryClient();
  return useMutation<{ ok: boolean }, Error, number>({
    mutationFn: (id) =>
      api<{ ok: boolean }>(`/api/conversations/${id}`, { method: "DELETE" }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function invalidateConversations(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["conversations"] });
}
