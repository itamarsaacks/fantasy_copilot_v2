"use client";

import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ChatRequest, ChatResponse } from "@/lib/api-types";

export function useChat() {
  return useMutation<ChatResponse, Error, ChatRequest>({
    mutationFn: (body) => api<ChatResponse>("/api/chat", { method: "POST", body }),
  });
}
