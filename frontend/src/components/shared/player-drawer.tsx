"use client";

/**
 * Shared player drawer — re-exports the existing implementation under
 * the canonical "shared" path so every tab opens the same drawer.
 *
 * Per master plan §3 ("Move player drawer → components/shared/"), this
 * keeps the implementation file where it currently lives (one place to
 * read it, no double-maintenance) while presenting the canonical import
 * path that future tab sessions consume:
 *
 *   import { PlayerDrawer } from "@/components/shared/player-drawer";
 *
 * For programmatic open-from-anywhere, use `useDrawer()` from
 * `components/shared/drawer-context`. The drawer is mounted once at the
 * app shell and any consumer can call `openPlayer(playerId)`.
 */
export { PlayerDetailDrawer as PlayerDrawer } from "@/components/players/player-detail-drawer";
