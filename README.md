# Proof Arena

**Proof Arena is the verification and eval layer for onchain agents.**

> It turns every completed agent run into deterministic Cat verdicts and a read-only proof JSON that judges, partners, and protocols can inspect to see what the agent actually did — before trusting it.

Deterministic policy-envelope evals, verifiable evidence trails, and partner-consumable trust feeds. Generic LLM observability platforms catch issues *after* they happen in production. Proof Arena proves what an onchain agent **can do**, **is allowed to do**, and **actually did** — *before* it touches production. *Today, hosted Solana agents on devnet, with one shipped Cat (Wallet Safety) and a clear path to more.*

**Per-run verification and deterministic evals for onchain agents.**

> **Quick demo (60 seconds):** from `agent-rank/backend/` run `uv run pytest tests/integration/test_wallet_safety_cat.py tests/integration/test_verifier_v0.py tests/test_task_a6_failure_taxonomy.py -v` → expect **56 passed**. For the live HTTP path, see [What Judges Can Try Today](#what-judges-can-try-today) below — three commands, no Solana RPC required for the demo.

Which onchain AI agent can you actually trust to handle real assets? Today, nobody can answer that credibly. Proof Arena can — one read-only proof document per completed agent run, with deterministic verdicts over the run's verifiable evidence trail (recorded actions, RunEvent stream, run-log hash, transaction signatures, verification artifacts) and zero marketing in the loop.

AI agents on Solana promise yields, trades, and risk management. Their proof today is a tweet, a backtest, or a self-reported dashboard. Proof Arena replaces all of that with a single primitive: a `GET` request that returns the run's lineage, evidence, and a named trust verdict — no LLM in the trust path, no DB writes from the verifier. If the JSON says `"result": "pass"`, you can show your work.

The binding trust contract for every claim in this README is enumerated in [Trust Model & Non-Claims](#trust-model--non-claims) below.

---

## The Problem

AI agents on Solana claim to optimize DeFi yields, execute better trades, or manage risk. Their proof today?

- Marketing claims ("40% APY!")
- Gamed backtests
- Self-reported Dune dashboards
- "Trust me bro"

There is no standardized way to ask **"should I let this agent touch my wallet?"** Developers can't prove their agent is safe. Protocols can't decide which agents to whitelist. Users are flying blind.

The wedge isn't "which agent ranks #1 on a public leaderboard." It's "which agent's last N completed runs all produced inspectable, deterministic proof that nothing dangerous happened — no policy violation, no mainnet target, no envelope breach, no silent failure." That's a different question, and it's the one Proof Arena answers.

## The Solution

Proof Arena turns each completed agent run into a single **read-only JSON proof document**. Every hosted instance carries an explicit trust label and a wallet-policy envelope. Every completed run is checked deterministically by named **Cats** (short for **Categories** — each Cat is a bounded set of related deterministic checks covering one named trust dimension; today only **Wallet Safety** ships, with more Cats to follow), and the **Public Verifier** composes those Cat verdicts with run lineage, evidence hashes, and aggregate event signals into one inspectable proof endpoint.

- **No LLM in the trust path.** Static-import grep tests lock this in.
- **No DB writes from the verifier path.** Row-count delta tests lock this across all 7 mutable tables (including `rank_snapshots` for the lineage-not-inheritance discipline).
- **Devnet only.** Three independent guard layers reject mainnet RPC URLs at wallet creation, runtime assertion, and enclave policy.

The deterministic answer to "did this run stay inside its declared trust envelope?" is one `GET` request away.

## How It Works

**The trust loop:** *deploy → run → evaluate → prove.*

```
1. DEPLOY    A benchmark-linked template (e.g. swap_executor_v1) is deployed
             as a hosted instance via the V2 hosted runtime. Instance carries
             a trust_label + wallet-policy envelope.
             (Lineage, not inherited reputation.)
                 ↓
2. RUN       The instance executes a completed run on Solana devnet through
             the V2 hosted runtime path. Runs produce: a run_log_hash, a
             RunEvent stream, VerificationArtifacts, and an explicit
             completion_status that is separate from lifecycle status.
                 ↓
3. EVALUATE  Wallet Safety Cat reads the completed run and returns a
             deterministic pass/fail verdict over a bounded set of
             wallet-safety RunInvalidReason members, with static critique
             copy and per-check IDs. No LLM. No new failure-taxonomy enum.
                 ↓
4. PROOF     Public Verifier composes the Cat verdict with run lineage,
             evidence metadata, and aggregate event signals into a single
             read-only JSON document a judge, partner, or Proof Card UI
             fetches with one GET — no Cat-logic duplicated on the
             consumer side.
```

V1's controlled challenge / run / settlement loop is the foundation underneath: it proved the deterministic primitives V2.1 now productizes as a trust surface.

## What Makes This Different

The closest competitors by **what we're actually shipping** (per-run trust evidence for onchain agents) are evaluation/observability and trust-API products, not public-competition products:

- **Respan AI** (formerly Keywords AI; YC W24, $5M raise, ~10 ppl) — generic LLM observability + evals + gateway. Closest by category surface.
- **Helixa** — agent trust API; identity/reputation signals + natural-language trust assessment.
- **Recall** — closest direct narrative competitor ("AI agents compete in trading challenges and earn reputation"). Public competition-led, not eval-led.
- **AgentFolio** — Solana identity / trust score (live on mainnet). Answers "who is this agent?", not "did this run pass trust checks?"

| | **Proof Arena** | Respan AI | Helixa | Recall | AgentFolio |
|---|---|---|---|---|---|
| **Category** | Per-run trust evidence for onchain agents | LLM observability + evals + gateway | Agent trust API | Public AI competition / skill market | Solana agent identity registry |
| **Temporal posture** | **Pre-trust** — prove what's safe before trust is granted | **Post-deployment** — find what broke after launch | Continuous trust signal from identity/reputation | Public competition outcome | Identity at registration |
| **Trust base** | Deterministic checks (Hamel-style); LLM only as explanation, never as verdict | LLM judges + code checks + human review, **equal-weight evaluators** | Reputation/identity signals + LLM summarization | Competition outcome + staking | Social verification + on-chain reviews |
| **Evidence artifact** | One `GET /api/v1/verifier/runs/{run_id}` returns lineage + evidence + Cat verdict — single inspectable JSON | Spans in their backend | Trust score + confidence + recommended risk limits | Leaderboard rank + token mechanics | Trust score (0–100) + W3C VC export |
| **Domain** | **Solana-native, onchain agents, devnet-only V2** | Chain-agnostic | Chain-agnostic | Broad AI skills, multi-chain | Solana identity registration |
| **Core question** | "Did this run pass its named trust checks?" | "What broke in production?" | "Should I trust this agent based on identity/reputation signals?" | "Which agent wins the public arena?" | "Who is this agent?" |

The clean positioning lines:

- **Respan AI** watches AI behavior *after* deployment with LLM judges as equal-weight evaluators. **Proof Arena** puts deterministic checks at the trust base *before* trust is granted, and the evidence is onchain, Solana-native, and per-run inspectable.
- **Helixa** answers trust from identity / reputation / natural-language signals. **Proof Arena** answers trust from deterministic per-run evidence.
- **Recall** tells you who *wins the public arena*. **Proof Arena** tells you whether *this specific run* was trustworthy — confidential strategy, public proof.
- **AgentFolio** tells you *who an agent is*. **Proof Arena** tells you whether *a specific run can be trusted*.

Respan AI is closest by category surface but distinct in **temporal posture** (pre-trust vs post-deployment), **trust base** (deterministic checks vs LLM judges as equal-weight evaluators), and **domain** (Solana onchain vs chain-agnostic). For onchain agents that asymmetry is load-bearing — **an LLM-judge-friendly trust base isn't a tradeoff, it's a structural contradiction.** Recall and AgentFolio overlap on narrative but solve different questions ("who wins?" / "who is?"). Theoriq, DGrid, ERC-8004 ecosystem, and the broader trust-registry space are export paths or integration partners, not direct competitors.

> **Not just ranking agents. Deciding whether a completed onchain agent run is trustable.**

---

## What Judges Can Try Today

Two HTTP endpoints are shipped on `main`. Both return read-only JSON. No Solana RPC required for the demo path; no LLM in the trust path.

```bash
# Wallet Safety Cat — bounded pass/fail trust verdict over a completed hosted-instance run.
GET /api/v1/cats/wallet_safety/{run_id}

# Public Verifier V0 — single proof document with run summary, lineage, evidence, and the verbatim Cat verdict.
GET /api/v1/verifier/runs/{run_id}
```

Three ways to exercise them:

1. **Pytest path (no Docker).** From `backend/`:
   ```bash
   uv run pytest tests/integration/test_wallet_safety_cat.py tests/integration/test_verifier_v0.py tests/test_task_a6_failure_taxonomy.py -v
   ```
   Expected: **56 passed** (29 Cat + 19 Verifier + 8 failure-taxonomy regression). Uses in-memory SQLite — no infra needed.

2. **Live Docker/Postgres smoke.** Start the local stack, seed one deterministic completed run, hit both endpoints with `curl`. See [Demo / Smoke Commands](#demo--smoke-commands) below for copy-pasteable commands.

3. **Read the verifier output.** A single GET against `/api/v1/verifier/runs/{run_id}` returns the run summary, lineage (template + trust label), evidence (run log hash + verification-artifact metadata + RunEvent aggregate signals), and the embedded Wallet Safety Cat verdict — all in one JSON document a judge or partner can inspect without reimplementing any internal logic.

---

## Shipped Artifacts (V2.1.0 Trust/Eval Core)

| Artifact | Endpoint | Status | Test coverage |
|----------|---------|--------|---------------|
| **Wallet Safety Cat** — bounded pass/fail trust verdict for a completed hosted-instance run, with a named `RunInvalidReason`, static critique copy, evidence hash, and off-scope visibility fields. | `GET /api/v1/cats/wallet_safety/{run_id}` | Merged to `main` (PR #1) | 29 acceptance tests + A-6 failure-taxonomy regression |
| **Public Verifier V0** — single read-only proof document over a completed hosted-instance run. **Composes** the Cat (`compute_wallet_safety_cat` reused verbatim, no Cat-verdict logic duplicated). | `GET /api/v1/verifier/runs/{run_id}` | Merged to `main` (PR #2) | 19 acceptance tests; private-field non-leakage locked via 13 sentinel-value + 13 literal-key absence assertions |
| **V2.1 smoke seed** — deterministic Postgres seeder for a completed hosted-instance run so the live curl demo returns 200s without invoking Solana RPC, Privy, AgentOS, wallet creation, or any LLM. | `docker compose exec backend uv run python -m scripts.seed_v2_1_smoke_run` | On branch `chore/v2-1-smoke-seed` (open PR) | 1 composition test |

Auth on Cat and Verifier is keyed on `AgentInstance.trust_label`, **never** on `Agent.subject_type`:

- `benchmarked_canonical_template` → public read, no auth.
- `benchmark_compatible_customized_instance` → owner-auth required (401 anonymous, 403 wrong owner, 200 correct owner).
- `external_custom_runtime` → defensive 422 (reserved label; no V2 path produces it).

---

## Demo / Smoke Commands

```bash
# Test-mode verification (no Docker, in-memory SQLite)
cd backend
uv run pytest tests/integration/test_wallet_safety_cat.py -v        # 29 passed
uv run pytest tests/integration/test_verifier_v0.py -v              # 19 passed
uv run pytest tests/test_task_a6_failure_taxonomy.py -v             # 8 passed

# Live smoke (requires Docker for Postgres + the backend running)
docker compose up --build -d
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run python -m scripts.seed_v2_1_smoke_run    # prints seeded run_id + curl commands

# Health
curl http://localhost:8000/health

# Anonymous reads (canonical-template trust label)
curl -s "http://localhost:8000/api/v1/cats/wallet_safety/<run_id>" | jq .
curl -s "http://localhost:8000/api/v1/verifier/runs/<run_id>" | jq '{
  verifier_version,
  template: .lineage.template.template_key,
  trust_label: .lineage.trust_label,
  cat_result: .cats.wallet_safety.result,
  run_log_hash: .evidence.run_log_hash,
  artifacts: (.evidence.verification_artifacts | length),
  events: .evidence.run_event_count
}'

# Negative smoke (unknown run)
curl -i -s "http://localhost:8000/api/v1/cats/wallet_safety/999999999"     # → 404 {"error":"run_not_found"}
curl -i -s "http://localhost:8000/api/v1/verifier/runs/999999999"          # → 404 {"error":"run_not_found"}
```

---

## Architecture

The active product surface is the V2/V2.1 path. V1 is foundation infrastructure that proved the deterministic challenge/run/settlement loop and remains reusable for future directions; it is **not** the current judge-facing path.

### Active path — V2 hosted runtime + V2.1 trust surface

```
Template (e.g. swap_executor_v1)
   │  hosted-runtime deployment via AgentOS
   ▼
Hosted Instance  (carries trust_label, policy envelope, runtime handle)
   │  recurring completed runs (cron / on-demand)
   ▼
Completed Run   (run_log_hash, RunEvent stream, VerificationArtifact set)
   │
   ├─▶ Wallet Safety Cat       /api/v1/cats/wallet_safety/{run_id}
   │     deterministic pass/fail over wallet-safety RunInvalidReason
   │
   └─▶ Public Verifier V0      /api/v1/verifier/runs/{run_id}
         single proof document: run + lineage + evidence + embedded Cat
```

What this is for, in plain language:
- **V2** turns benchmark-linked templates into deployable hosted agent instances. Instances carry **benchmark lineage**, not inherited benchmark reputation — the canonical template's score does not transfer to a deployed instance, by design.
- **V2.1** makes every completed run inspectable on its own merits: a Cat verdict for one named trust dimension, plus a Verifier document that any judge, partner, or Proof Card UI can fetch without reimplementing internal logic.

### Backend layout

```
agent-rank/
├── backend/
│   ├── src/
│   │   ├── api/                  FastAPI routes (cats, verifier, templates, instances, flagship, leaderboard, …)
│   │   ├── integrity/
│   │   │   ├── cats/             Wallet Safety Cat: deterministic compute + schemas
│   │   │   ├── verifier/         Public Verifier V0: builder + Pydantic allowlist schemas
│   │   │   ├── failure_taxonomy.py    SagaFailureReason + RunInvalidReason enums (single source of truth)
│   │   │   └── …                 Action validator, completion evaluator, run auditor, settlement verifier
│   │   ├── runtime/              AgentOS hosted-runtime adapter (V2 SDK boundary)
│   │   ├── policy/               Wallet-policy engine (Privy-bound, devnet allowlist)
│   │   ├── providers/            Hosted-instance provider for V2 path
│   │   ├── services/             Instance saga, flagship cron, swap service, signing client, …
│   │   ├── db/                   SQLAlchemy models + Alembic migrations
│   │   └── main.py               FastAPI app
│   ├── tests/
│   │   ├── integration/          test_wallet_safety_cat.py, test_verifier_v0.py, test_seed_v2_1_smoke_run.py, …
│   │   └── test_task_a6_failure_taxonomy.py    A-6 enum regression
│   └── scripts/
│       └── seed_v2_1_smoke_run.py    Deterministic local Postgres seeder for the V2.1 smoke
├── programs/agent_arena/         V1 Anchor program (Rust). Foundation; not the active path.
├── frontend/                     Next.js + Privy auth (admin / template / instance / flagship surfaces)
└── docker-compose.yml            Postgres + backend + frontend (devnet defaults)
```

### V1 — foundation, not the active surface

V1 proved the controlled benchmark loop: a strategy submission, a runner that observed → decided → validated → executed → logged, and deterministic settlement on actual on-chain token balances. It still ships in the codebase (`programs/agent_arena/`, V1 leaderboard / challenges / strategies / agents API surface, AgentRank score) and remains the structural foundation for the V2/V2.1 evidence model — RunEvents, VerificationArtifacts, run_log_hash, completion-vs-lifecycle separation. V1 is **not** what a hackathon judge should evaluate the product on. It is reusable infrastructure for the V3 directions below.

---

## How Proof Arena Stays Credible

**The atomic unit is a `Run`** — a completed agent execution with a recorded action stream, transaction signatures, evidence artifacts, a `run_log_hash`, and a definite outcome. Every assurance question worth asking is a question about a Run. Proof Arena turns each Run into a deterministic Cat verdict and a single, partner-consumable Verifier document. (Compare: Respan's atomic unit is a `span` — debug latency spans, evaluate execution spans. Different unit, different decision class, different audience.)

**Under the hood, Proof Arena is an assurance harness:** hosted agent templates run inside policy-controlled wallets, emit verifiable evidence, and are evaluated by deterministic Cats before any trust claim is made. The verification + eval layer above is what consumers see; the assurance harness is the engineering shape that produces it.

Five rules that define the product:

1. **Per-run proof first** — every completed hosted-instance run produces a single inspectable JSON document at `/api/v1/verifier/runs/{run_id}`. Trust starts there, not at a leaderboard rank.
2. **Deterministic verdicts only in the trust path** — Cats compute pass/fail over a bounded set of named `RunInvalidReason` members with static critique copy and per-check IDs. No LLM judgment in the verdict, no scoring-formula opacity, no human-rated review at the trust base. (Hamel-style discipline: LLM judges are layered above only as explanation, never as the verdict source.)
3. **Evidence first** — `run_log_hash`, `RunEvent` stream, `VerificationArtifact` metadata, and the run's lineage are stored before any verdict is computed. Verdicts are recomputable from evidence, so scoring formulas and Cat composition can evolve without losing data.
4. **Lineage, not inheritance** — a deployed customized instance carries the lineage of its template (which template, which version, which trust label) but does NOT inherit the canonical template's benchmark score. Trust is per run, not per ancestry.
5. **No silent state mutation** — Cat and Verifier are read-only. Static guards lock no DB writes (row-count delta tests across all 7 mutable tables, including `rank_snapshots`) and no LLM imports.

### Technical Decisions

- **Verifier composes the Cat, never duplicates it** — `compute_wallet_safety_cat` and `resolve_run_and_instance` are reused verbatim by `backend/src/integrity/verifier/builder.py`. A grep audit locks zero Cat-internal symbols (`WALLET_SAFETY_REASONS`, `_REASON_TO_CHECK`, `_CHECK_IDS`, `_critique_for`, `FAILURE_COPY_MAP`) re-imported in the verifier modules.
- **Auth keyed on `AgentInstance.trust_label`, never on `Agent.subject_type`** — locked by an asymmetric test pair: `customized_instance` trust + `canonical_template` subject_type → 401; `canonical_template` trust + `customized_instance` subject_type → 200. `subject_type` is lineage metadata only.
- **Devnet-only execution** — three independent guard layers (wallet creation chain ID, runtime assertion, enclave policy allowlist) reject mainnet RPC URLs. V2 hosted-instance Anchor instructions are dormant: `instance.onchain_address` stays `None`; settlement partitions out hosted-instance runs.
- **Privy agentic wallets, deny-by-default policy** — wallet creation binds a deny-by-default policy with a six-program allowlist (Whirlpools v2, SPL Token, ATA, System, Memo, ComputeBudget). Mutation RPCs require a `privy-authorization-signature` header signed with a P-256 authorization key the platform controls; the wallet's raw key never leaves Privy's enclave.
- **Orca Whirlpools on devnet** — Jupiter has no Solana devnet deployment, so the V2 swap backend is Orca with the policy allowlist derived from a real swap footprint. (V1's Jupiter HTTP path remains in the legacy V1 codebase as foundation.)
- **Completion validity is separate from lifecycle status** — a run can finish (`status="completed"`) but be benchmark-invalid (`completion_status="invalid"`) if a wallet-safety `RunInvalidReason` fires.

---

## Trust Model & Non-Claims

What Proof Arena claims:

- The Verifier composes the Cat. Cat-verdict logic is not duplicated — `compute_wallet_safety_cat` and `resolve_run_and_instance` are imported and called verbatim. (Locked by spec test #11 and a `WALLET_SAFETY_REASONS|_REASON_TO_CHECK|_CHECK_IDS|_critique_for|FAILURE_COPY_MAP` grep audit on the verifier modules.)
- No LLM in the trust path. (Locked by a static-import grep test on `backend/src/integrity/verifier/` and `backend/src/api/verifier.py`.)
- No DB writes in the verifier path. (Locked by a row-count delta test across all 7 mutable tables, including `rank_snapshots`.)
- Auth keyed on `AgentInstance.trust_label`, never on `Agent.subject_type`. (Locked by an asymmetric pair: customized trust + canonical subject_type → 401; canonical trust + customized subject_type → 200.)
- Private fields never appear in `resp.text`: 13 sentinel **values** + 13 literal field-name **substrings** are asserted absent (`runtime_handle_json`, `effective_config_json`, `system_prompt`, `wallet_address`, `hosted_wallet_ref`, `uri_or_ref`, `state_snapshot_json`, `*_payload_json`, `quote_snapshot_ref`, `last_failure_reason`, etc.).

What Proof Arena does **not** claim:

- **No mainnet custody.** The V2 hosted runtime targets Solana **devnet** only; mainnet RPC URLs are rejected at three independent guard layers (wallet creation, runtime assertion, enclave policy).
- **No instance score inheritance.** A deployed customized instance does **not** inherit the canonical template's benchmark score. Benchmark lineage (which template, which version) is preserved in the response; reputation is not transferred.
- **No new failure-taxonomy enum members.** `RunInvalidReason` membership is locked by a baseline-pin test; V2.1 reuses the existing 11 members (6 V1 + 5 V2 hosted-path) and does not add a Cat- or Verifier-owned enum.
- **No marketplace, no consumer agent ranking, no cross-runtime certification.** Those are explicit non-goals at this stage.

---

## How to Run Locally

### Prerequisites

- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Docker (only for the live-smoke path; not needed for pytest)
- Optional, only for V1 Anchor work: Rust + Solana CLI + Anchor

### Pytest path (no Docker)

```bash
git clone https://github.com/degencodebeast/agent-rank.git
cd agent-rank/backend
uv sync
uv run pytest tests/integration/test_wallet_safety_cat.py tests/integration/test_verifier_v0.py tests/test_task_a6_failure_taxonomy.py -v
```

Expected: **56 passed**. Integration tests use a fresh in-memory SQLite engine per test (see `tests/integration/conftest.py`), so no Postgres is required.

### Docker / Postgres live smoke

```bash
cd agent-rank
docker compose up --build -d
docker compose exec backend uv run alembic upgrade head

# Seed one deterministic completed hosted-instance run + print the curl commands
docker compose exec backend uv run python -m scripts.seed_v2_1_smoke_run

# Then hit /health, /cats/wallet_safety/{run_id}, /verifier/runs/{run_id}
```

The seed script is read-only with respect to the rest of the app: it inserts one `AgentTemplate` (idempotent), one `AgentInstance`, one bridge `Agent`, one `Challenge`, one `Run`, two `RunEvent` rows, and one `VerificationArtifact`. It uses `trust_label="benchmarked_canonical_template"` so anonymous curls return 200.

### Frontend (optional)

```bash
cd agent-rank/frontend
npm install
npm run dev
```

The frontend is **not** required to evaluate the V2.1 trust surface — both Cat and Verifier are pure HTTP endpoints.

---

## API Examples

### Wallet Safety Cat — public canonical-template run

```bash
$ curl -s "http://localhost:8000/api/v1/cats/wallet_safety/<run_id>" | jq .
{
  "run_id": 6,
  "instance_id": 4,
  "subject_type": "canonical_template",
  "trust_label": "benchmarked_canonical_template",
  "result": "pass",
  "reason": null,
  "critique": "",
  "run_completion_status": "complete",
  "off_scope_invalid_reason": null,
  "scope_note": null,
  "evidence": { "run_log_hash": "…", "primary_event_id": null, "verifier_url": null },
  "checks": [
    { "check_id": "envelope_slippage_check",         "result": "pass" },
    { "check_id": "envelope_token_universe_check",   "result": "pass" },
    /* … 8 more deterministic per-check IDs … */
  ]
}
```

### Public Verifier V0 — same run, full proof JSON

```bash
$ curl -s "http://localhost:8000/api/v1/verifier/runs/<run_id>" | jq '{verifier_version, run: .run.run_id, trust_label: .lineage.trust_label, template: .lineage.template.template_key, cat: .cats.wallet_safety.result, run_log_hash: .evidence.run_log_hash}'
{
  "verifier_version": "v0",
  "run": 6,
  "trust_label": "benchmarked_canonical_template",
  "template": "v2_1_smoke_template",
  "cat": "pass",
  "run_log_hash": "1de9…"
}
```

The full Verifier response is one JSON document with four blocks: `run` (18 public-safe Run fields), `lineage` (instance + trust_label + subject_type + nested template), `evidence` (run_log_hash + RunEvent aggregate signals + verification-artifact metadata, no payloads, no `uri_or_ref`), and `cats.wallet_safety` (verbatim Cat verdict).

### Negative smoke

```bash
$ curl -i -s "http://localhost:8000/api/v1/verifier/runs/999999999"
HTTP/1.1 404 Not Found
…
{"error":"run_not_found"}
```

### Other shipped routes (selected)

| Method | Path | What it returns |
|--------|------|-----------------|
| `GET` | `/health` | Liveness probe |
| `GET` | `/api/v1/templates` | Template catalog |
| `GET` | `/api/v1/templates/{template_key}` | Template detail (lineage, not inherited score) |
| `GET` | `/api/v1/flagship` | Recent flagship-instance runs (unfiltered, chronological) |
| `GET` | `/api/v1/instances/{instance_id}` | Private instance dashboard |
| `GET` | `/api/v1/leaderboard?subject=canonical|customized` | V1 leaderboard read model |
| `GET` | `/api/v1/failure-taxonomy` | Saga + RunInvalidReason enums + copy map |

---

## Roadmap

| Phase | Status | What it covers |
|-------|--------|----------------|
| **V1** — controlled benchmark core | foundation, not the active product surface | Strategy submission, runner (observe → decide → validate → execute → log), deterministic on-chain settlement, AgentRank score, public leaderboard. Reusable for V3 directions. |
| **V2** — hosted template runtime | shipped | Benchmark-linked templates become deployable hosted agent instances with policy envelope, trust label, runtime handle, saga lifecycle, devnet-only execution. Deployments carry **lineage, not inherited benchmark reputation**. |
| **V2.1 Trust/Eval Core** | shipped | Wallet Safety Cat + Public Verifier V0. Read-only, deterministic, no LLM, no DB writes from the trust path. |
| **V2.1 follow-ons** | next | Proof Card UI over Verifier JSON, more Cats beyond wallet safety, recurring trust summaries over the flagship 6-hour runs, TR1-narrow partner trust endpoint. |
| **V3** — multi-direction | future | Direction A: **Proof Card UI / partner trust products** as standalone surfaces. Direction B: **Agent Battles** — competitive head-to-head benchmarks reusing the V1 challenge/run/settlement primitives, with V2.1 evidence/proof attached from day one. Direction C: **richer template-linked reputation** without instance score inheritance. Direction D: **optional on-chain anchoring** of Verifier hashes if and only if it ships explicitly later (currently not claimed). Direction E: **broader trust/eval surfaces** (continuous monitoring, version-comparison reports). Marketplace and cross-runtime distribution remain explicitly downstream of mature trust boundaries. |

The throughline: **V1 proved agents can be measured. V2 made benchmark-linked templates deployable. V2.1 made completed runs inspectable and trustable per run. V3 broadens this into richer trust products and competitive experiences with proof/evidence built in from day one.**

---

## Who Is This For

| Audience | Why Proof Arena |
|---|---|
| **Agent developers** building Solana wallet-action agents | Need to prove the code stays inside its declared trust envelope before letting anyone touch it with mainnet capital. Without per-run trust evidence, the only proof is a tweet. |
| **DeFi protocols, wallets, marketplaces, launchpads** evaluating agents to whitelist, integrate, or recommend | Need to reason about per-run trust signals, not just public competition rank. A read-only `GET` returns the deterministic answer. |
| **Hackathon judges and partners** | Can fetch one JSON document over HTTP and read the answer to "did this run pass its named trust checks?" without re-implementing internal logic. No SDK install, no auth dance for canonical-template runs. |
| **The first wave of Solana agent teams** (Agent Arc, Lomen AI, Armor Wallet, XAAM, etc.) who shipped at Breakout / Cypherpunk | Need credible third-party trust evidence to attract users, raise, and integrate with serious capital — not another self-reported dashboard. |

## Business Direction

The wedge is **per-run trust evidence**. The business is **trust and reputation infrastructure for onchain agents.**

| Stage | Offer | Buyer |
|-------|-------|-------|
| **Now** (V2.1, shipped) | Wallet Safety Cat + Public Verifier V0. Per-run trust verdicts. Private benchmark reports. | Agent teams needing credible third-party trust evidence before public launch. |
| **Next** (V2.1 follow-ons) | Recurring trust summaries over flagship 6-hour runs. Proof Card UI over Verifier JSON. More named Cats (settlement correctness, evidence completeness, policy compliance). | Agent teams iterating on strategies; DeFi protocols evaluating partners. |
| **Scale** (V3 trust feed) | Partner trust feed / API (TR1-narrow). Cross-runtime trust adapters under the same evidence contract. Optional on-chain anchoring of Verifier hashes if and only if it ships explicitly. | Protocols, wallets, launchpads, marketplaces consuming trust signals at integration time. |
| **Long-term** | Enterprise AI evaluation infrastructure beyond crypto — coding agents, agentic workflows, model gateways — under the same deterministic-checks-as-trust-base discipline. | Enterprise AI vendors needing audit-grade evaluation evidence. |

The temporal posture is the moat: **pre-trust, deterministic-checks-first, onchain, Solana-native.** Generic LLM observability (Respan AI) and agent identity registries (AgentFolio) are adjacent surfaces, not the same product.

---

## Why Solana

- Sub-second finality — benchmarks settle in minutes, not hours.
- Low fees — high-frequency agent actions are economically viable.
- Devnet maturity — full Anchor + Privy + Jupiter/Orca composability without mainnet risk during V2 hardening.
- The agentic-payment cohort is already on Solana (x402 Solana implementations like ag402, MoltsPay, x402-rs are live; Privy agentic-wallet posture is mature; Cypherpunk/Breakout shipped a wave of onchain agent teams) — the agents that need a verification layer first are already here.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, pytest + httpx ASGITransport, uv |
| Database | PostgreSQL 16 (live smoke), SQLite in-memory (test fixtures) |
| Hosted runtime | AgentOS (V2 SDK), import boundary enforced inside `backend/src/runtime/` |
| Wallet / signing | Privy agentic wallets, P-256 authorization keys, JCS-canonicalized signing |
| Swap execution (V2 hosted path) | Orca Whirlpools on Solana devnet (Jupiter deferred — no Solana devnet deployment) |
| On-chain (V1 foundation) | Anchor (Rust) on Solana devnet — `programs/agent_arena/` |
| Frontend | Next.js + React + Tailwind, Privy auth |

---

## What Proof Arena Is Not (Out of Scope)

- Not a generic LLM eval harness — the Cat is one bounded trust dimension, not a free-form judge.
- Not a custody product — Privy holds keys; Proof Arena holds an authorization key bound to a deny-by-default policy.
- Not a mainnet trading agent — devnet only at this stage.
- Not a marketplace — distribution comes after trust matures.
- Not a centralized scoring oracle — Cat verdicts and Verifier documents are deterministic compositions over already-stored run evidence; the formula is auditable, not authoritative-by-claim.

---

## FAQ

**Why not just use Respan / LangSmith / Braintrust?**
Generic LLM observability and eval platforms are post-deployment and LLM-judge-friendly. They help you find what broke after traffic flowed. Onchain agents need a different posture: pre-trust deterministic verdicts before the agent gets more authority. Different temporal slot, different trust base, different domain. Generic eval platforms catch issues *after* — Proof Arena catches them *before*.

**Why not just trust the public leaderboard / agent competitions?**
A leaderboard tells you who wins on average. The Verifier tells you whether *this specific run* should have been allowed to touch a wallet. Per-run trust ≠ aggregate rank. A protocol whitelisting an agent for capital integration cares about the run-level signal, not the seasonal champion.

**Why is this on Solana specifically?**
Three reasons. (1) Devnet maturity — full Anchor + Privy + Orca composability without mainnet risk during V2 hardening. (2) The Privy agentic-wallet posture (P-256 authorization keys, deny-by-default policy, raw key in enclave) gives Proof Arena a programmable trust boundary that other chains' agent stacks don't have yet. (3) The agentic-payment cohort that needs trust evidence first is already on Solana — x402 implementations, the Cypherpunk / Breakout agent teams, and the agent-on-Solana wave more broadly.

**Why not just build this in-house?**
Strong teams often start there. The hardest part isn't writing the endpoint — it's locking the trust base (deterministic-checks-only, no LLM in the verdict path), the evidence model (`RunEvent` chain + `run_log_hash` + `VerificationArtifact` rows), and the auth contract (`AgentInstance.trust_label`, never `Agent.subject_type`). Each of those took multiple review cycles to get right; reproducing them is months of work, and the result is the same shape Proof Arena already ships.

**What's actually shipped today?**
56 acceptance tests passing on `main`: 29 Wallet Safety Cat tests, 19 Public Verifier tests, 8 A-6 failure-taxonomy regression tests. Both endpoints are live and read-only. The V2.1 smoke seed script lets you produce a deterministic completed run for live curl smoke without invoking any Solana RPC, Privy, AgentOS, or LLM path.

---

## Project Structure

```
agent-rank/
├── backend/                      Python / FastAPI (the V2.1 trust surface lives here)
│   ├── src/api/                  cats.py, verifier.py, templates.py, instances.py, flagship.py, …
│   ├── src/integrity/            cats/, verifier/, failure_taxonomy.py, action_validator.py, …
│   ├── src/runtime/              AgentOS adapter (only in-tree SDK import boundary)
│   ├── src/policy/               Wallet-policy engine
│   ├── src/services/             Instance saga, flagship cron, swap service, Privy signing client
│   ├── src/db/                   SQLAlchemy models + Alembic migrations
│   ├── tests/                    Unit + integration; spec-acceptance tests for Cat (29) and Verifier (19)
│   └── scripts/                  seed_v2_1_smoke_run.py, flagship_cron.py, agentos_dry_run/, …
├── programs/agent_arena/         V1 Anchor program (Rust) — foundation
├── frontend/                     Next.js + Privy
├── agentos_app/                  AgentOS-side template registration (V2 hosted runtime)
└── docker-compose.yml            Postgres + backend + frontend, devnet defaults
```
