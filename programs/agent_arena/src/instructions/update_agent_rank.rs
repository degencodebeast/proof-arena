use anchor_lang::prelude::*;

use crate::constants::*;
use crate::errors::AgentArenaError;
use crate::events::AgentRankUpdated;
use crate::state::{AgentRankAccount, ConfigAccount, StrategyAccount};

#[derive(Accounts)]
#[instruction(agent_id: u64)]
pub struct UpdateAgentRank<'info> {
    #[account(
        init_if_needed,
        payer = authority,
        space = 8 + AgentRankAccount::INIT_SPACE,
        seeds = [AGENT_RANK_SEED, &agent_id.to_le_bytes()],
        bump,
    )]
    pub agent_rank_account: Account<'info, AgentRankAccount>,

    /// Strategy account proves the real owner of this agent.
    #[account(
        constraint = strategy_account.agent_id == agent_id
            @ AgentArenaError::AgentNotRegistered,
        constraint = strategy_account.is_active
            @ AgentArenaError::AgentNotRegistered,
    )]
    pub strategy_account: Account<'info, StrategyAccount>,

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
    ctx: Context<UpdateAgentRank>,
    agent_id: u64,
    score: u16,
    rank_version: u16,
    wins: u32,
    losses: u32,
    total_challenges: u32,
    avg_execution_quality: u16,
    consistency: u16,
    invalid_runs: u32,
) -> Result<()> {
    require!(score <= MAX_SCORE, AgentArenaError::InvalidScore);

    let rank = &mut ctx.accounts.agent_rank_account;
    let strategy = &ctx.accounts.strategy_account;

    // Initialize on first creation
    if rank.agent_id == 0 {
        rank.agent_id = agent_id;
        // Owner comes from strategy, not authority (fix 5)
        rank.owner = strategy.owner;
        rank.bump = ctx.bumps.agent_rank_account;
    }

    rank.score = score;
    rank.rank_version = rank_version;
    rank.wins = wins;
    rank.losses = losses;
    rank.total_challenges = total_challenges;
    rank.avg_execution_quality = avg_execution_quality;
    rank.consistency = consistency;
    rank.invalid_runs = invalid_runs;
    rank.last_updated = Clock::get()?.unix_timestamp;

    emit!(AgentRankUpdated {
        agent_id,
        score,
        rank_version,
        wins,
        losses,
        total_challenges,
    });

    Ok(())
}
