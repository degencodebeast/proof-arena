#!/usr/bin/env node
/**
 * Orca Whirlpools swap-tx builder (V2 Task 11, Option A).
 *
 * Stdin/stdout contract (see .taskmaster/docs/task11-b6-decision.md):
 * - Input: CLI flags
 *     --input-mint    <base58 mint>
 *     --output-mint   <base58 mint>  (enforced: must be the pool side
 *                                    opposite --input-mint; mismatches
 *                                    fail before tx construction and
 *                                    surface as InvalidPoolError)
 *     --amount        <u64 string>   (input amount in base units)
 *     --slippage-bps  <int string>
 *     --wallet-pubkey <base58 pubkey>
 *     --rpc-url       <https url>
 *     --pool          <base58 Whirlpool address>
 * - Output on success: one line of base64 — the unsigned serialized
 *   versioned transaction. Exit 0.
 * - Output on failure: human-readable reason on stderr. Exit non-zero.
 *   Messages mentioning "pool" / "whirlpool" / "mint" are classified by
 *   the Python caller as InvalidPoolError; all others as OrcaSwapError.
 *
 * Python caller: `OrcaSwapService.prepare_swap_tx(...)`.
 *
 * Dependencies (declared in ./package.json; run `npm install` once before
 * using the service):
 * - @orca-so/whirlpools
 * - @solana/kit
 *
 * V2 is devnet-only. The Python side's cluster guard is the primary check;
 * this script is only ever invoked when the service's cluster == "devnet".
 */

import {
  swapInstructions,
  setWhirlpoolsConfig,
  fetchWhirlpool,
} from "@orca-so/whirlpools";
import {
  createSolanaRpc,
  address,
  createNoopSigner,
  pipe,
  createTransactionMessage,
  setTransactionMessageFeePayer,
  setTransactionMessageLifetimeUsingBlockhash,
  appendTransactionMessageInstructions,
  compileTransaction,
  getBase64EncodedWireTransaction,
} from "@solana/kit";

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    const val = argv[i + 1];
    if (!key || !key.startsWith("--") || val === undefined) {
      throw new Error(`malformed CLI args near ${key ?? "<end>"}`);
    }
    out[key.slice(2)] = val;
  }
  return out;
}

const REQUIRED = [
  "input-mint",
  "output-mint",
  "amount",
  "slippage-bps",
  "wallet-pubkey",
  "rpc-url",
  "pool",
];

async function main() {
  const args = parseArgs(process.argv);
  for (const k of REQUIRED) {
    if (!args[k]) throw new Error(`missing required flag --${k}`);
  }

  const rpc = createSolanaRpc(args["rpc-url"]);
  await setWhirlpoolsConfig("solanaDevnet");

  const walletAddress = address(args["wallet-pubkey"]);
  const signer = createNoopSigner(walletAddress);
  const poolAddress = address(args["pool"]);
  const inputMint = address(args["input-mint"]);
  const outputMint = address(args["output-mint"]);
  const slippageBps = parseInt(args["slippage-bps"], 10);
  const amount = BigInt(args["amount"]);

  // Enforce the public contract: output_mint must be the Whirlpool's
  // other side. Orca SDK's swapInstructions infers direction from
  // `{ mint: inputMint }` alone, so a wrong output_mint would silently
  // succeed without this check. We fetch the pool and compare
  // (input, output) against (tokenMintA, tokenMintB) as an unordered pair.
  const pool = await fetchWhirlpool(rpc, poolAddress);
  const a = String(pool.data.tokenMintA);
  const b = String(pool.data.tokenMintB);
  const i = String(inputMint);
  const o = String(outputMint);
  const pairMatches = (i === a && o === b) || (i === b && o === a);
  if (!pairMatches) {
    throw new Error(
      `input/output mint pair (${i} -> ${o}) does not match pool ${poolAddress} ` +
        `sides (tokenMintA=${a}, tokenMintB=${b})`,
    );
  }

  const { instructions } = await swapInstructions(
    rpc,
    { inputAmount: amount, mint: inputMint },
    poolAddress,
    slippageBps,
    signer,
  );

  const { value: blockhashValue } = await rpc.getLatestBlockhash().send();

  const message = pipe(
    createTransactionMessage({ version: 0 }),
    (m) => setTransactionMessageFeePayer(walletAddress, m),
    (m) => setTransactionMessageLifetimeUsingBlockhash(blockhashValue, m),
    (m) => appendTransactionMessageInstructions(instructions, m),
  );

  const tx = compileTransaction(message);
  // Unsigned wire-format — caller (Privy enclave) signs later.
  process.stdout.write(getBase64EncodedWireTransaction(tx));
  process.stdout.write("\n");
}

main().catch((err) => {
  process.stderr.write(`${err && err.message ? err.message : String(err)}\n`);
  process.exit(1);
});
