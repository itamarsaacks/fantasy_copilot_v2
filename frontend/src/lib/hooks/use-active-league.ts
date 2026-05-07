"use client";

import { useEffect, useState } from "react";
import { useMe } from "@/lib/hooks/use-me";

const LS_KEY = "fc.activeLeagueKey";

/**
 * Tracks which league the user is currently viewing. Persists in localStorage.
 * Falls back to the first league if no preference is stored or the stored
 * one no longer exists.
 */
export function useActiveLeague() {
  const me = useMe();
  const [activeKey, setActiveKey] = useState<string | null>(null);

  useEffect(() => {
    if (!me.data?.leagues?.length) return;
    const stored =
      typeof window !== "undefined" ? window.localStorage.getItem(LS_KEY) : null;
    const valid = me.data.leagues.find((l) => l.league_key === stored);
    setActiveKey(valid?.league_key ?? me.data.leagues[0].league_key);
  }, [me.data]);

  const select = (leagueKey: string) => {
    setActiveKey(leagueKey);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LS_KEY, leagueKey);
    }
  };

  const league = me.data?.leagues.find((l) => l.league_key === activeKey) ?? null;

  return {
    leagues: me.data?.leagues ?? [],
    league,
    activeKey,
    leagueId: league?.id ?? null,
    select,
    isLoading: me.isLoading,
  };
}
