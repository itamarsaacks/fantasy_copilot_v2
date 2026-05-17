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
  is_admin?: boolean;
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

// /api/players/{league_id}/{player_id}
export type PlayerDetailMeta = {
  id: number;
  yahoo_player_key: string;
  name: string;
  nba_team: string | null;
  eligible_positions: string[];
  primary_position: string | null;
  status: string | null;
  status_full: string | null;
  injury_note: string | null;
  image_url: string | null;
  percent_owned: number | null;
  percent_started: number | null;
};

export type PlayerDetailOwnership = {
  state: "free_agent" | "waivers" | "on_team" | "my_team";
  team_name: string | null;
  waiver_status: string | null;
};

export type PlayerDetailDateRange = {
  start: string;
  end: string;
  today: string;
};

export type PlayerGameLogRow = {
  date: string;
  opponent: string | null;
  home: boolean | null;
  is_back_to_back: boolean;
  minutes: number | null;
  stats: Record<string, number>;
  fantasy_points: number | null;
};

export type PlayerStatsAggregate = {
  games_played: number;
  totals: Record<string, number>;
  per_game: Record<string, number>;
  fantasy_points_total: number | null;
  fantasy_points_per_game: number | null;
  games_log: PlayerGameLogRow[];
};

export type PlayerProjectedGameRow = {
  date: string;
  opponent: string;
  home: boolean;
  is_back_to_back: boolean;
  projected_fps: number | null;
};

export type PlayerProjectionAggregate = {
  games_projected: number;
  fantasy_points_total: number | null;
  fantasy_points_per_game: number | null;
  games_log: PlayerProjectedGameRow[];
};

export type PlayerNewsItem = {
  title: string;
  body: string | null;
  url: string | null;
  kind: string;
  confidence: number | null;
  source: string;
  published_at: string;
};

export type PlayerDetailResponse = {
  player: PlayerDetailMeta;
  ownership: PlayerDetailOwnership;
  date_range: PlayerDetailDateRange;
  base_projection_per_game: number | null;
  actual: PlayerStatsAggregate;
  projection: PlayerProjectionAggregate;
  news: PlayerNewsItem[];
};

// /api/admin/evals/*
export type EvalRunSummary = {
  id: number;
  started_at: string;
  finished_at: string | null;
  git_sha: string | null;
  git_branch: string | null;
  triggered_by: string;
  model: string | null;
  total_cases: number;
  total_phrasings: number;
  strict_passed: number;
  soft_passed: number;
  failed: number;
  errored: number;
  total_latency_ms: number;
  total_cost_usd: number | null;
  pass_rate: number | null;
};

export type EvalCaseResultSummary = {
  id: number;
  case_id: string;
  phrasing: string;
  repeat_index: number;
  verdict: string;
  errored: boolean;
  error_message: string | null;
  latency_ms: number;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  langsmith_trace_url: string | null;
  intent_question_type: string;
  intent_complexity: string;
  intent_domain: string;
  failure_reasons: Array<Record<string, unknown>>;
  tool_calls_count: number;
};

export type EvalRunDetail = {
  run: EvalRunSummary;
  results: EvalCaseResultSummary[];
};

export type EvalCaseLibraryEntry = {
  case_id: string;
  intent_question_type: string | null;
  intent_complexity: string | null;
  intent_domain: string | null;
  tags: string[];
  phrasings_count: number;
  repeats: number;
  latest_verdict: string | null;
  latest_run_id: number | null;
};

export type EvalCaseDetailRun = {
  run_id: number;
  started_at: string;
  verdicts: Record<string, number>;
  results: EvalCaseResultSummary[];
};

export type EvalCaseDetail = {
  case_id: string;
  case_yaml_path: string | null;
  intent_question_type: string | null;
  intent_complexity: string | null;
  intent_domain: string | null;
  tags: string[];
  runs: EvalCaseDetailRun[];
};

export type EvalRegression = {
  case_id: string;
  latest_verdict: string;
  latest_run_id: number;
  prior_verdict: string;
  prior_run_id: number;
  direction: "worsened" | "improved";
};

