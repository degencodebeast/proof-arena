use anchor_lang::prelude::*;

use crate::constants::*;
use crate::errors::AgentArenaError;
use crate::events::ChallengeStarted;
use crate::state::{ChallengeAccount, ChallengeStatus};

#[derive(Accounts)]
pub struct StartChallenge<'info> {
    #[account(
        mut,
        seeds = [CHALLENGE_SEED, &challenge_account.challenge_id.to_le_bytes()],
        bump = challenge_account.bump,
        constraint = challenge_account.authority == authority.key()
            @ AgentArenaError::UnauthorizedAuthority,
        constraint = challenge_account.status == ChallengeStatus::Pending
            @ AgentArenaError::InvalidChallengeStatus,
        // All contestants must be enrolled before starting
        constraint = challenge_account.num_enrolled == challenge_account.num_contestants
            @ AgentArenaError::InvalidContestantCount,
    )]
    pub challenge_account: Account<'info, ChallengeAccount>,

    pub authority: Signer<'info>,
}

pub fn handler(ctx: Context<StartChallenge>) -> Result<()> {
    let challenge = &mut ctx.accounts.challenge_account;
    let now = Clock::get()?.unix_timestamp;

    challenge.status = ChallengeStatus::Active;
    challenge.started_at = Some(now);

    emit!(ChallengeStarted {
        challenge_id: challenge.challenge_id,
        started_at: now,
    });

    Ok(())
}
