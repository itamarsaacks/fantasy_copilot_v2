"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { MeResponse } from "@/lib/api-types";

/**
 * Fetch the current user's profile + leagues. Returns null when unauthenticated.
 * Used by the shell to detect the auth state and which leagues to offer.
 */
export function useMe() {
  return useQuery<MeResponse | null>({
    queryKey: ["me"],
    queryFn: () => api<MeResponse>("/auth/me", { silent401: true }),
    staleTime: 60 * 1000,
  });
}
