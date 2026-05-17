/**
 * TypeScript shapes that mirror the FastAPI backend responses.
 * Keep in sync when the backend changes.
 */

export type LeagueScoringType = "point" | "headpoint" | "head" | "roto" | string;

export type MeLeague = {
  id: number;
  league_key: string;
  name: string;
  scoring_type: LeagueScoringType;
  num_teams: number;
  current_week: number | null;
  season: string;
};

export type MeUser = {
  id: number;
  yahoo_guid: string;
  auth_broken: boolean;
  token_expires_at: string;
};

export type MeResponse = {
  user: MeUser;
  leagues: MeLeague[];
};

export type ChatRequest = {
  message: string;
  league_id: number;
};

export type ChatResponse = {
  reply: string;
  tool_calls: number;
  league_name: string;
};

export type HealthResponse = {
  status: "ok" | string;
  app_mode: "live" | "replay";
  as_of_date: string | null;
};

// /api/team/{league_id}?date=YYYY-MM-DD
export type GameOnDate = {
  date: string;
  opponent: string;
  home: boolean;
  status: string;
  tipoff_at: string | null;
  is_back_to_back: boolean;
};

export type SeasonStats = {
  gp: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  tov: number | null;
};

export type TeamPlayerView = {
  name: string;
  nba_team: string | null;
  eligible_positions: string[];
  selected_position: string | null;
  status: string | null;
  status_full: string | null;
  injury_note: string | null;
  projected_fps_per_game: number | null;
  projected_fps_on_date: number | null;
  actual_fps_on_date: number | null;
  actual_stats: SeasonStats | null;
  game_on_date: GameOnDate | null;
  season_stats: SeasonStats;
};

export type RosterBucket = {
  label: string;
  players: TeamPlayerView[];
};

export type TeamResponse = {
  league_id: number;
  league_name: string;
  team_name: string;
  manager_name: string | null;
  requested_date: string;
  is_past_date: boolean;
  starters: RosterBucket;
  bench: RosterBucket;
  ir: RosterBucket;
};
