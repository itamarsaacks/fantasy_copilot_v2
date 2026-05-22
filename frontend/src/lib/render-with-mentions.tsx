"use client";

/**
 * Post-process an agent reply: find player & team names, wrap them in
 * clickable chips (master plan §3, "renderWithMentions").
 *
 * v1 strategy: whole-word case-insensitive match against a known-players
 * list + known team abbreviations. Skip tokens inside code blocks.
 * Disambiguation: if a token matches multiple players, leave as plain
 * text (we'd rather under-link than mis-link).
 *
 * Future hook (Risk #4 in master plan): if the backend later returns a
 * `mentions: [{text, player_id, start, end}]` sidecar, prefer that
 * over fuzzy matching — see `renderWithSidecar` below.
 */
import { Fragment, type ReactNode } from "react";

import { PlayerChip } from "@/components/shared/player-chip";
import { TeamLogo } from "@/components/shared/team-logo";

export interface KnownPlayer {
  player_id: number;
  full_name: string;
  last_name?: string | null;
  position?: string | null;
  nba_team_abbr?: string | null;
  headshot_path?: string | null;
}

export interface KnownTeam {
  abbr: string;
  full_name: string; // "Los Angeles Lakers"
}

export interface MentionsContext {
  players: KnownPlayer[];
  teams: KnownTeam[];
  onPlayerClick?: (playerId: number) => void;
}

interface Match {
  start: number;
  end: number;
  type: "player" | "team";
  player?: KnownPlayer;
  team?: KnownTeam;
}

/** Build a map full-name → player; full-name and last-name unique-only. */
function buildPlayerLookup(players: KnownPlayer[]): {
  exact: Map<string, KnownPlayer>;
  lastNameUnique: Map<string, KnownPlayer>;
} {
  const exact = new Map<string, KnownPlayer>();
  const lastNameCount = new Map<string, number>();
  for (const p of players) {
    exact.set(p.full_name.toLowerCase(), p);
    const ln = (p.last_name || p.full_name.split(/\s+/).pop() || "").toLowerCase();
    lastNameCount.set(ln, (lastNameCount.get(ln) ?? 0) + 1);
  }
  const lastNameUnique = new Map<string, KnownPlayer>();
  for (const p of players) {
    const ln = (p.last_name || p.full_name.split(/\s+/).pop() || "").toLowerCase();
    if ((lastNameCount.get(ln) ?? 0) === 1) {
      lastNameUnique.set(ln, p);
    }
  }
  return { exact, lastNameUnique };
}

function buildTeamLookup(teams: KnownTeam[]): Map<string, KnownTeam> {
  const m = new Map<string, KnownTeam>();
  for (const t of teams) {
    m.set(t.full_name.toLowerCase(), t);
    m.set(t.abbr.toLowerCase(), t);
  }
  return m;
}

/** Find all match positions in `text`, longest-first to prefer full names. */
function findMatches(text: string, ctx: MentionsContext): Match[] {
  const { exact, lastNameUnique } = buildPlayerLookup(ctx.players);
  const teamsByText = buildTeamLookup(ctx.teams);
  const matches: Match[] = [];

  // Full names first (longest token)
  const sortedExact = Array.from(exact.entries()).sort(
    (a, b) => b[0].length - a[0].length
  );
  for (const [key, player] of sortedExact) {
    const re = new RegExp(`\\b${escapeRegex(key)}\\b`, "gi");
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      matches.push({
        start: m.index,
        end: m.index + m[0].length,
        type: "player",
        player,
      });
    }
  }

  // Last names (unique)
  for (const [key, player] of lastNameUnique.entries()) {
    if (key.length < 3) continue; // skip super-short last names ("Jr")
    const re = new RegExp(`\\b${escapeRegex(key)}\\b`, "gi");
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      matches.push({
        start: m.index,
        end: m.index + m[0].length,
        type: "player",
        player,
      });
    }
  }

  // Teams
  for (const [key, team] of teamsByText.entries()) {
    if (key.length < 2) continue;
    const re = new RegExp(`\\b${escapeRegex(key)}\\b`, "gi");
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      matches.push({
        start: m.index,
        end: m.index + m[0].length,
        type: "team",
        team,
      });
    }
  }

  // Resolve overlaps: keep the longest, drop the rest
  matches.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start));
  const kept: Match[] = [];
  for (const m of matches) {
    if (kept.length && m.start < kept[kept.length - 1].end) continue;
    kept.push(m);
  }
  return kept;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Render `text` with chips inserted at match positions. Skips matches
 * inside ```code``` and `inline code` regions.
 */
export function renderWithMentions(
  text: string,
  ctx: MentionsContext
): ReactNode {
  // Quick code-block bypass: split on fenced code, render those literally.
  const segments = text.split(/(```[\s\S]*?```|`[^`]+`)/g);
  return (
    <>
      {segments.map((seg, i) => {
        if (seg.startsWith("```") || (seg.startsWith("`") && seg.endsWith("`"))) {
          return <Fragment key={i}>{seg}</Fragment>;
        }
        return <Fragment key={i}>{renderInline(seg, ctx)}</Fragment>;
      })}
    </>
  );
}

function renderInline(text: string, ctx: MentionsContext): ReactNode {
  const matches = findMatches(text, ctx);
  if (matches.length === 0) return text;

  const out: ReactNode[] = [];
  let cursor = 0;
  for (let i = 0; i < matches.length; i++) {
    const m = matches[i];
    if (m.start > cursor) out.push(text.slice(cursor, m.start));
    if (m.type === "player" && m.player) {
      out.push(
        <PlayerChip
          key={`p-${i}`}
          playerId={m.player.player_id}
          name={text.slice(m.start, m.end)}
          position={m.player.position}
          nbaTeamAbbr={m.player.nba_team_abbr}
          headshotPath={m.player.headshot_path}
          size="sm"
          onClick={ctx.onPlayerClick}
          className="mx-0.5"
        />
      );
    } else if (m.type === "team" && m.team) {
      out.push(
        <span key={`t-${i}`} className="inline-flex items-center gap-1 mx-0.5">
          <TeamLogo abbr={m.team.abbr} size={16} />
          <span>{text.slice(m.start, m.end)}</span>
        </span>
      );
    }
    cursor = m.end;
  }
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}
