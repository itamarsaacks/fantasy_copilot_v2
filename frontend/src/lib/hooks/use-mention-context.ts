"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { MentionContextResponse } from "@/lib/api-types";

/**
 * Fetch the league's player + team list used by `renderWithMentions` to
 * post-process agent replies into clickable chips. Stable per league for
 * the life of the session — players + team metadata change at most daily.
 */
export function useMentionContext(leagueId: number | null | undefined) {
  return useQuery<MentionContextResponse>({
    queryKey: ["mention-context", leagueId],
    queryFn: () =>
      api<MentionContextResponse>(`/api/players/${leagueId}/mention-context`),
    enabled: leagueId != null,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}
