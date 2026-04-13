use anchor_lang::prelude::*;

use crate::constants::*;
use crate::errors::AgentArenaError;
use crate::events::ChallengeSettled;
use crate::state::{ChallengeAccount, ChallengeStatus, CompletionStatus, RunAccount};

#[derive(Accounts)]
pub struct SettleChallenge<'info> {
    #[account(
        mut,
        seeds = [CHALLENGE_SEED, &challenge_account.challenge_id.to_le_bytes()],
        bump = challenge_account.bump,
        constraint = challenge_account.authority == authority.key()
            @ AgentArenaError::UnauthorizedAuthority,
        constraint = challenge_account.status == ChallengeStatus::Settling
            @ AgentArenaError::ChallengeNotSettleable,
    )]
    pub challenge_account: Account<'info, ChallengeAccount>,

    pub authority: Signer<'info>,
    // remaining_accounts: all RunAccount PDAs for this challenge
}

pub fn handler(ctx: Context<SettleChallenge>) -> Result<()> {
    let challenge = &mut ctx.accounts.challenge_account;
    let challenge_id = challenge.challenge_id;
    let num_enrolled = challenge.num_enrolled;
    let now = Clock::get()?.unix_timestamp;

    // Track best: (agent_id, ending_usdc, ended_at)
    let mut winner: Option<(u64, u64, i64)> = None;
    let mut valid_run_count: u8 = 0;
    // Duplicate detection: track seen agent_ids (max 32 contestants)
    let mut seen_agents: [u64; 32] = [0u64; 32];
    let mut seen_count: usize = 0;

    for account_info in ctx.remaining_accounts.iter() {
        // Verify account is owned by this program — reject foreign accounts
        require!(
            account_info.owner == ctx.program_id,
            AgentArenaError::AgentNotRegistered
        );

        // Deserialize RunAccount
        let mut data: &[u8] = &account_info.try_borrow_data()?;
        let run = RunAccount::try_deserialize(&mut data)?;

        // Verify this run belongs to the challenge being settled
        require!(
            run.challenge_id == challenge_id,
            AgentArenaError::InvalidRunStatus
        );

        // Duplicate detection: reject if we've already seen this agent_id
        let is_duplicate = seen_agents[..seen_count].contains(&run.agent_id);
        require!(!is_duplicate, AgentArenaError::DuplicateAgent);
        require!(seen_count < 32, AgentArenaError::Overflow);
        seen_agents[seen_count] = run.agent_id;
        seen_count += 1;

        valid_run_count = valid_run_count
            .checked_add(1)
            .ok_or(AgentArenaError::Overflow)?;

        // CRITICAL: Only Complete runs can win
        if run.completion_status != Some(CompletionStatus::Complete) {
            continue;
        }

        let ending = match run.ending_usdc {
            Some(v) => v,
            None => continue,
        };

        let ended_at = match run.ended_at {
            Some(t) => t,
            None => continue,
        };

        let is_better = match winner {
            Some((_, best_usdc, best_time)) => {
                ending > best_usdc || (ending == best_usdc && ended_at < best_time)
            }
            None => true,
        };

        if is_better {
            winner = Some((run.agent_id, ending, ended_at));
        }
    }

    // Cardinality: must match the actual number of enrolled runs
    require!(
        valid_run_count == num_enrolled,
        AgentArenaError::InvalidContestantCount
    );

    challenge.winner_agent_id = winner.map(|(id, _, _)| id);
    challenge.status = ChallengeStatus::Completed;
    challenge.ended_at = Some(now);

    emit!(ChallengeSettled {
        challenge_id,
        winner_agent_id: challenge.winner_agent_id,
        ended_at: now,
    });

    Ok(())
}
