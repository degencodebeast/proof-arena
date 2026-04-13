use anchor_lang::prelude::*;

// ---------------------------------------------------------------------------
// Enums — lifecycle status is SEPARATE from completion validity
// ---------------------------------------------------------------------------

/// Run lifecycle status — tracks execution progress.
/// This is NOT the same as benchmark validity.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq, InitSpace)]
#[repr(u8)]
pub enum RunStatus {
    Pending = 0,
    Running = 1,
    Completed = 2,
    Failed = 3,
    Timeout = 4,
}

/// Run completion validity — determines benchmark eligibility.
/// SEPARATE from RunStatus. A run can be Completed but Incomplete.
///
/// Only Complete runs can win settlement.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq, InitSpace)]
#[repr(u8)]
pub enum CompletionStatus {
    Complete = 0,
    Incomplete = 1,
    Invalid = 2,
}

// ---------------------------------------------------------------------------
// Account
// ---------------------------------------------------------------------------

/// On-chain run record — execution state and outcome for one agent in one challenge.
///
/// PDA seeds: [b"run", challenge_id.to_le_bytes(), agent_id.to_le_bytes()]
///
/// On-chain stores: outcome summary (balances, status, hash).
/// Off-chain (Postgres) stores: full RunEvent sequence, rich evidence.
#[account]
#[derive(InitSpace)]
pub struct RunAccount {
    /// Challenge this run belongs to
    pub challenge_id: u64,
    /// Agent executing this run
    pub agent_id: u64,
    /// Privy-managed benchmark wallet for this run
    pub benchmark_wallet: Pubkey,
    /// Starting USDC balance (base units, 6 decimals)
    pub starting_usdc: u64,
    /// Ending USDC balance after flattening (None until finalized)
    pub ending_usdc: Option<u64>,
    /// SHA-256 of the full RunEvent sequence (evidence anchor)
    pub run_log_hash: Option<[u8; 32]>,
    /// Lifecycle status (execution progress)
    pub status: RunStatus,
    /// Completion validity (benchmark eligibility) — None until finalized
    pub completion_status: Option<CompletionStatus>,
    /// Number of decision iterations used
    pub iterations_used: u16,
    /// Unix timestamp of run creation
    pub created_at: i64,
    /// Unix timestamp when run started executing
    pub started_at: Option<i64>,
    /// Unix timestamp when run finished
    pub ended_at: Option<i64>,
    /// PDA bump seed
    pub bump: u8,
}
