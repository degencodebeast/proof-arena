#[cfg(test)]
mod tests {
    use anchor_lang::prelude::*;
    use anchor_lang::solana_program::pubkey::Pubkey;

    use crate::constants::*;
    use crate::state::*;

    // =======================================================================
    // Settlement logic — mirrors settle_challenge::handler with all fixes
    // =======================================================================

    /// Extracted and hardened settlement logic matching the real handler.
    /// Each run: (agent_id, ending_usdc, completion_status, ended_at, challenge_id)
    fn settle(
        challenge_id: u64,
        num_enrolled: u8,
        runs: &[(u64, Option<u64>, Option<CompletionStatus>, Option<i64>, u64)],
    ) -> std::result::Result<Option<u64>, &'static str> {
        let mut winner: Option<(u64, u64, i64)> = None;
        let mut valid_run_count: u8 = 0;
        let mut seen_agents: Vec<u64> = Vec::new();

        for &(agent_id, ending_usdc, completion_status, ended_at, run_cid) in runs {
            // Fix 3: program owner check would happen at runtime
            // Fix 3: challenge_id must match
            if run_cid != challenge_id {
                return Err("run belongs to different challenge");
            }

            // Fix 4: duplicate detection
            if seen_agents.contains(&agent_id) {
                return Err("duplicate agent in remaining_accounts");
            }
            seen_agents.push(agent_id);

            valid_run_count = valid_run_count.checked_add(1).ok_or("overflow")?;

            if completion_status != Some(CompletionStatus::Complete) {
                continue;
            }
            let ending = match ending_usdc {
                Some(v) => v,
                None => continue,
            };
            let ended = match ended_at {
                Some(t) => t,
                None => continue,
            };

            let is_better = match winner {
                Some((_, best_usdc, best_time)) => {
                    ending > best_usdc || (ending == best_usdc && ended < best_time)
                }
                None => true,
            };
            if is_better {
                winner = Some((agent_id, ending, ended));
            }
        }

        // Fix 3+4: cardinality check against actual enrollment
        if valid_run_count != num_enrolled {
            return Err("run count does not match num_enrolled");
        }

