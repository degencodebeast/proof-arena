/// PDA seed constants — single source of truth for all PDA derivations.
///
/// These MUST match the seeds used in instruction account constraints.
/// Off-chain (anchorpy) PDA derivation must use the same seeds.

// PDA seeds
pub const CONFIG_SEED: &[u8] = b"config";
pub const STRATEGY_SEED: &[u8] = b"strategy";
pub const CHALLENGE_SEED: &[u8] = b"challenge";
pub const RUN_SEED: &[u8] = b"run";
pub const AGENT_RANK_SEED: &[u8] = b"agent_rank";

// Version mappings (on-chain numeric -> off-chain symbolic)
// challenge_type: u8 enum
//   0 = SwapExecution (V1)
//   Future: 1 = YieldSprint, etc.

// challenge_version: u16
//   1 = swap_execution_v1
pub const CHALLENGE_VERSION_SWAP_V1: u16 = 1;

// rank_version: u16
//   1 = rank_v1
pub const RANK_VERSION_V1: u16 = 1;

// Max value constraints
pub const MAX_AGENT_NAME_LEN: usize = 64;
pub const MAX_METADATA_REF_LEN: usize = 128;
pub const MAX_SLIPPAGE_BPS: u16 = 500;
pub const MAX_CONTESTANTS: u8 = 32;
pub const MAX_SCORE: u16 = 10_000;
