use anchor_lang::prelude::*;

pub mod constants;
pub mod errors;
pub mod events;
pub mod instructions;
pub mod state;

use instructions::*;
use state::*;

declare_id!("GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu");

#[program]
pub mod agent_arena {
    use super::*;

    /// Initialize program config with admin pubkey. One-time setup.
    pub fn initialize(ctx: Context<Initialize>) -> Result<()> {
        instructions::initialize::handler(ctx)
    }

    /// Register a new strategy. Owner-signed (not authority).
    pub fn register_strategy(
        ctx: Context<RegisterStrategy>,
        agent_id: u64,
        agent_name: String,
        submission_hash: [u8; 32],
        metadata_ref: String,
    ) -> Result<()> {
        instructions::register_strategy::handler(
            ctx,
            agent_id,
            agent_name,
            submission_hash,
            metadata_ref,
        )
    }

    /// Create a new challenge. Authority-only.
    pub fn create_challenge(
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
        instructions::create_challenge::handler(
            ctx,
            challenge_id,
            challenge_type,
            challenge_version,
            starting_usdc,
            usdc_mint,
            max_slippage_bps,
            iteration_budget,
            time_budget_secs,
            num_contestants,
        )
    }

    /// Create a run for an agent in a challenge. Authority-only.
    pub fn create_run(
        ctx: Context<CreateRun>,
        challenge_id: u64,
        agent_id: u64,
        benchmark_wallet: Pubkey,
    ) -> Result<()> {
        instructions::create_run::handler(ctx, challenge_id, agent_id, benchmark_wallet)
    }

    /// Start a pending challenge. Authority-only.
    pub fn start_challenge(ctx: Context<StartChallenge>) -> Result<()> {
        instructions::start_challenge::handler(ctx)
    }

    /// Finalize a completed run with results. Authority-only.
    pub fn finalize_run(
        ctx: Context<FinalizeRun>,
        ending_usdc: u64,
        run_log_hash: [u8; 32],
        completion_status: CompletionStatus,
        iterations_used: u16,
    ) -> Result<()> {
        instructions::finalize_run::handler(
            ctx,
            ending_usdc,
            run_log_hash,
            completion_status,
            iterations_used,
        )
    }

    /// Settle a challenge and determine winner. Authority-only.
    /// Pass all RunAccount PDAs as remaining_accounts.
    pub fn settle_challenge(ctx: Context<SettleChallenge>) -> Result<()> {
        instructions::settle_challenge::handler(ctx)
    }

    /// Create or update an agent's rank record. Authority-only.
    pub fn update_agent_rank(
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
        instructions::update_agent_rank::handler(
            ctx,
            agent_id,
            score,
            rank_version,
            wins,
            losses,
            total_challenges,
            avg_execution_quality,
            consistency,
            invalid_runs,
        )
    }
}
