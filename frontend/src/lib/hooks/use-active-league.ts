"use client";

/**
 * Cross-mount store for the active league key.
 *
 * Why this is module-level: the previous per-component `useState` pattern
 * caused a brief `activeKey=null` window on every component remount (while
 * the useEffect re-read from localStorage). Anything that observed
 * "leagueKey transitioned to null" would mis-fire — e.g. the chat-reset
 * fix's `checkLeagueChanged()` had to special-case null to avoid wiping
 * the chat on every tab navigation.
 *
 * Module-level state, hydrated ONCE from localStorage on first read, keeps
 * `activeKey` stable across mounts/unmounts. Matches the pattern in
 * `use-chat-state.ts`.
 *
 * Preserves:
 *   - localStorage persistence at key `fc.activeLeagueKey`
 *   - The contract `useActiveLeague()` exposes today (leagues, league,
 *     activeKey, leagueId, select, isLoading)
 *   - Null-transition guard in `use-chat-state.checkLeagueChanged` —
 *     activeKey is null ONLY before first read; once a real key is set,
 *     it never returns to null until `select()` is called with null.
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";

import { useMe } from "@/lib/hooks/use-me";

const LS_KEY = "fc.activeLeagueKey";

let _activeKey: string | null = null;
let _hydrated = false;

type Listener = () => void;
const _listeners = new Set<Listener>();

function emit() {
  for (const l of _listeners) l();
}

function subscribe(cb: Listener): () => void {
  _listeners.add(cb);
  return () => {
    _listeners.delete(cb);
  };
}

function getSnapshot(): string | null {
  return _activeKey;
}

function getServerSnapshot(): string | null {
  return null;
}

/** Set the active league + persist. Called from the league switcher. */
export function selectLeague(leagueKey: string | null) {
  if (_activeKey === leagueKey) return;
  _activeKey = leagueKey;
  if (typeof window !== "undefined") {
    if (leagueKey === null) {
      window.localStorage.removeItem(LS_KEY);
    } else {
      window.localStorage.setItem(LS_KEY, leagueKey);
    }
  }
  emit();
}

/**
 * Initialize from localStorage if not already done. Called once per consumer
 * mount but guarded so it runs at most once across the whole app session.
 * We don't put this in module-level top-level code because `window` isn't
 * available during SSR/build.
 */
function hydrateOnce() {
  if (_hydrated) return;
  _hydrated = true;
  if (typeof window === "undefined") return;
  const stored = window.localStorage.getItem(LS_KEY);
  if (stored && _activeKey === null) {
    _activeKey = stored;
    emit();
  }
}

export function useActiveLeague() {
  const me = useMe();
  const activeKey = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  useEffect(() => {
    hydrateOnce();
  }, []);

  // If we have leagues and no active key (first visit, never selected,
  // localStorage empty), default to the first league. Also: if the
  // stored key is no longer valid (user left the league), fall back.
  useEffect(() => {
    if (!me.data?.leagues?.length) return;
    if (activeKey === null) {
      selectLeague(me.data.leagues[0].league_key);
      return;
    }
    const found = me.data.leagues.find((l) => l.league_key === activeKey);
    if (!found) {
      selectLeague(me.data.leagues[0].league_key);
    }
  }, [me.data, activeKey]);

  const select = useCallback((leagueKey: string) => selectLeague(leagueKey), []);
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
