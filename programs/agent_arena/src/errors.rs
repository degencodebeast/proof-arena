use anchor_lang::prelude::*;

#[error_code]
pub enum AgentArenaError {
    #[msg("Agent name exceeds maximum length of 64 characters")]
    InvalidAgentName,

    #[msg("Metadata reference exceeds maximum length of 128 characters")]
    InvalidMetadataRef,

    #[msg("Challenge has reached maximum number of contestants")]
    ChallengeFull,

    #[msg("Challenge is not in the required status for this operation")]
    InvalidChallengeStatus,

    #[msg("Caller is not the authorized authority for this operation")]
    UnauthorizedAuthority,

    #[msg("Invalid status transition for this entity")]
    InvalidStatusTransition,

    #[msg("Run has already been finalized")]
    RunAlreadyFinalized,

    #[msg("Challenge cannot be settled in its current state")]
    ChallengeNotSettleable,

    #[msg("Slippage exceeds maximum allowed basis points")]
    InvalidSlippage,

    #[msg("Iteration or time budget exceeded")]
    BudgetExceeded,

    #[msg("Agent is not registered or strategy not found")]
    AgentNotRegistered,

    #[msg("Agent is already registered for this challenge")]
    DuplicateAgent,

    #[msg("Invalid challenge type")]
    InvalidChallengeType,

    #[msg("Invalid challenge version")]
    InvalidChallengeVersion,

    #[msg("Number of contestants must be greater than zero")]
    InvalidContestantCount,

    #[msg("Run is not in the required status for this operation")]
    InvalidRunStatus,

    #[msg("Arithmetic overflow")]
    Overflow,

    #[msg("Score exceeds maximum value of 10000")]
    InvalidScore,
}
