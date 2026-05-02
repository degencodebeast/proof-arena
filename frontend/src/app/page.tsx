import Link from 'next/link';

export default function Home() {
  return (
    <div className="space-y-16 py-12">
      <section className="text-center space-y-6">
        <h1 className="text-5xl font-bold tracking-tight">
          Benchmark-linked templates, deployable on devnet.
        </h1>
        <p className="text-xl text-zinc-400 max-w-2xl mx-auto">
          Proof Arena hosts canonical templates that have been benchmarked under
          controlled conditions. Deploy a benchmark-compatible hosted instance,
          customize inside a bounded policy envelope, and inspect status,
          evidence, and benchmark history. Solana devnet only. Orca Whirlpools
          devnet swaps.
        </p>
        <div className="flex gap-4 justify-center pt-4">
          <Link href="/templates" className="bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-3 rounded-lg font-medium transition">
            Browse Templates
          </Link>
          <Link href="/flagship" className="border border-zinc-700 hover:border-zinc-500 text-zinc-300 px-6 py-3 rounded-lg font-medium transition">
            View Flagship
          </Link>
        </div>
      </section>

      <section className="grid md:grid-cols-3 gap-8">
        {[
          {
            step: '01 — Choose',
            title: 'Pick a Benchmarked Template',
            desc: 'Browse canonical templates that have passed the benchmark contract. Lineage and trust label are surfaced upfront — score belongs to the exact template/version, not transitively to instances.',
          },
          {
            step: '02 — Deploy',
            title: 'Deploy a Hosted Instance',
            desc: 'Customize inside a five-field policy envelope: slippage, position size, allowed tokens, runtime seconds, max iterations. Hosted instance for assurance workflows. Devnet-only execution.',
          },
          {
            step: '03 — Inspect',
            title: 'Status, Evidence, History',
            desc: 'Inspect the deployed instance: saga state, trust label, run history, and per-run evidence chain. Each instance earns its own benchmark score — templates do not lend reputation to deployments.',
          },
        ].map(({ step, title, desc }) => (
          <div key={step} className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-3">
            <div className="text-emerald-400 text-sm font-mono">{step}</div>
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="text-zinc-400 text-sm">{desc}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
