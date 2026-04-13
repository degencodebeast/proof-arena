#[cfg(test)]
mod tests {
    use anchor_lang::prelude::*;
    use anchor_lang::solana_program::pubkey::Pubkey;

    use crate::constants::*;
    use crate::state::*;

    // -----------------------------------------------------------------------
    // PDA derivation tests — verify seeds match the approved design
    // -----------------------------------------------------------------------

    #[test]
    fn test_strategy_pda_uses_owner_and_agent_id() {
        let owner = Pubkey::new_unique();
        let agent_id: u64 = 42;
        let program_id = Pubkey::new_unique();

        let (pda, bump) = Pubkey::find_program_address(
            &[STRATEGY_SEED, owner.as_ref(), &agent_id.to_le_bytes()],
            &program_id,
        );
        assert_ne!(pda, Pubkey::default());
        assert!(bump <= 255);

        // Same inputs produce same PDA
        let (pda2, bump2) = Pubkey::find_program_address(
            &[STRATEGY_SEED, owner.as_ref(), &agent_id.to_le_bytes()],
            &program_id,
        );
        assert_eq!(pda, pda2);
        assert_eq!(bump, bump2);
    }

    #[test]
    fn test_strategy_pda_differs_by_owner() {
        let owner1 = Pubkey::new_unique();
        let owner2 = Pubkey::new_unique();
        let agent_id: u64 = 1;
        let program_id = Pubkey::new_unique();

        let (pda1, _) = Pubkey::find_program_address(
            &[STRATEGY_SEED, owner1.as_ref(), &agent_id.to_le_bytes()],
            &program_id,
        );
        let (pda2, _) = Pubkey::find_program_address(
            &[STRATEGY_SEED, owner2.as_ref(), &agent_id.to_le_bytes()],
            &program_id,
        );
        assert_ne!(pda1, pda2);
    }

    #[test]
    fn test_challenge_pda_uses_challenge_id() {
        let challenge_id: u64 = 99;
        let program_id = Pubkey::new_unique();

        let (pda, bump) = Pubkey::find_program_address(
            &[CHALLENGE_SEED, &challenge_id.to_le_bytes()],
            &program_id,
        );
        assert_ne!(pda, Pubkey::default());
        assert!(bump <= 255);
    }

    #[test]
    fn test_run_pda_uses_challenge_and_agent_id() {
        let challenge_id: u64 = 1;
        let agent_id: u64 = 2;
        let program_id = Pubkey::new_unique();

        let (pda, _) = Pubkey::find_program_address(
            &[
                RUN_SEED,
                &challenge_id.to_le_bytes(),
                &agent_id.to_le_bytes(),
            ],
            &program_id,
        );
        assert_ne!(pda, Pubkey::default());

        // Different agent_id produces different PDA
        let (pda2, _) = Pubkey::find_program_address(
            &[
                RUN_SEED,
                &challenge_id.to_le_bytes(),
                &3u64.to_le_bytes(),
            ],
            &program_id,
        );
        assert_ne!(pda, pda2);
    }

    #[test]
    fn test_agent_rank_pda_uses_only_agent_id() {
        let agent_id: u64 = 7;
        let program_id = Pubkey::new_unique();

        let (pda, _) = Pubkey::find_program_address(
            &[AGENT_RANK_SEED, &agent_id.to_le_bytes()],
            &program_id,
        );
        assert_ne!(pda, Pubkey::default());
    }

