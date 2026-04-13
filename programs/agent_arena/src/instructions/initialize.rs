use anchor_lang::prelude::*;

use crate::constants::*;
use crate::state::ConfigAccount;

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(
        init,
        payer = admin,
        space = 8 + ConfigAccount::INIT_SPACE,
        seeds = [CONFIG_SEED],
        bump,
    )]
    pub config: Account<'info, ConfigAccount>,

    #[account(mut)]
    pub admin: Signer<'info>,

    pub system_program: Program<'info, System>,
}

/// Initialize the program config with the admin pubkey.
/// Can only be called once (PDA uniqueness enforces this).
pub fn handler(ctx: Context<Initialize>) -> Result<()> {
    let config = &mut ctx.accounts.config;
    config.admin = ctx.accounts.admin.key();
    config.is_initialized = true;
    config.bump = ctx.bumps.config;
    Ok(())
}
