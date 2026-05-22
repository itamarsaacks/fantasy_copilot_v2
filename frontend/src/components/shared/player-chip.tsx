"use client";

/**
 * Inline-clickable player chip — avatar + name + optional team badge.
 * Used in chat replies (via renderWithMentions) and anywhere a player
 * is named inline in another component.
 *
 * Click opens the shared player drawer (TODO: wire to a global drawer
 * context in the next session; for now `onClick` is exposed so the
 * caller can route to /players/<id> or open its own drawer).
 */
import { PlayerAvatar } from "./player-avatar";
import { TeamLogo } from "./team-logo";

export interface PlayerChipProps {
  playerId: number;
  name: string;
  position?: string | null;
  nbaTeamAbbr?: string | null;
  headshotPath?: string | null;
  size?: "sm" | "md";
  onClick?: (playerId: number) => void;
  className?: string;
}

export function PlayerChip({
  playerId,
  name,
  position,
  nbaTeamAbbr,
  headshotPath,
  size = "md",
  onClick,
  className = "",
}: PlayerChipProps) {
  const avatar = size === "sm" ? 24 : 32;
  const handleClick = onClick ? () => onClick(playerId) : undefined;

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-sm leading-none hover:bg-slate-50 transition-colors ${className}`}
      title={position ? `${name} • ${position}` : name}
    >
      <PlayerAvatar name={name} headshotPath={headshotPath} size={avatar} />
      <span className="font-medium text-slate-800">{name}</span>
      {nbaTeamAbbr && (
        <span className="ml-1">
          <TeamLogo abbr={nbaTeamAbbr} size={16} />
        </span>
      )}
    </button>
  );
}