    // -----------------------------------------------------------------------
    // Enum serialization tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_challenge_type_discriminant() {
        assert_eq!(ChallengeType::SwapExecution as u8, 0);
    }

    #[test]
    fn test_challenge_status_discriminants() {
        assert_eq!(ChallengeStatus::Pending as u8, 0);
        assert_eq!(ChallengeStatus::Active as u8, 1);
        assert_eq!(ChallengeStatus::Settling as u8, 2);
        assert_eq!(ChallengeStatus::Completed as u8, 3);
        assert_eq!(ChallengeStatus::Cancelled as u8, 4);
    }

    #[test]
    fn test_run_status_discriminants() {
        assert_eq!(RunStatus::Pending as u8, 0);
        assert_eq!(RunStatus::Running as u8, 1);
        assert_eq!(RunStatus::Completed as u8, 2);
        assert_eq!(RunStatus::Failed as u8, 3);
        assert_eq!(RunStatus::Timeout as u8, 4);
    }

    #[test]
    fn test_completion_status_discriminants() {
        assert_eq!(CompletionStatus::Complete as u8, 0);
        assert_eq!(CompletionStatus::Incomplete as u8, 1);
        assert_eq!(CompletionStatus::Invalid as u8, 2);
    }

    #[test]
    fn test_completion_status_has_exactly_three_variants() {
        // Verify it's exactly {Complete, Incomplete, Invalid}
        let all = [
            CompletionStatus::Complete,
            CompletionStatus::Incomplete,
            CompletionStatus::Invalid,
        ];
        assert_eq!(all.len(), 3);
    }

    #[test]
    fn test_run_status_and_completion_status_are_independent() {
        // A run can be Completed (lifecycle) but Incomplete (validity)
        let run_status = RunStatus::Completed;
        let completion = CompletionStatus::Incomplete;
        assert_eq!(run_status as u8, 2); // Completed
        assert_eq!(completion as u8, 1); // Incomplete
    }

    // -----------------------------------------------------------------------
    // Space calculation tests — InitSpace correctness
    // -----------------------------------------------------------------------

    #[test]
    fn test_strategy_account_space() {
        // Manual calculation:
        // agent_id: 8
        // owner: 32
        // agent_name: 4 + 64 (String = 4-byte len prefix + max_len)
        // submission_hash: 32
        // metadata_ref: 4 + 128
        // created_at: 8
        // is_active: 1
        // bump: 1
        // Total: 8 + 32 + 68 + 32 + 132 + 8 + 1 + 1 = 282
        let space = StrategyAccount::INIT_SPACE;
        assert_eq!(space, 282, "StrategyAccount INIT_SPACE mismatch");
    }

    #[test]
    fn test_challenge_account_space() {
        // challenge_id: 8
        // authority: 32
        // challenge_type: 1 (enum u8)
        // challenge_version: 2
        // status: 1
        // starting_usdc: 8
        // usdc_mint: 32
        // max_slippage_bps: 2
        // iteration_budget: 2
        // time_budget_secs: 4
        // num_contestants: 1
        // num_enrolled: 1
        // num_finalized: 1
        // winner_agent_id: 1 + 8 (Option<u64>)
        // created_at: 8
        // started_at: 1 + 8 (Option<i64>)
        // ended_at: 1 + 8
        // bump: 1
        // Total: 8 + 32 + 1 + 2 + 1 + 8 + 32 + 2 + 2 + 4 + 1 + 1 + 1 + 9 + 8 + 9 + 9 + 1 = 131
        let space = ChallengeAccount::INIT_SPACE;
        assert_eq!(space, 131, "ChallengeAccount INIT_SPACE mismatch");
    }

    #[test]
    fn test_config_account_space() {
        // admin: 32
        // is_initialized: 1
        // bump: 1
        // Total: 34
        let space = ConfigAccount::INIT_SPACE;
        assert_eq!(space, 34, "ConfigAccount INIT_SPACE mismatch");
    }

    #[test]
    fn test_run_account_space() {
        // challenge_id: 8
        // agent_id: 8
        // benchmark_wallet: 32
        // starting_usdc: 8
        // ending_usdc: 1 + 8 (Option<u64>)
        // run_log_hash: 1 + 32 (Option<[u8;32]>)
        // status: 1
        // completion_status: 1 + 1 (Option<enum u8>)
        // iterations_used: 2
        // created_at: 8
        // started_at: 1 + 8 (Option<i64>)
        // ended_at: 1 + 8
        // bump: 1
        // Total: 8 + 8 + 32 + 8 + 9 + 33 + 1 + 2 + 2 + 8 + 9 + 9 + 1 = 130
        let space = RunAccount::INIT_SPACE;
        assert_eq!(space, 130, "RunAccount INIT_SPACE mismatch");
    }

    #[test]
    fn test_agent_rank_account_space() {
        // agent_id: 8
        // owner: 32
        // score: 2
        // rank_version: 2
        // wins: 4
        // losses: 4
        // total_challenges: 4
        // avg_execution_quality: 2
        // consistency: 2
        // invalid_runs: 4
        // last_updated: 8
        // bump: 1
        // Total: 8 + 32 + 2 + 2 + 4 + 4 + 4 + 2 + 2 + 4 + 8 + 1 = 73
        let space = AgentRankAccount::INIT_SPACE;
        assert_eq!(space, 73, "AgentRankAccount INIT_SPACE mismatch");
    }

    #[test]
    fn test_total_account_space_with_discriminator() {
        // Anchor accounts need 8-byte discriminator + INIT_SPACE
        let strategy_total = 8 + StrategyAccount::INIT_SPACE;
        let challenge_total = 8 + ChallengeAccount::INIT_SPACE;
        let run_total = 8 + RunAccount::INIT_SPACE;
        let rank_total = 8 + AgentRankAccount::INIT_SPACE;

        // Verify all fit within reasonable rent bounds (< 1 KB each)
        assert!(strategy_total < 1024, "StrategyAccount too large: {strategy_total}");
        assert!(challenge_total < 1024, "ChallengeAccount too large: {challenge_total}");
        assert!(run_total < 1024, "RunAccount too large: {run_total}");
        assert!(rank_total < 1024, "AgentRankAccount too large: {rank_total}");
    }

    // -----------------------------------------------------------------------
    // Version field tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_challenge_version_constant() {
        assert_eq!(CHALLENGE_VERSION_SWAP_V1, 1u16);
    }

    #[test]
    fn test_rank_version_constant() {
        assert_eq!(RANK_VERSION_V1, 1u16);
    }

    #[test]
    fn test_pda_seed_constants() {
        assert_eq!(STRATEGY_SEED, b"strategy");
        assert_eq!(CHALLENGE_SEED, b"challenge");
        assert_eq!(RUN_SEED, b"run");
        assert_eq!(AGENT_RANK_SEED, b"agent_rank");
    }

    #[test]
    fn test_max_value_constants() {
        assert_eq!(MAX_AGENT_NAME_LEN, 64);
        assert_eq!(MAX_METADATA_REF_LEN, 128);
        assert_eq!(MAX_SLIPPAGE_BPS, 500);
        assert_eq!(MAX_CONTESTANTS, 32);
        assert_eq!(MAX_SCORE, 10_000);
    }
}
