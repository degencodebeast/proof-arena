# Proof Arena README Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the root README with a complete product introduction that explains Proof Arena, defines its project-specific terms, proves its claims, and gives a working local path.

**Architecture:** The README follows a product-first order. It explains the user problem and product flow before it shows APIs, code, tests, setup, limits, and project files. Current behavior and planned business direction remain separate.

**Tech Stack:** Markdown, Python 3.11, FastAPI, Pydantic v2, SQLAlchemy, PostgreSQL, Docker Compose, Next.js, TypeScript, Solana, Anchor, pytest.

## Global Constraints

- Use ASD-STE100 Simplified Technical English.
- Use short, direct sentences and common words.
- Define only Proof Arena-specific or unclear terms.
- Do not explain common terms such as agent, API, database, backend, or frontend.
- Do not mention or compare Proof Arena with a separate product.
- Do not claim on-chain proof storage, mainnet custody, a public marketplace, or cross-runtime certification.
- Scope the no-model-library claim to `backend/src/integrity/cats/`, `backend/src/integrity/verifier/`, and their API route files.
- Keep current product behavior separate from future business direction.
- Do not change code, API contracts, database tables, Solana instructions, or compatibility names.

---

### Task 1: Replace the README with the approved product story

**Files:**
- Modify: `README.md`
- Reference: `docs/superpowers/specs/2026-08-04-proof-arena-readme-design.md`
- Reference: `backend/src/integrity/cats/wallet_safety.py`
- Reference: `backend/src/integrity/cats/rebalance_policy.py`
- Reference: `backend/src/integrity/verifier/builder.py`
- Reference: `backend/src/integrity/verifier/schemas.py`
- Reference: `backend/src/policy/engine.py`
- Reference: `backend/src/services/runner_service.py`

**Interfaces:**
- Consumes: The current route paths, check IDs, evidence fields, policy rules, test commands, and product limits.
- Produces: A root README that is the complete product tour for users, partners, reviewers, and developers.

- [ ] **Step 1: Record the required section order**

Use this exact order:

```markdown
# Proof Arena
## The problem
## Who Proof Arena is for
## What you can do
## How it works
## Proof Arena terms
## What works now
## Example proof document
## How Proof Arena is different
## Proof that it works
## Architecture
## Run Proof Arena locally
## API routes
## Security rules
## Honest limits
## Business direction
## Technology
## Project structure
## Detailed documents
## License
```

- [ ] **Step 2: Write the opening product statement**

The opening must state these facts without hype:

```markdown
Proof Arena verifies completed hosted Solana agent runs. It applies fixed checks and returns one read-only JSON proof document that another person or system can inspect.
```

The opening must link to the quick test path, the current API routes, the architecture section, and the honest limits section.

- [ ] **Step 3: Define only the required project terms**

Use these meanings:

```markdown
- Run: one recorded execution of an agent.
- Hosted run: a run executed by the Proof Arena runtime.
- Policy envelope: stored limits for allowed tokens, slippage, position size, iterations, and run time.
- Cat: a named group of fixed checks for one risk area. Cat is short for Category.
- Public Verifier: the read-only API that combines run details, instance and template origin, evidence details, event totals, and Cat results.
- Deterministic: the same stored input and code version produce the same result.
- Trust label: a stored label that controls who may read a proof document.
```

Do not define agent, API, backend, frontend, or database.

- [ ] **Step 4: Describe the current product flow**

Use four stages:

```text
DEPLOY -> RUN -> CHECK -> PROVE
```

State that deployment stores the instance, template origin, trust label, and policy envelope. State that the runner records events and evidence. State that Cats check the completed run. State that the verifier returns one proof document.

- [ ] **Step 5: Describe the two Cats accurately**

State these differences:

```markdown
- Wallet Safety has ten check IDs. It maps one of five saved wallet failure reasons to the related failed check. It does not recalculate all ten rules from raw events.
- Rebalance Policy recalculates ten portfolio rules from the deployed configuration and saved evidence for `rebalance_executor_v1` runs.
```

List the ten Rebalance Policy check IDs from `backend/src/integrity/cats/rebalance_policy.py`.

- [ ] **Step 6: Add the Public Verifier example**

Use a small JSON response with these exact top-level keys:

```json
{
  "verifier_version": "v0",
  "run": {},
  "lineage": {},
  "evidence": {},
  "cats": {
    "wallet_safety": {},
    "rebalance_policy": null
  }
}
```

In the text, call `lineage` the instance and template origin. Explain that Rebalance Policy is `null` for unsupported run types.

- [ ] **Step 7: Keep a short product-position section**

Compare product categories before named products:

```markdown
| Product type | Main question | Difference from Proof Arena |
| --- | --- | --- |
| Model monitoring | What happened in model calls? | Proof Arena checks a completed Solana run against fixed policy and evidence rules. |
| Agent identity or reputation | Who is this agent? | Proof Arena checks what happened in one recorded run. |
| Agent competition | Which agent performed best? | Proof Arena can verify a run without a public competition or leaderboard. |
```

Keep only two sourced examples in a short note:

