use anchor_lang::prelude::*;

// ---------------------------------------------------------------------------
// Enums — compact on-chain encoding (u8/u16 mapped to symbolic labels)
// ---------------------------------------------------------------------------

/// Challenge type — u8 enum. Mapping defined in constants.rs.
/// V1: SwapExecution = 0. V2 will add YieldSprint, etc.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq, InitSpace)]
#[repr(u8)]
pub enum ChallengeType {
    SwapExecution = 0,
}

/// Challenge lifecycle status.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq, InitSpace)]
#[repr(u8)]
pub enum ChallengeStatus {
    Pending = 0,
    Active = 1,
    Settling = 2,
    Completed = 3,
    Cancelled = 4,
}

// ---------------------------------------------------------------------------
// Account
// ---------------------------------------------------------------------------

/// On-chain challenge definition — benchmark config and settlement state.
///
/// PDA seeds: [b"challenge", challenge_id.to_le_bytes()]
///
/// On-chain stores: config params, lifecycle status, winner.
/// Off-chain (Postgres) stores: full config_json, rich evidence.
#[account]
#[derive(InitSpace)]
pub struct ChallengeAccount {
    /// Unique challenge identifier
    pub challenge_id: u64,
    /// Admin authority that manages this challenge
    pub authority: Pubkey,
    /// Challenge type as compact enum (0 = SwapExecution)
    pub challenge_type: ChallengeType,
    /// Challenge version as numeric code (1 = swap_execution_v1)
    /// Mapping: constants::CHALLENGE_VERSION_SWAP_V1
    pub challenge_version: u16,
    /// Current lifecycle status
    pub status: ChallengeStatus,
    /// Starting USDC amount for each contestant (base units, 6 decimals)
    pub starting_usdc: u64,
    /// USDC mint address on this cluster
    pub usdc_mint: Pubkey,
    /// Maximum allowed slippage in basis points
    pub max_slippage_bps: u16,
    /// Maximum number of decision iterations per run
    pub iteration_budget: u16,
    /// Maximum wall-clock time per run in seconds
    pub time_budget_secs: u32,
    /// Expected number of contestants
    pub num_contestants: u8,
    /// Number of runs actually created (enrolled)
    pub num_enrolled: u8,
    /// Number of runs finalized so far
    pub num_finalized: u8,
    /// Winner agent_id after settlement (None until settled)
    pub winner_agent_id: Option<u64>,
    /// Unix timestamp of creation
    pub created_at: i64,
    /// Unix timestamp when challenge became Active
    pub started_at: Option<i64>,
    /// Unix timestamp when challenge completed/cancelled
    pub ended_at: Option<i64>,
    /// PDA bump seed
    pub bump: u8,
}
