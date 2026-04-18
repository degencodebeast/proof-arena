/**
 * TypeScript interfaces matching backend Pydantic schemas.
 * Cross-referenced with backend/src/db/schemas.py
 */

export interface LeaderboardEntry {
  agent_id: number;
  display_name: string;
  score: number;
  rank_version: string;
  wins: number;
  losses: number;
  completed_runs: number;
  invalid_runs: number;
  twitter_handle: string | null;
}

export interface RunSummary {
  run_id: number;
  challenge_id: number;
  status: string;
  completion_status: string | null;
  starting_value: number;
  ending_value: number | null;
}

export interface RunEventSummary {
  event_id: number;
  run_id: number;
  sequence_no: number;
  event_type: string;
  timestamp: string;
  tx_signature: string | null;
}

export interface ContestantSummary {
  agent_id: number;
  display_name: string;
  run_id: number;
  status: string;
  completion_status: string | null;
  ending_value: number | null;
}

export interface ChallengeSummary {
  challenge_id: number;
  challenge_type: string;
  challenge_version: string;
  status: string;
  num_contestants: number;
  num_finalized: number;
  started_at: string | null;
  ended_at: string | null;
}

export interface ChallengeDetailResponse {
  challenge_id: number;
  challenge_type: string;
  challenge_version: string;
  llm_provider: string;
  llm_model: string;
  status: string;
  config: Record<string, unknown>;
  num_contestants: number;
  num_finalized: number;
  winner_agent_id: number | null;
  contestants: ContestantSummary[];
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface AgentProfileResponse {
  agent_id: number;
  display_name: string;
  owner_wallet: string;
  submission_hash: string;
  twitter_handle: string | null;
  current_rank: LeaderboardEntry | null;
  recent_runs: RunSummary[];
  score_breakdown: Record<string, unknown>;
}

export interface StrategySubmitRequest {
  agent_name: string;
  system_prompt: string;
  config?: Record<string, unknown>;
}

export interface StrategyResponse {
  agent_id: number;
  display_name: string;
  submission_hash: string;
  onchain_address: string | null;
}
