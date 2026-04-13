use anchor_lang::prelude::*;

use crate::constants::*;
use crate::errors::AgentArenaError;
use crate::events::ChallengeCreated;
use crate::state::{ChallengeAccount, ChallengeStatus, ChallengeType, ConfigAccount};

#[derive(Accounts)]
#[instruction(challenge_id: u64)]
pub struct CreateChallenge<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + ChallengeAccount::INIT_SPACE,
        seeds = [CHALLENGE_SEED, &challenge_id.to_le_bytes()],
        bump,
    )]
    pub challenge_account: Account<'info, ChallengeAccount>,

    /// Global config — proves the signer is the program admin.
    #[account(
        seeds = [CONFIG_SEED],
        bump = config.bump,
        constraint = config.is_initialized @ AgentArenaError::UnauthorizedAuthority,
        constraint = config.admin == authority.key() @ AgentArenaError::UnauthorizedAuthority,
    )]
    pub config: Account<'info, ConfigAccount>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub system_program: Program<'info, System>,
}

pub fn handler(
    ctx: Context<CreateChallenge>,
    challenge_id: u64,
    challenge_type: ChallengeType,
    challenge_version: u16,
    starting_usdc: u64,
    usdc_mint: Pubkey,
    max_slippage_bps: u16,
    iteration_budget: u16,
    time_budget_secs: u32,
    num_contestants: u8,
) -> Result<()> {
    require!(
        max_slippage_bps <= MAX_SLIPPAGE_BPS,
        AgentArenaError::InvalidSlippage
    );
    require!(
        num_contestants > 0 && num_contestants <= MAX_CONTESTANTS,
        AgentArenaError::InvalidContestantCount
    );

    let challenge = &mut ctx.accounts.challenge_account;
    challenge.challenge_id = challenge_id;
    challenge.authority = ctx.accounts.authority.key();
    challenge.challenge_type = challenge_type;
    challenge.challenge_version = challenge_version;
    challenge.status = ChallengeStatus::Pending;
    challenge.starting_usdc = starting_usdc;
    challenge.usdc_mint = usdc_mint;
    challenge.max_slippage_bps = max_slippage_bps;
    challenge.iteration_budget = iteration_budget;
    challenge.time_budget_secs = time_budget_secs;
    challenge.num_contestants = num_contestants;
    challenge.num_enrolled = 0;
    challenge.num_finalized = 0;
    challenge.winner_agent_id = None;
    challenge.created_at = Clock::get()?.unix_timestamp;
    challenge.started_at = None;
    challenge.ended_at = None;
    challenge.bump = ctx.bumps.challenge_account;

    emit!(ChallengeCreated {
        challenge_id,
        challenge_type: challenge_type as u8,
        challenge_version,
        starting_usdc,
        num_contestants,
        created_at: challenge.created_at,
    });

    Ok(())
}
