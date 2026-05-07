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
