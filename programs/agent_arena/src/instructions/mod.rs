pub mod initialize;
pub mod register_strategy;
pub mod create_challenge;
pub mod create_run;
pub mod start_challenge;
pub mod finalize_run;
pub mod settle_challenge;
pub mod update_agent_rank;

#[cfg(test)]
mod tests;

// Glob re-exports required — Anchor's #[program] macro generates code
// that references Context<T> types from these modules. Explicit exports
// cause unresolved import errors in the macro expansion.
pub use initialize::*;
pub use register_strategy::*;
pub use create_challenge::*;
pub use create_run::*;
pub use start_challenge::*;
pub use finalize_run::*;
pub use settle_challenge::*;
pub use update_agent_rank::*;
