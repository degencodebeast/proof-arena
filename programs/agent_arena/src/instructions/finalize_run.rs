use anchor_lang::prelude::*;

use crate::constants::*;
use crate::errors::AgentArenaError;
use crate::events::RunFinalized;
use crate::state::{
    ChallengeAccount, ChallengeStatus, CompletionStatus, RunAccount, RunStatus,
};

#[derive(Accounts)]
pub struct FinalizeRun<'info> {
    #[account(
        mut,
        seeds = [
            RUN_SEED,
            &run_account.challenge_id.to_le_bytes(),
            &run_account.agent_id.to_le_bytes(),
        ],
        bump = run_account.bump,
        // Prove this run belongs to the challenge being mutated
        constraint = run_account.challenge_id == challenge_account.challenge_id
            @ AgentArenaError::InvalidRunStatus,
        constraint = run_account.status == RunStatus::Pending
            || run_account.status == RunStatus::Running
            @ AgentArenaError::RunAlreadyFinalized,
    )]
    pub run_account: Account<'info, RunAccount>,

    #[account(
        mut,
        seeds = [CHALLENGE_SEED, &challenge_account.challenge_id.to_le_bytes()],
        bump = challenge_account.bump,
        constraint = challenge_account.authority == authority.key()
            @ AgentArenaError::UnauthorizedAuthority,
    )]
    pub challenge_account: Account<'info, ChallengeAccount>,

    pub authority: Signer<'info>,
}

pub fn handler(
    ctx: Context<FinalizeRun>,
    ending_usdc: u64,
    run_log_hash: [u8; 32],
    completion_status: CompletionStatus,
    iterations_used: u16,
) -> Result<()> {
    let run = &mut ctx.accounts.run_account;
    let challenge = &mut ctx.accounts.challenge_account;
    let now = Clock::get()?.unix_timestamp;

    run.ending_usdc = Some(ending_usdc);
    run.run_log_hash = Some(run_log_hash);
    run.completion_status = Some(completion_status);
    run.iterations_used = iterations_used;
    run.status = RunStatus::Completed;
    run.ended_at = Some(now);

    // Increment finalized count
    challenge.num_finalized = challenge
        .num_finalized
        .checked_add(1)
        .ok_or(AgentArenaError::Overflow)?;

    // Transition to Settling if all runs finalized
    if challenge.num_finalized == challenge.num_contestants {
        challenge.status = ChallengeStatus::Settling;
    }

    emit!(RunFinalized {
        challenge_id: run.challenge_id,
        agent_id: run.agent_id,
        ending_usdc,
        completion_status: completion_status as u8,
        run_log_hash,
    });

    Ok(())
}