- Respan documents model tracing, evaluations, prompts, and gateway routing at `https://www.respan.ai/docs/documentation/overview`.
- Recall documents agent competitions, paper trading, and leaderboards at `https://docs.recall.network/reference/competitions`.

Do not repeat unverified funding, team-size, trust-score, or chain claims.

- [ ] **Step 8: Add current limits and business direction**

The limits must state:

```markdown
- Hosted execution is devnet-only.
- Proof Arena does not provide mainnet custody.
- It does not store the proof document on-chain.
- It does not provide a public marketplace or cross-runtime certification.
- One successful run does not prove that future runs will be safe.
```

The business section can describe proof feeds, partner API access, repeated-run reports, and policy packs as future directions. Label all of them as future directions.

- [ ] **Step 9: Add setup, architecture, technology, and project structure**

Use `backend/` for backend commands. Do not use `agent-rank/backend/`.

The architecture diagram must include the web interface, FastAPI routes, runtime, policy engine, Cats, Public Verifier, PostgreSQL, and Solana devnet.

Describe the V1 Anchor program as foundation code, not the active proof-storage path.

- [ ] **Step 10: Commit the rewrite**

```bash
git add README.md docs/superpowers/plans/2026-08-04-proof-arena-readme-rewrite.md
git commit -m "docs: rewrite Proof Arena product README"
```

Expected: one documentation commit containing the plan and README rewrite.

---

### Task 2: Prove every current product claim

**Files:**
- Modify if needed: `README.md`
- Test: `backend/tests/integration/test_wallet_safety_cat.py`
- Test: `backend/tests/integration/test_verifier_v0.py`
- Test: `backend/tests/test_task_a6_failure_taxonomy.py`
- Test: `backend/tests/integration/test_rebalance_policy_cat.py`
- Test: `backend/tests/integration/test_rebalance_policy_cat_route.py`
- Test: `backend/tests/integration/test_verifier_with_rebalance_cat.py`
- Test: `backend/tests/test_rebalance_cat_no_llm_imports.py`

**Interfaces:**
- Consumes: The rewritten claims and commands in `README.md`.
- Produces: Verified test counts and setup commands with no outdated paths.

- [ ] **Step 1: Run the Wallet Safety and Public Verifier set**

Run from `backend/`:

```bash
uv run pytest tests/integration/test_wallet_safety_cat.py tests/integration/test_verifier_v0.py tests/test_task_a6_failure_taxonomy.py -q
```

Expected: `56 passed`.

- [ ] **Step 2: Run the selected Rebalance Policy set**

Run from `backend/`:

```bash
uv run pytest tests/integration/test_rebalance_policy_cat.py tests/integration/test_rebalance_policy_cat_route.py tests/integration/test_verifier_with_rebalance_cat.py tests/test_rebalance_cat_no_llm_imports.py -q
```

Expected: `29 passed`.

- [ ] **Step 3: Verify the three proof routes**

Run from the repository root:

```bash
rg -n '@router.get' backend/src/api/cats.py backend/src/api/verifier.py
```

Expected route suffixes:

```text
/wallet_safety/{run_id}
/rebalance_policy/{run_id}
/runs/{run_id}
```

The shared router prefix is `/api/v1`. The local route prefixes are `/cats` and `/verifier`.

- [ ] **Step 4: Check outdated claims and paths**

Run:

```bash
rg -n 'one shipped Cat|today only Wallet Safety|two endpoints|agent-rank/backend|evidence is onchain|on-chain proof' README.md
```

Expected: no outdated product claim. The phrase `on-chain proof` can appear only in a clear non-claim.

- [ ] **Step 5: Commit any factual corrections**

If Task 2 changes the README:

```bash
git add README.md
git commit -m "docs: correct verified Proof Arena claims"
```

If no change is required, do not create an empty commit.

---

### Task 3: Check language, links, and Markdown structure

**Files:**
- Modify if needed: `README.md`

**Interfaces:**
- Consumes: The verified README from Tasks 1 and 2.
- Produces: The final readable README with working local links and no repeated claims.

- [ ] **Step 1: Check required headings**

Run:

```bash
rg -n '^## ' README.md
```

Expected: all 19 headings from Task 1 appear once and in the approved order.

- [ ] **Step 2: Check local Markdown links**

Read each relative path in `README.md` and confirm that the target exists. Check source links, test links, setup files, the design, and the implementation plan.

- [ ] **Step 3: Check repeated claims**

Search for repeated paragraphs about read-only behavior, database writes, model-library boundaries, devnet, and fixed checks. Keep the main claim in one section and use links from later sections.

- [ ] **Step 4: Check Simplified Technical English**

Replace vague terms such as `trust surface`, `trust feed`, `wedge`, `primitive`, `temporal posture`, `load-bearing`, `zero marketing`, and `structural contradiction`.

Keep required code names unchanged. Define Cat, policy envelope, Public Verifier, deterministic, trust label, hosted run, and run once.

- [ ] **Step 5: Check Markdown whitespace**

Run:

```bash
git diff --check -- README.md
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit final wording corrections**

If Task 3 changes the README:

```bash
git add README.md
git commit -m "docs: tighten Proof Arena README wording"
```

If no change is required, do not create an empty commit.
