import { StrategyBuilderLite } from '@/components/strategy/StrategyBuilderLite';

export default function BuilderPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Strategy Builder Lite</h1>
      <p className="text-zinc-400">
        Pick a strategy template, customize parameters, and submit — no coding
        required.
      </p>
      <p className="text-zinc-600 text-xs">
        All templates submit through the same{' '}
        <code className="text-zinc-400">/api/v1/strategies</code> endpoint. This
        is NOT a hosted agent product — it generates prompt/config only.
      </p>
      <StrategyBuilderLite />
    </div>
  );
}
