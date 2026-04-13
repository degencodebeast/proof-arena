use anchor_lang::prelude::*;

/// On-chain strategy registration — links an agent identity to a submission hash.
///
/// PDA seeds: [b"strategy", owner.key().as_ref(), agent_id.to_le_bytes()]
///
/// On-chain stores: identity + submission hash.
/// Off-chain (Postgres) stores: full system_prompt, config_json, rich metadata.
#[account]
#[derive(InitSpace)]
pub struct StrategyAccount {
    /// Unique agent identifier (matches Postgres agents.agent_id)
    pub agent_id: u64,
    /// Strategy owner's public key (signer at registration)
    pub owner: Pubkey,
    /// Human-readable agent name
    #[max_len(64)]
    pub agent_name: String,
    /// SHA-256 of normalized (system_prompt + config_json)
    pub submission_hash: [u8; 32],
    /// Optional reference to metadata (IPFS hash, URL, etc.)
    #[max_len(128)]
    pub metadata_ref: String,
    /// Unix timestamp of registration
    pub created_at: i64,
    /// Whether this strategy is currently active
    pub is_active: bool,
    /// PDA bump seed
    pub bump: u8,
}