export type EvalSummary = {
  total_runs: number;
  latest_run: EvalRunSummary | null;
  overall_pass_rate_last_run: number | null;
  cases_on_disk: number;
  cases_with_history: number;
};

// /api/trades/{league_id}
export type TradePlayer = {
  player_id: number;
  name: string;
  nba_team: string | null;
  eligible_positions: string[];
  selected_position: string | null;
  status: string | null;
  injury_note: string | null;
  projected_fps_per_game: number | null;
};

export type TradeTeam = {
  team_id: number;
  name: string;
  manager_name: string | null;
  is_user_team: boolean;
  players: TradePlayer[];
};

export type TradesBuilderResponse = {
  league_id: number;
  league_name: string;
  scoring_type: string;
  my_team: TradeTeam | null;
  partners: TradeTeam[];
};

// /api/league/{league_id}
export type LeagueMeta = {
  league_id: number;
  league_key: string;
  name: string;
  season: string;
  scoring_type: string;
  num_teams: number;
  current_week: number | null;
};

export type TeamStanding = {
  team_id: number;
  team_key: string;
  name: string;
  manager_name: string | null;
  logo_url: string | null;
  is_user_team: boolean;
  rank: number | null;
  wins: number | null;
  losses: number | null;
  ties: number | null;
  points_for: number | null;
  points_against: number | null;
  number_of_moves: number | null;
  number_of_trades: number | null;
  faab_balance: number | null;
  waiver_priority: number | null;
  clinched_playoffs: boolean | null;
  division_id: string | null;
};

export type ScoringRule = {
  stat_id: string;
  abbr: string;
  display_name: string;
  modifier: number | null;
};

export type LeagueSettings = {
  max_teams: number | null;
  waiver_type: string | null;
  waiver_days: string | null;
  waiver_rule: string | null;
  waiver_time: string | null;
  uses_faab: boolean;
  uses_playoff: boolean;
  trade_end_date: string | null;
  max_games_played: number | null;
  is_highscore: boolean;
};

export type LeagueResponse = {
  meta: LeagueMeta;
  teams: TeamStanding[];
  scoring: ScoringRule[];
  settings: LeagueSettings;
};

// /api/waivers/{league_id}?days_ahead=N
export type WaiverCandidate = {
  player_id: number;
  name: string;
  nba_team: string | null;
  eligible_positions: string[];
  status: string | null;
  status_full: string | null;
  injury_note: string | null;
  projected_fps_per_game: number | null;
  games_in_window: number;
  back_to_back_count: number;
  availability_factor: number;
  window_fps: number | null;
  waiver_status: string | null;
  selected_position: string | null;
};

export type SuggestedSwap = {
  pickup: WaiverCandidate;
  drop: WaiverCandidate;
  delta_window_fps: number;
  delta_per_game: number;
};

export type WaiversResponse = {
  league_id: number;
  window_days: number;
  window_start: string;
  window_end: string;
  pickups: WaiverCandidate[];
  drops: WaiverCandidate[];
  suggested_swaps: SuggestedSwap[];
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

// /api/players/{league_id}
export type PlayerOwnershipState =
  | "free_agent"
  | "waivers"
  | "on_team"
  | "my_team";

export type PlayerOwnership = {
  state: PlayerOwnershipState;
  team_name: string | null;
  waiver_status: string | null;
};

export type PlayerSeasonStats = {
  gp: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  tov: number | null;
};

export type PlayerView = {
  id: number;
  name: string;
  nba_team: string | null;
  eligible_positions: string[];
  primary_position: string | null;
  status: string | null;
  status_full: string | null;
  injury_note: string | null;
  image_url: string | null;
  percent_owned: number | null;
  percent_started: number | null;
  projected_fps_per_game: number | null;
  season_fps_per_game: number | null;
  season_stats: PlayerSeasonStats;
  ownership: PlayerOwnership;
};

export type PlayersResponse = {
  league_id: number;
  total: number;
  limit: number;
  offset: number;
  available_positions: string[];
  items: PlayerView[];
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
