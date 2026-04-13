use anchor_lang::prelude::*;

use crate::constants::*;
use crate::errors::AgentArenaError;
use crate::state::{ChallengeAccount, ChallengeStatus, RunAccount, RunStatus, StrategyAccount};

#[derive(Accounts)]
#[instruction(challenge_id: u64, agent_id: u64)]
pub struct CreateRun<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + RunAccount::INIT_SPACE,
        seeds = [RUN_SEED, &challenge_id.to_le_bytes(), &agent_id.to_le_bytes()],
        bump,
    )]
    pub run_account: Account<'info, RunAccount>,

    #[account(
        mut,
        seeds = [CHALLENGE_SEED, &challenge_id.to_le_bytes()],
        bump = challenge_account.bump,
        // Only the challenge authority (admin) can create runs
        constraint = challenge_account.authority == authority.key()
            @ AgentArenaError::UnauthorizedAuthority,
        constraint = challenge_account.status == ChallengeStatus::Pending
            || challenge_account.status == ChallengeStatus::Active
            @ AgentArenaError::InvalidChallengeStatus,
        // Cannot exceed declared contestant count
        constraint = challenge_account.num_enrolled < challenge_account.num_contestants
            @ AgentArenaError::ChallengeFull,
    )]
    pub challenge_account: Account<'info, ChallengeAccount>,

    /// The strategy must exist and be active.
    #[account(
        constraint = strategy_account.agent_id == agent_id @ AgentArenaError::AgentNotRegistered,
        constraint = strategy_account.is_active @ AgentArenaError::AgentNotRegistered,
    )]
    pub strategy_account: Account<'info, StrategyAccount>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub system_program: Program<'info, System>,
}

pub fn handler(
    ctx: Context<CreateRun>,
    challenge_id: u64,
    agent_id: u64,
    benchmark_wallet: Pubkey,
) -> Result<()> {
    let challenge = &mut ctx.accounts.challenge_account;

    // Track enrollment for cardinality enforcement
    challenge.num_enrolled = challenge
        .num_enrolled
        .checked_add(1)
        .ok_or(AgentArenaError::Overflow)?;

    let run = &mut ctx.accounts.run_account;
    run.challenge_id = challenge_id;
    run.agent_id = agent_id;
    run.benchmark_wallet = benchmark_wallet;
    run.starting_usdc = challenge.starting_usdc;
    run.ending_usdc = None;
    run.run_log_hash = None;
    run.status = RunStatus::Pending;
    run.completion_status = None;
    run.iterations_used = 0;
    run.created_at = Clock::get()?.unix_timestamp;
    run.started_at = None;
    run.ended_at = None;
    run.bump = ctx.bumps.run_account;

    Ok(())
}
