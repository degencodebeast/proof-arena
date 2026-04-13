use anchor_lang::prelude::*;

/// Global program configuration — stores the admin authority.
///
/// PDA seeds: [b"config"]
///
/// The admin is the only pubkey that can create challenges,
/// update agent ranks, and perform other privileged operations.
/// Set once via initialize instruction.
#[account]
#[derive(InitSpace)]
pub struct ConfigAccount {
    /// The program admin (backend authority)
    pub admin: Pubkey,
    /// Whether this config has been initialized
    pub is_initialized: bool,
    /// PDA bump seed
    pub bump: u8,
}
