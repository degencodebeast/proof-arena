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

// --- Task 20: flagship public read endpoint ---

export interface FlagshipRun {
  run_id: number;
  status: string;
  completion_status: string | null;
  invalid_reason: string | null;
  created_at: string | null;
}

export interface OutcomeDistribution {
  complete_count: number;
  complete_pct: number;
  invalid_count: number;
  invalid_pct: number;
  failed_count: number;
  failed_pct: number;
  pending_count: number;
  total: number;
}

export interface FlagshipResponse {
  instance_id: number;
  trust_label: string;
  template_key: string;
  status_label: 'devnet-live' | 'offline';
  runs: FlagshipRun[];
  outcome_distribution: OutcomeDistribution;
}

// --- Task 4: public template catalog summary (list response) ---

/**
 * Matches backend/src/api/templates.py `list_templates()` summary shape.
 * Detail-response fields (allowed_fields, default_config, system_prompt,
 * flagship_trust_label, template_id, benchmark_subject_agent_id) are
 * deliberately absent — they belong to GET /templates/{key} which Task
 * 22 will consume. The catalog view never accesses them.
 */
export interface TemplateSummary {
  template_key: string;
  template_version: string;
  description: string;
  is_deployable: boolean;
  created_at: string | null;
}

// --- Task 23: deploy flow request/response ---

/**
 * Body for POST /api/v1/instances/deploy. `owner_ref` is NOT included
 * — the backend sets it server-side from the authenticated Privy
 * user. Client-supplied owner fields are ignored by design.
 */
export interface InstanceDeployRequest {
  template_key: string;
  effective_config: Record<string, unknown>;
  consent: Record<string, boolean>;
}

/**
 * Narrow public-safe response from POST /api/v1/instances/deploy.
 * Excludes all private fields (hosted_wallet_ref, runtime_handle_json,
 * consent_artifact_id, wallet_address, wallet_provider,
 * instance_owner_ref) — the backend response_model enforces this.
 */
export interface InstanceDeployResponse {
  instance_id: number;
  status: string;
  last_failure_reason: string | null;
}

/**
 * Matches backend template_service.get_template_with_flagship_info()
 * return shape exactly — the Task 4 detail endpoint serializes this
 * dict verbatim. 10 fields. No benchmark scores / wins / losses —
 * template-layer responses surface lineage only per the V2 service
 * boundary ("No benchmark overclaim").
 */
export interface TemplateDetailResponse {
  template_id: number;
  template_key: string;
  template_version: string;
  description: string;
  system_prompt: string;
  allowed_fields: string[];
  default_config: Record<string, unknown>;
  is_deployable: boolean;
  benchmark_subject_agent_id: number | null;
  flagship_trust_label: string | null;
}

// --- Task 17: owner-gated instance profile response ---

export interface InstanceRunSummary {
  run_id: number;
  challenge_id: number;
  status: string;
  completion_status: string | null;
  invalid_reason: string | null;
  ending_value: number | null;
  created_at: string | null;
}

export interface InstanceRankSnapshot {
  snapshot_id: number;
  score: number;
  rank_version: string;
  subject_type: string;
  wins: number;
  losses: number;
  completed_runs: number;
  invalid_runs: number;
  computed_at: string | null;
}

/**
 * Matches backend/src/api/instances.py `get_instance_profile` flat-dict
 * response. Private fields (instance_owner_ref, hosted_wallet_ref,
 * wallet_address, wallet_provider, runtime_handle_json,
 * consent_artifact_id) are deliberately absent — the backend does not
 * serialize them.
 */
export interface InstanceProfileResponse {
  instance_id: number;
  template_key: string | null;
  template_version_at_deploy: string;
  effective_config: Record<string, unknown>;
  trust_label: string;
  status: string;
  last_failure_reason: string | null;
  superseded_by_instance_id: number | null;
  is_superseded: boolean;
  created_at: string | null;
  benchmarked: boolean;
  runs: InstanceRunSummary[];
  rank_history: InstanceRankSnapshot[];
}
