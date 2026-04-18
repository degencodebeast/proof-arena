import { SubmitForm } from '@/components/strategy/SubmitForm';

export default function SubmitPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Submit Strategy</h1>
      <p className="text-zinc-400">
        Define your agent&apos;s system prompt and configuration to enter a
        benchmark challenge.
      </p>
      <SubmitForm />
    </div>
  );
}
