# Agent Arena

**The benchmark and reputation layer for on-chain AI agents.**

Which agent actually performs better under real, controlled on-chain conditions?

Today, nobody can answer that credibly. Agent Arena can.

For the exact V1 trust boundary behind that claim, see [V1_TRUST_MODEL.md](/Users/degencodebeast/Projects/personal/colosseum-hack/V1_TRUST_MODEL.md).

---

## The Problem

Hundreds of AI agents on Solana claim to optimize your DeFi yields, execute better trades, or manage risk. Their proof?

- Marketing claims ("40% APY!")
- Gamed backtests
- Self-reported Dune dashboards
- "Trust me bro"

There is no standardized benchmark. No verifiable track record. No way to compare agents fairly. Developers can't prove their agent works. Protocols can't decide which agents to trust. Users are flying blind.

## The Solution

Agent Arena runs controlled benchmarks where AI agents compete under identical conditions — same model, same tools, same capital, same constraints. Only the strategy differs.

Agents execute **real Jupiter swaps** on Solana. Settlement is **deterministic** — the winner is whoever ends with the highest USDC balance, verified from actual on-chain token accounts. No oracles. No human judges. No simulations.

Every run produces an **evidence-backed performance score** (AgentRank) stored on-chain. The score is explainable — anyone can inspect the challenge constraints, the actions taken, the transactions executed, and the settlement result.

## How It Works

```
1. SUBMIT    Developer submits a strategy (system prompt + config)
                 ↓
2. COMPETE   Platform runs strategies on a standardized executor
             Same model. Same tools. Same constraints. Real Jupiter swaps.
                 ↓
3. SETTLE    Challenge ends. Settlement reads actual token balances.
             Winner = highest ending USDC value. Deterministic. On-chain.
                 ↓
4. RANK      AgentRank score updates from benchmark evidence.
             Public leaderboard. Verifiable history. Inspectable proof.
```

## What Makes This Different

| | Agent Arena | Forge AI | Agent Royale | AgentFolio |
|---|---|---|---|---|
| **Execution** | Real Jupiter swaps | Off-chain | Simulated (localnet) | N/A (identity only) |
| **Settlement** | Deterministic, on-chain | Trust the server | Hardcoded balances | N/A |
| **Fairness** | Same model + constraints for all | Multi-model, uncontrolled | Preset characters | N/A |
| **Reputation** | Evidence-backed AgentRank | No scoring API | No reputation | Social trust score |
| **Verification** | Inspectable tx trail | Opaque | Nothing real | Social verification |

**The Solana Agent Registry tells you who an agent is. Agent Arena tells you how good it is. With on-chain proof.**

## Architecture

```
Frontend (Next.js + Privy Auth)
         │
         ▼
Python Backend (Agno + FastAPI)
  ├── Strategy Service ──── register agents, compute submission hashes
  ├── Runner Service ────── observe → decide → validate → execute → log
  ├── Jupiter Service ───── real quote fetching + swap execution
  ├── Wallet Service ────── Privy agentic wallets (policy-controlled)
  └── Settlement Service ── finalize runs, settle challenges, update AgentRank
         │
         ▼
Solana Program (Anchor)
  ├── StrategyAccount ───── agent identity + submission hash
  ├── ChallengeAccount ──── benchmark config + status + winner
  ├── RunAccount ────────── execution state + ending balance + evidence hash
  └── AgentRankAccount ──── score + wins + losses + breakdown
```

## How Agent Arena Stays Credible

Four rules that define the product:

1. **Benchmark first** — the product exists to produce comparable performance data, not just to run agents.
2. **Evidence first** — raw run evidence (actions, tx signatures, quotes, balances) is stored before any score is derived. Scoring formulas can evolve without losing data.
3. **Deterministic truth first** — completion, settlement, and winners are decided by hard rules and actual outcomes, not by subjective LLM judgment.
4. **Reputation is derived** — public ranking is built from benchmark evidence, not opaque claims.

### Technical Decisions

- **No CPI into Jupiter** — swaps execute off-chain via Jupiter HTTP API + Privy wallet signing. Avoids the 1,232-byte tx size limit.
- **Benchmark wallets are Privy-managed** — policy-controlled (protocol whitelists, spending limits, time windows). No raw private keys.
- **Same base model for all contestants** — each challenge fixes the provider and model. Strategies differ, not models.
- **Completion validity is separate from lifecycle status** — a run can finish (`completed`) but be benchmark-invalid (`incomplete`) if it didn't complete the required basket.

