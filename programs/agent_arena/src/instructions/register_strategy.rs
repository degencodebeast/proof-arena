use anchor_lang::prelude::*;

use crate::constants::*;
use crate::errors::AgentArenaError;
use crate::events::StrategyRegistered;
use crate::state::StrategyAccount;

#[derive(Accounts)]
#[instruction(agent_id: u64)]
pub struct RegisterStrategy<'info> {
    #[account(
        init,
        payer = owner,
        space = 8 + StrategyAccount::INIT_SPACE,
        seeds = [STRATEGY_SEED, owner.key().as_ref(), &agent_id.to_le_bytes()],
        bump,
    )]
    pub strategy_account: Account<'info, StrategyAccount>,

    #[account(mut)]
    pub owner: Signer<'info>,

    pub system_program: Program<'info, System>,
}

pub fn handler(
    ctx: Context<RegisterStrategy>,
    agent_id: u64,
    agent_name: String,
    submission_hash: [u8; 32],
    metadata_ref: String,
) -> Result<()> {
    require!(
        agent_name.len() <= MAX_AGENT_NAME_LEN,
        AgentArenaError::InvalidAgentName
    );
    require!(
        metadata_ref.len() <= MAX_METADATA_REF_LEN,
        AgentArenaError::InvalidMetadataRef
    );

    let strategy = &mut ctx.accounts.strategy_account;
    strategy.agent_id = agent_id;
    strategy.owner = ctx.accounts.owner.key();
    strategy.agent_name = agent_name.clone();
    strategy.submission_hash = submission_hash;
    strategy.metadata_ref = metadata_ref;
    strategy.created_at = Clock::get()?.unix_timestamp;
    strategy.is_active = true;
    strategy.bump = ctx.bumps.strategy_account;

    emit!(StrategyRegistered {
        agent_id,
        owner: ctx.accounts.owner.key(),
        agent_name,
        submission_hash,
        created_at: strategy.created_at,
    });

    Ok(())
}
