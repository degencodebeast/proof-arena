import type { RunEventSummary } from '@/lib/types';

const EVENT_STYLES: Record<string, string> = {
  observe: 'text-blue-400',
  decide: 'text-purple-400',
  validate: 'text-yellow-400',
  execute: 'text-emerald-400',
  error: 'text-red-400',
  finish: 'text-zinc-300',
  flatten: 'text-orange-400',
  budget_exceeded: 'text-red-400',
  finalize: 'text-cyan-400',
  onchain_finalize: 'text-cyan-300',
};

export function LiveRunView({
  events,
  isError = false,
  isLoading = false,
}: {
  events?: RunEventSummary[];
  isError?: boolean;
  isLoading?: boolean;
}) {
  if (isError) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
        <h3 className="text-lg font-semibold mb-4">Live Actions</h3>
        <p data-testid="events-error" className="text-red-400 text-sm">
          Failed to load events.
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
        <h3 className="text-lg font-semibold mb-4">Live Actions</h3>
        <p data-testid="events-loading" className="text-zinc-500 text-sm">
          Loading events...
        </p>
      </div>
    );
  }

  if (!events || events.length === 0) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
        <h3 className="text-lg font-semibold mb-4">Live Actions</h3>
        <p data-testid="empty-events" className="text-zinc-500 text-sm">
          No events yet.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
      <h3 className="text-lg font-semibold mb-4">Live Actions</h3>
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {events.map((event) => (
          <div key={event.event_id} className="flex items-start gap-3 text-sm">
            <span className="text-zinc-500 font-mono text-xs w-20 shrink-0">
              {new Date(event.timestamp).toLocaleTimeString()}
            </span>
            <span
              data-testid={`event-type-${event.event_id}`}
              className={`font-mono text-xs ${EVENT_STYLES[event.event_type] ?? 'text-zinc-400'}`}
            >
              {event.event_type}
            </span>
            {event.tx_signature && (
              <a
                href={`https://explorer.solana.com/tx/${event.tx_signature}?cluster=devnet`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-emerald-400 hover:underline text-xs ml-auto"
              >
                View TX
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
