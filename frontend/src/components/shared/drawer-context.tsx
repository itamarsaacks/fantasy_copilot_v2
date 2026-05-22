"use client";

/**
 * Global drawer context — any component anywhere in the tree can call
 * `useDrawer().openPlayer(playerId)` to surface the shared player drawer.
 *
 * Why this exists (master plan §3 + chat-mentions / players / games /
 * my-team / league tabs all need to open the same drawer):
 *   - Before: each tab embedded its own <PlayerDrawer/> + drove state with
 *     local useState. Inconsistent UX, four copies of the same wiring.
 *   - Now: the drawer is mounted exactly once at the app shell layout.
 *     Consumers call openPlayer/closePlayer through context. State is
 *     module-level on top of context so it survives mid-tree remounts.
 *
 * Player name is optional — passing it gives the drawer a header to
 * render while the API request is in flight. Without it the drawer shows
 * "Player" until detail loads.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useActiveLeague } from "@/lib/hooks/use-active-league";
import { PlayerDrawer } from "@/components/shared/player-drawer";

interface DrawerCtx {
  isOpen: boolean;
  playerId: number | null;
  playerName: string | undefined;
  openPlayer: (playerId: number, playerName?: string) => void;
  closePlayer: () => void;
}

const Ctx = createContext<DrawerCtx | null>(null);

export function DrawerProvider({ children }: { children: ReactNode }) {
  const [playerId, setPlayerId] = useState<number | null>(null);
  const [playerName, setPlayerName] = useState<string | undefined>(undefined);

  const openPlayer = useCallback((id: number, name?: string) => {
    setPlayerId(id);
    setPlayerName(name);
  }, []);

  const closePlayer = useCallback(() => {
    setPlayerId(null);
    setPlayerName(undefined);
  }, []);

  const onOpenChange = useCallback(
    (next: boolean) => {
      if (!next) closePlayer();
    },
    [closePlayer],
  );

  const value: DrawerCtx = useMemo(
    () => ({
      isOpen: playerId !== null,
      playerId,
      playerName,
      openPlayer,
      closePlayer,
    }),
    [playerId, playerName, openPlayer, closePlayer],
  );

  const { leagueId } = useActiveLeague();

  return (
    <Ctx.Provider value={value}>
      {children}
      <PlayerDrawer
        open={playerId !== null}
        onOpenChange={onOpenChange}
        leagueId={leagueId}
        playerId={playerId}
        playerName={playerName}
      />
    </Ctx.Provider>
  );
}

/**
 * Use the global player drawer from any descendant of <DrawerProvider/>.
 * Returns null-safe handlers if called outside the provider so SSR or
 * isolated component tests don't blow up.
 */
export function useDrawer(): DrawerCtx {
  const ctx = useContext(Ctx);
  if (ctx) return ctx;
  // Stub fallback — keeps consumers safe outside the provider tree.
  return {
    isOpen: false,
    playerId: null,
    playerName: undefined,
    openPlayer: () => undefined,
    closePlayer: () => undefined,
  };
}