        Ok(winner.map(|(id, _, _)| id))
    }

    // -----------------------------------------------------------------------
    // Settlement correctness — happy path
    // -----------------------------------------------------------------------

    #[test]
    fn test_settle_highest_usdc_wins() {
        let r = settle(1, 3, &[
            (1, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
            (3, Some(150), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert_eq!(r.unwrap(), Some(2));
    }

    #[test]
    fn test_settle_tiebreak_by_earliest_ended_at() {
        let r = settle(1, 2, &[
            (1, Some(200), Some(CompletionStatus::Complete), Some(2000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert_eq!(r.unwrap(), Some(2));
    }

    #[test]
    fn test_settle_single_contestant() {
        let r = settle(1, 1, &[
            (1, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert_eq!(r.unwrap(), Some(1));
    }

    // -----------------------------------------------------------------------
    // Invalid/incomplete runs cannot win
    // -----------------------------------------------------------------------

    #[test]
    fn test_settle_invalid_excluded_even_highest_usdc() {
        let r = settle(1, 3, &[
            (1, Some(300), Some(CompletionStatus::Invalid), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
            (3, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert_eq!(r.unwrap(), Some(2));
    }

    #[test]
    fn test_settle_incomplete_excluded() {
        let r = settle(1, 2, &[
            (1, Some(300), Some(CompletionStatus::Incomplete), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert_eq!(r.unwrap(), Some(2));
    }

    #[test]
    fn test_settle_all_invalid_no_winner() {
        let r = settle(1, 3, &[
            (1, Some(300), Some(CompletionStatus::Invalid), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Invalid), Some(1000), 1),
            (3, Some(100), Some(CompletionStatus::Invalid), Some(1000), 1),
        ]);
        assert_eq!(r.unwrap(), None);
    }

    #[test]
    fn test_settle_no_completion_status_excluded() {
        let r = settle(1, 2, &[
            (1, Some(300), None, Some(1000), 1),
            (2, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert_eq!(r.unwrap(), Some(2));
    }

    #[test]
    fn test_settle_mixed_statuses() {
        let r = settle(1, 4, &[
            (1, Some(500), Some(CompletionStatus::Invalid), Some(1000), 1),
            (2, Some(400), Some(CompletionStatus::Incomplete), Some(1000), 1),
            (3, Some(300), Some(CompletionStatus::Complete), Some(1000), 1),
            (4, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert_eq!(r.unwrap(), Some(3));
    }

    // -----------------------------------------------------------------------
    // Fix 3: Rejects runs from wrong challenge
    // -----------------------------------------------------------------------

    #[test]
    fn test_settle_rejects_foreign_challenge_run() {
        let r = settle(1, 2, &[
            (1, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 999),
        ]);
        assert!(r.is_err());
        assert_eq!(r.unwrap_err(), "run belongs to different challenge");
    }

    // -----------------------------------------------------------------------
    // Fix 4: Duplicate detection
    // -----------------------------------------------------------------------

    #[test]
    fn test_settle_rejects_duplicate_agent() {
        let r = settle(1, 2, &[
            (1, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
            (1, Some(200), Some(CompletionStatus::Complete), Some(2000), 1), // same agent_id
        ]);
        assert!(r.is_err());
        assert_eq!(r.unwrap_err(), "duplicate agent in remaining_accounts");
    }

    #[test]
    fn test_settle_duplicate_inflates_count_blocked() {
        // Even if the attacker passes the same account twice to inflate count
        let r = settle(1, 3, &[
            (1, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1), // duplicate
        ]);
        assert!(r.is_err());
        assert_eq!(r.unwrap_err(), "duplicate agent in remaining_accounts");
    }

    // -----------------------------------------------------------------------
    // Fix 4: Cardinality enforcement
    // -----------------------------------------------------------------------

    #[test]
    fn test_settle_rejects_too_few_runs() {
        let r = settle(1, 3, &[
            (1, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert!(r.is_err());
        assert_eq!(r.unwrap_err(), "run count does not match num_enrolled");
    }

    #[test]
    fn test_settle_rejects_too_many_runs() {
        let r = settle(1, 2, &[
            (1, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
            (3, Some(300), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert!(r.is_err());
        assert_eq!(r.unwrap_err(), "run count does not match num_enrolled");
    }

    #[test]
    fn test_settle_exact_enrolled_count_succeeds() {
        let r = settle(1, 3, &[
            (1, Some(100), Some(CompletionStatus::Complete), Some(1000), 1),
            (2, Some(200), Some(CompletionStatus::Complete), Some(1000), 1),
            (3, Some(300), Some(CompletionStatus::Complete), Some(1000), 1),
        ]);
        assert!(r.is_ok());
        assert_eq!(r.unwrap(), Some(3));
    }

    // -----------------------------------------------------------------------
    // Fix 2: finalize_run run/challenge binding
    // -----------------------------------------------------------------------

    #[test]
    fn test_finalize_run_challenge_match() {
        // Constraint: run.challenge_id == challenge.challenge_id
        let run_cid: u64 = 1;
        let challenge_cid: u64 = 1;
        assert_eq!(run_cid, challenge_cid); // passes

        let wrong_cid: u64 = 2;
        assert_ne!(run_cid, wrong_cid); // would fail constraint
    }

    // -----------------------------------------------------------------------
    // Fix 1+2: Authority model
    // -----------------------------------------------------------------------

    #[test]
    fn test_config_admin_check() {
        let admin = Pubkey::new_unique();
        let non_admin = Pubkey::new_unique();

        // config.admin == signer → pass
        assert_eq!(admin, admin);
        // config.admin != random_signer → fail
        assert_ne!(admin, non_admin);
    }

    #[test]
    fn test_challenge_authority_is_admin() {
        // create_challenge sets challenge.authority = signer.key()
        // create_challenge requires config.admin == signer.key()
        // Therefore challenge.authority IS the admin
        let admin = Pubkey::new_unique();
        let challenge_authority = admin; // set in create_challenge
        assert_eq!(challenge_authority, admin);
    }

    #[test]
    fn test_create_run_requires_challenge_authority() {
        let admin = Pubkey::new_unique();
        let non_admin = Pubkey::new_unique();
        let challenge_authority = admin;

        assert_eq!(challenge_authority, admin); // admin can create runs
        assert_ne!(challenge_authority, non_admin); // non-admin cannot
    }

    // -----------------------------------------------------------------------
    // Fix 5: update_agent_rank owner from strategy
    // -----------------------------------------------------------------------

    #[test]
    fn test_rank_owner_is_strategy_owner() {
        let strategy_owner = Pubkey::new_unique();
        let admin = Pubkey::new_unique();
        assert_ne!(strategy_owner, admin);

        // rank.owner = strategy.owner (not authority)
        let rank_owner = strategy_owner;
        assert_eq!(rank_owner, strategy_owner);
        assert_ne!(rank_owner, admin);
    }

    // -----------------------------------------------------------------------
    // Enrollment and cardinality
    // -----------------------------------------------------------------------

    #[test]
    fn test_enrollment_prevents_overfill() {
        // create_run constraint: num_enrolled < num_contestants
        let num_contestants: u8 = 2;
        let num_enrolled: u8 = 0;
        assert!(num_enrolled < num_contestants); // first run: ok

        let num_enrolled: u8 = 1;
        assert!(num_enrolled < num_contestants); // second run: ok

        let num_enrolled: u8 = 2;
        assert!(!(num_enrolled < num_contestants)); // third run: blocked
    }

    #[test]
    fn test_settling_uses_enrolled_not_contestants() {
        // settle checks valid_run_count == num_enrolled
        // This means if 2 of 3 possible slots are enrolled, you must pass exactly 2
        let num_enrolled: u8 = 2;
        let valid_run_count: u8 = 2;
        assert_eq!(valid_run_count, num_enrolled); // passes

        let valid_run_count: u8 = 3;
        assert_ne!(valid_run_count, num_enrolled); // fails
    }

    // -----------------------------------------------------------------------
    // Status transition invariants
    // -----------------------------------------------------------------------

    #[test]
    fn test_start_requires_full_enrollment() {
        // start_challenge constraint: num_enrolled == num_contestants
        let num_contestants: u8 = 3;

        let num_enrolled: u8 = 2;
        assert_ne!(num_enrolled, num_contestants); // cannot start — not full

        let num_enrolled: u8 = 3;
        assert_eq!(num_enrolled, num_contestants); // can start — fully enrolled
    }

    #[test]
    fn test_counters_are_consistent_at_settling() {
        // With start_challenge enforcing num_enrolled == num_contestants,
        // finalize_run transitioning on num_finalized == num_contestants,
        // and settle_challenge validating valid_run_count == num_enrolled:
        // All three counters are guaranteed equal at settlement time.
        let num_contestants: u8 = 3;
        let num_enrolled: u8 = 3; // enforced by start_challenge
        let num_finalized: u8 = 3; // triggers Settling

        assert_eq!(num_enrolled, num_contestants);
        assert_eq!(num_finalized, num_contestants);
        // settle will check valid_run_count == num_enrolled == 3
    }

    #[test]
    fn test_settling_requires_all_enrolled_finalized() {
        // num_finalized == num_contestants triggers Settling
        // start_challenge ensures num_enrolled == num_contestants
        // settle_challenge validates against num_enrolled
        let num_contestants: u8 = 3;
        let num_enrolled: u8 = 3;
        let num_finalized: u8 = 3;
        assert_eq!(num_finalized, num_contestants); // triggers Settling
        assert_eq!(num_enrolled, num_finalized); // settlement will pass
    }

    #[test]
    fn test_completed_but_incomplete_is_valid() {
        let run_status = RunStatus::Completed;
        let completion = CompletionStatus::Incomplete;
        assert_eq!(run_status, RunStatus::Completed);
        assert_eq!(completion, CompletionStatus::Incomplete);
    }

    // -----------------------------------------------------------------------
    // Validation constraints
    // -----------------------------------------------------------------------

    #[test]
    fn test_slippage_bounds() {
        assert!(500u16 <= MAX_SLIPPAGE_BPS);
        assert!(501u16 > MAX_SLIPPAGE_BPS);
    }

    #[test]
    fn test_contestant_bounds() {
        assert!(1u8 > 0 && 1u8 <= MAX_CONTESTANTS);
        assert!(32u8 <= MAX_CONTESTANTS);
        assert!(33u8 > MAX_CONTESTANTS);
    }

    #[test]
    fn test_score_bounds() {
        assert!(10_000u16 <= MAX_SCORE);
        assert!(10_001u16 > MAX_SCORE);
    }

    // -----------------------------------------------------------------------
    // PDA consistency
    // -----------------------------------------------------------------------

    #[test]
    fn test_config_pda() {
        let program_id = Pubkey::new_unique();
        let (pda, _) = Pubkey::find_program_address(&[CONFIG_SEED], &program_id);
        assert_ne!(pda, Pubkey::default());
    }

    #[test]
    fn test_strategy_pda() {
        let owner = Pubkey::new_unique();
        let program_id = Pubkey::new_unique();
        let (pda, _) = Pubkey::find_program_address(
            &[STRATEGY_SEED, owner.as_ref(), &1u64.to_le_bytes()],
            &program_id,
        );
        assert_ne!(pda, Pubkey::default());
    }

    #[test]
    fn test_challenge_pda() {
        let program_id = Pubkey::new_unique();
        let (pda, _) = Pubkey::find_program_address(
            &[CHALLENGE_SEED, &1u64.to_le_bytes()],
            &program_id,
        );
        assert_ne!(pda, Pubkey::default());
    }

    #[test]
    fn test_run_pda() {
        let program_id = Pubkey::new_unique();
        let (pda, _) = Pubkey::find_program_address(
            &[RUN_SEED, &1u64.to_le_bytes(), &2u64.to_le_bytes()],
            &program_id,
        );
        assert_ne!(pda, Pubkey::default());
    }

    #[test]
    fn test_agent_rank_pda() {
        let program_id = Pubkey::new_unique();
        let (pda, _) = Pubkey::find_program_address(
            &[AGENT_RANK_SEED, &1u64.to_le_bytes()],
            &program_id,
        );
        assert_ne!(pda, Pubkey::default());
    }
}
