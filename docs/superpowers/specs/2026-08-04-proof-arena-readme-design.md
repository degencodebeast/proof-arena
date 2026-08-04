# Proof Arena README Rewrite Design

## Objective

Rewrite the root README so it introduces Proof Arena as a real product. The README must explain who it serves, what problem it solves, what works now, and how each important claim can be checked.

The README must also show the quality of the engineering work. Product value comes first. Code, tests, and setup details provide proof after the reader understands the product.

## Audience

The README serves these readers in this order:

1. Potential users and partners.
2. Product and hackathon reviewers.
3. Hiring reviewers.
4. Developers who want to run the project.

The first screen must explain the product without requiring knowledge of the codebase.

## Product Position

Proof Arena verifies completed hosted Solana agent runs. It applies fixed checks and returns a read-only JSON proof document that another person or system can inspect.

Proof Arena is not a sports-trading competition. It can verify different types of Solana agent runs. The current checks cover wallet safety and portfolio rebalancing.

Veridex and Proof Arena are separate products. Veridex builds, runs, and compares sports-trading agents. Proof Arena checks individual Solana agent runs and returns inspectable evidence.

The README must not claim that Veridex uses Proof Arena unless a real code integration exists.

## Terms to Define

The README must define each domain term when it first appears.

- **Agent:** Software that selects actions and can call tools or services.
- **Run:** One recorded execution of an agent.
- **Hosted run:** A run executed by the Proof Arena runtime instead of an outside runtime.
- **Policy:** Fixed rules that state what an agent may and may not do.
- **Policy envelope:** The stored set of run limits, such as allowed tokens, slippage, position size, iteration count, and run time.
- **Cat:** A named group of fixed checks for one risk area. Cat is short for Category.
- **Wallet Safety Cat:** A Cat that maps a saved wallet failure reason to a related check result.
- **Rebalance Policy Cat:** A Cat that recalculates ten portfolio-rebalance rules from the deployed configuration and saved evidence.
- **Public Verifier:** A read-only API that combines run details, origin, evidence details, event totals, and Cat results.
- **Evidence:** Saved records used to support a result, such as hashes, event totals, transaction signatures, and verification files.
- **Deterministic:** The same stored input and code version produce the same result.
- **Trust label:** A stored label that controls who may read the proof document.
- **Devnet:** Solana's test network. It does not use real mainnet assets.

## README Structure

### 1. Product introduction

State what Proof Arena is in one direct sentence. Add a short product statement and links to the quickest working proof.

### 2. The problem

Explain why agent claims are not enough. A user or partner needs saved evidence and checks that the agent cannot change after the run.

### 3. Who it is for

List agent developers, protocols, product teams, reviewers, and systems that need to inspect a completed run before they trust it.

### 4. What users can do

Explain the complete product flow: deploy an agent, run it under a policy, record evidence, apply Cats, and fetch the proof document.

### 5. How it works

Show the deploy, run, check, and prove sequence. Keep the diagram and explanation short.

### 6. What works now

Describe Wallet Safety, Rebalance Policy, the Public Verifier, the policy engine, action checks, the backend, the database, Docker, and the web interface.

Separate current behavior from planned work.

### 7. Proof document example

Show a small JSON response. Explain the run, origin, evidence, and Cats sections in plain English.

### 8. Product position

Explain how Proof Arena differs from model monitoring, identity systems, agent competitions, and general verification tools.

Keep named competitor claims short. Verify every current claim with a public source. Move long market research out of the root README.

### 9. Proof that it works

Map each important claim to an API route, test file, or command. Include the 56-test Wallet Safety and verifier set and the selected 29-test Rebalance Policy set.

### 10. Architecture

Show the runtime, policy checks, Cats, verifier, PostgreSQL database, and Next.js interface. Explain each part after the diagram.

### 11. Run it locally

Give three paths: quick tests without Docker, the Docker and PostgreSQL path, and the optional frontend path.

### 12. Security rules

State that the active hosted path is devnet-only, invalid actions are not executed, the verifier cannot write to the database, and public response fields are listed by hand.

State that model libraries are not imported into the Cat or verifier path. Do not claim that the complete product has no model libraries.

### 13. Honest limits

State that Proof Arena has no mainnet custody, no on-chain proof storage, no public marketplace, and no cross-runtime certification.

One successful run does not prove that all future runs will be safe.

### 14. Business direction

Keep a short product direction section. Explain possible users, integration paths, and paid product forms without presenting planned work as shipped work.

### 15. Technology and project structure

List the main tools and folders. Keep historical V1 code separate from the active V2 and V2.1 product path.

### 16. Detailed documents

Link to deeper technical and product documents when they exist. The root README remains the complete product tour, not the full internal specification.

## Writing Rules

Use ASD-STE100 Simplified Technical English.

- Use short, direct sentences and common words.
- Define a required technical term at first use.
- Keep each paragraph at 240 characters or fewer where practical.
- Do not use hype, vague claims, or unnecessary metaphors.
- Do not use “trust path” without explaining the exact code boundary.
- Do not use “lineage” when “instance and template origin” is clearer.
- Do not say private fields are removed. Say tests prove that private fields are absent.
- Do not say evidence is stored on-chain.
- Do not say Wallet Safety recalculates all ten checks from raw events.

## Current Facts to Preserve

- Proof Arena verifies completed hosted Solana agent runs.
- Wallet Safety has ten check IDs and five saved wallet failure reasons.
- Rebalance Policy recalculates ten rules for `rebalance_executor_v1` runs.
- The Public Verifier always includes Wallet Safety and includes Rebalance Policy for supported runs.
- The verifier is read-only.
- Public response fields are listed by hand.
- The runner does not execute invalid actions.
- The wallet policy denies actions unless a rule allows them.
- The active hosted path uses Solana devnet.
- The selected Wallet Safety and verifier test set passes 56 tests.
- The selected Rebalance Policy test set passes 29 tests.

## Outdated Content to Correct

- Replace “one shipped Cat” with the two current Cats.
- Replace “two endpoints” with the three current read-only routes.
- Replace `agent-rank/backend/` setup paths with `proof-arena/backend/` or `backend/`.
- Repair the shipped-artifacts table so every row has the same columns.
- Remove statements that imply on-chain proof storage.
- Replace broad “no model” claims with the exact Cat and verifier boundary.
- Remove repeated copies of the same product and safety claims.

## Verification

Before the rewrite is complete:

1. Check every API route against the backend route files.
2. Run the focused Wallet Safety and verifier tests.
3. Run the focused Rebalance Policy tests.
4. Check every setup command from the stated directory.
5. Check all local README links.
6. Search for the outdated Agent Rank path and old one-Cat statements.
7. Confirm that current product claims and limits do not conflict.

## Non-Goals

This rewrite does not change program behavior, API contracts, database tables, Solana program names, deployed instructions, or compatibility names.

It does not rename behavior-sensitive `AgentRank` symbols. It does not add product features that are not present in the code.
