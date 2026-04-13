use anchor_lang::prelude::*;

/// On-chain agent rank — latest performance summary only.
/// This is a mutable PDA overwritten on each update.
///
/// PDA seeds: [b"agent_rank", agent_id.to_le_bytes()]
///
/// On-chain stores: LATEST summary only (score, wins, losses, etc.).
/// Off-chain (Postgres rank_snapshots): stores FULL HISTORY of every
/// rank computation, never overwrites. Enables formula changes and audits.
///
/// Score is stored as u16 (0-10000) representing 0.00-100.00 with
/// 2 decimal precision.
#[account]
#[derive(InitSpace)]
pub struct AgentRankAccount {
    /// Agent this rank belongs to
    pub agent_id: u64,
    /// Strategy owner
    pub owner: Pubkey,
    /// AgentRank score: 0-10000 (maps to 0.00-100.00)
    pub score: u16,
    /// Rank formula version as numeric code (1 = rank_v1)
    /// Mapping: constants::RANK_VERSION_V1
    pub rank_version: u16,
    /// Total challenge wins
    pub wins: u32,
    /// Total challenge losses
    pub losses: u32,
    /// Total challenges participated in
    pub total_challenges: u32,
    /// Average execution quality: 0-10000 (maps to 0.00-100.00)
    pub avg_execution_quality: u16,
    /// Performance consistency: 0-10000 (maps to 0.00-100.00)
    pub consistency: u16,
    /// Number of invalid runs
    pub invalid_runs: u32,
    /// Unix timestamp of last rank update
    pub last_updated: i64,
    /// PDA bump seed
    pub bump: u8,
}