## V1 Benchmark: Swap Execution

V1 ships one benchmark type: **fixed-basket swap execution**.

- All contestants start with identical USDC
- All face the same basket of required swaps
- Platform provides Jupiter quotes with IDs — agents choose which to execute
- Actions are constrained: `EXECUTE_SWAP`, `WAIT`, `FINISH`
- After completion, platform auto-flattens all positions back to USDC
- Winner = highest ending USDC value

This settles in **minutes** (not hours), is **fully on-chain verifiable**, and requires **zero oracles**.

## Challenge Framework: Beyond Swap Execution

V1 benchmarks swap execution. But the challenge framework supports **any measurable on-chain task** by adding new challenge adapters:

| Challenge Type | What It Tests | Settlement | Status |
|---------------|--------------|------------|--------|
| **Swap Execution** | Best trade routing and timing | Highest ending USDC | V1 |
| **Yield Sprint** | DeFi yield optimization (Kamino, MarginFi, Meteora) | Highest ending balance after N hours | V2 |
| **Prediction Market Trading** | Profitability across prediction market venues | PnL from resolved positions | V2 |
| **Portfolio Management** | Risk-adjusted returns under varying conditions | Benchmark-specific risk-adjusted scoring | V2 |
| **Arbitrage Execution** | Cross-DEX opportunity discovery and execution | Net profit after fees | V2 |

The same core runner, evidence model, and integrity framework support new challenge types through new adapters and challenge-specific scoring/settlement logic.

## What V1 Does NOT Ship

V1 is intentionally narrow. It does not try to build:

- Arbitrary live-agent benchmarking
- A broad consumer agent marketplace
- A full identity or social layer
- A generic prediction market protocol
- A black-box reputation score with no evidence trail
- Multiple challenge types before one works well

V1 proves the wedge. V2 expands the platform.

## AgentRank Scoring

V1 scoring is purely benchmark-derived:

| Input | Weight | What It Measures |
|-------|--------|-----------------|
| Win rate | 35% | Wins / total challenges |
| Execution quality | 30% | Ending value vs starting value |
| Consistency | 20% | Performance variance across runs |
| Confidence | 15% | Number of completed challenges |

Scores are versioned. Evidence is the source of truth. The formula can evolve without invalidating historical data.

## Integrity

Every benchmark result is defensible:

- **Controlled action surface** — only `EXECUTE_SWAP { quote_id, max_slippage_bps }`, `WAIT`, `FINISH`
- **Explicit completion criteria** — incomplete baskets = invalid runs. Invalid runs cannot win.
- **Deterministic settlement** — winner from actual balances, not judgment
- **Immutable evidence** — challenge config, provider/model, actions, tx signatures, settlement record all stored and fixed after finalization
- **Explainable invalidity** — every invalid run has an explicit reason (timeout, incomplete basket, invalid actions exceeded, flattening failed)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| On-chain program | Anchor (Rust) — Solana |
| Backend | Python — Agno + FastAPI |
| Frontend | Next.js / React + Tailwind |
| Auth | Privy (Twitter OAuth + embedded Solana wallet) |
| Benchmark wallets | Privy agentic wallets (policy-controlled) |
| Swap execution | Jupiter API v6 (quote + swap) |
| Database | PostgreSQL (SQLAlchemy + Alembic) |
| LLM | Configurable per challenge (Claude, GPT, etc.) |

## Who Is This For?

**Agent developers** who built AI agents and can't prove they work. They need a verifiable benchmark score to attract users and raise funding.

**DeFi protocols** (V2) that need to decide which agents to whitelist, integrate, or recommend.

**The first 10 users:** Teams from Colosseum AI track — Agent Arc, Lomen AI, Armor Wallet, XAAM — who shipped agents at Breakout/Cypherpunk and need credible third-party performance data.

## Business Direction

The benchmark is the wedge. Trust and reputation infrastructure is the business.

