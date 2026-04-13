use anchor_lang::prelude::*;

#[event]
pub struct StrategyRegistered {
    pub agent_id: u64,
    pub owner: Pubkey,
    pub agent_name: String,
    pub submission_hash: [u8; 32],
    pub created_at: i64,
}

#[event]
pub struct ChallengeCreated {
    pub challenge_id: u64,
    pub challenge_type: u8,
    pub challenge_version: u16,
    pub starting_usdc: u64,
    pub num_contestants: u8,
    pub created_at: i64,
}

#[event]
pub struct ChallengeStarted {
    pub challenge_id: u64,
    pub started_at: i64,
}

#[event]
pub struct RunFinalized {
    pub challenge_id: u64,
    pub agent_id: u64,
    pub ending_usdc: u64,
    pub completion_status: u8,
    pub run_log_hash: [u8; 32],
}

#[event]
pub struct ChallengeSettled {
    pub challenge_id: u64,
    pub winner_agent_id: Option<u64>,
    pub ended_at: i64,
}

#[event]
pub struct AgentRankUpdated {
    pub agent_id: u64,
    pub score: u16,
    pub rank_version: u16,
    pub wins: u32,
    pub losses: u32,
    pub total_challenges: u32,
}