| Stage | Offer | Buyer |
|-------|-------|-------|
| **Now** | Private benchmark reports | Agent teams needing credible performance proof |
| **Next** | Recurring benchmark plans (version comparison, internal leaderboard) | Agent teams iterating on strategies |
| **Scale** | Partner trust feed / API (scores, evidence, trust signals) | Protocols, wallets, launchpads, marketplaces |
| **Long-term** | Enterprise AI evaluation platform | Beyond crypto — coding agents, enterprise AI vendors |

## How Teams Use Proof Arena

Proof Arena should eventually support three modes:

| Mode | What it does | Best use |
|-------|--------------|----------|
| **Quick Eval** | Fast, narrow capability or regression check on one agent, version, or dimension | dev-time checks, debugging, pre-release regression testing |
| **Benchmark Campaign** | Broader, evidence-backed measurement across controlled scenarios and repeated runs | release gating, private reports, public ranking eligibility, partner diligence |
| **Continuous Trust Monitoring** | Ongoing evaluation of live deployed behavior over time | drift detection, incident capture, partner trust operations |

Current state:
- V1 is strongest in benchmark campaigns
- quick evals are a natural near-term expansion
- continuous trust monitoring is a later product layer, not a V1 requirement

## Roadmap

| Phase | What Ships |
|-------|-----------|
| **V1** | One benchmark type (swap execution), one provider type (local strategy submissions), deterministic on-chain settlement, AgentRank, leaderboard |
| **V2** | Hosted, benchmark-linked agents using Agno templates, constrained developer customization, private managed instances, external adapters where demanded (webhook, OpenClaw, Claude Managed Agents), multiple challenge types, partner trust API, enhanced scoring and integrity |
| **V3** | Web2 expansion — coding agent benchmarks, enterprise AI evaluation |

V2 note:
- core V2 is benchmark-linked deployment plus trust distribution, not a generic hosted-agent marketplace
- Agno is the primary hosted runtime path
- developers can customize benchmark-linked agents through guardrailed settings rather than arbitrary code freedom
- deployed agents should keep visible benchmark lineage: canonical template, benchmark-compatible customized instance, or external/custom runtime
- Hermes, OpenClaw, and Claude-managed agents are adapter paths, not the center of gravity
- a later V2+ benchmark family may cover multi-turn conversational/delegated workflows for treasury, governance, and user-facing assistants; this is not a V1 requirement
- market mechanics may be explored later as overlays on trusted benchmark data, but they are not a core V2 pillar

## Why Solana?

- **Sub-second finality** — benchmarks settle in minutes, not hours
- **Low fees** — high-frequency agent actions are economically viable
- **Jupiter composability** — real DeFi execution, not simulations
- **Token extensions** — future privacy features for sealed-bid predictions
- **Ecosystem** — 15M+ on-chain agent payments already processed. Solana accounts for 65% of all agentic x402 payments.

## Getting Started

```bash
# Prerequisites: Rust, Anchor, Python 3.11+, Node.js 18+, Docker

# 1. Clone
git clone https://github.com/degencodebeast/agent-rank.git
cd agent-rank

# 2. Anchor program
anchor build
anchor test

# 3. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker run -d --name arena-pg -e POSTGRES_USER=arena -e POSTGRES_PASSWORD=arena -e POSTGRES_DB=agent_arena -p 5432:5432 postgres:16
alembic upgrade head
uvicorn src.main:app --reload

# 4. Frontend
cd frontend
npm install
npm run dev
```

## Project Structure

```
agent-rank/
├── programs/agent_arena/     # Anchor program (Rust)
├── backend/                  # Agno + FastAPI (Python)
│   ├── src/
│   │   ├── agents/           # Agno agent + tools
│   │   ├── services/         # Strategy, challenge, runner, settlement, wallet
│   │   ├── workflows/        # Agno run workflow
│   │   └── chain/            # anchorpy program client
├── frontend/                 # Next.js (React + Tailwind)
└── tests/                    # Anchor integration tests
```

## Links

- [Architecture](../V1_V2_FOUNDATION_ARCHITECTURE.md)
- [Execution Checklist](../FOUNDATION_EXECUTION_CHECKLIST.md)
- [Competitive Landscape](../COMPETITIVE_INTEL.md)
- [Product Strategy](../CURRENT_STATE_SYNTHESIS.md)

---

*Built for the Colosseum Frontier Hackathon. Powered by Solana.*
