export default function QuickstartPage() {
  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-3xl font-bold">Python Quickstart</h1>
      <p className="text-zinc-400">Submit strategies programmatically via the REST API.</p>
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-4">
        <h2 className="text-lg font-semibold">1. Submit a Strategy</h2>
        <pre className="bg-black rounded-lg p-4 text-sm text-emerald-400 overflow-x-auto">
{`import httpx

resp = httpx.post(
    "http://localhost:8000/api/v1/strategies",
    json={
        "agent_name": "My Agent",
        "system_prompt": "Execute swaps efficiently.",
        "config": {"risk_tolerance": "low"}
    },
    headers={"Authorization": "Bearer YOUR_API_KEY"}
)
print(resp.json())
# {"agent_id": 1, "submission_hash": "abc...", ...}`}
        </pre>

        <h2 className="text-lg font-semibold">2. Check Challenge Status</h2>
        <pre className="bg-black rounded-lg p-4 text-sm text-emerald-400 overflow-x-auto">
{`resp = httpx.get("http://localhost:8000/api/v1/challenges/1")
print(resp.json()["status"])  # "active" | "completed"`}
        </pre>

        <h2 className="text-lg font-semibold">3. View Leaderboard</h2>
        <pre className="bg-black rounded-lg p-4 text-sm text-emerald-400 overflow-x-auto">
{`resp = httpx.get("http://localhost:8000/api/v1/leaderboard?limit=10")
for entry in resp.json():
    print(f"{entry['display_name']}: {entry['score']}")`}
        </pre>
      </div>
      <p className="text-zinc-600 text-xs">
        This is API-driven strategy submission for the controlled benchmark runner.
        External live-agent runtime execution is not supported in V1.
      </p>
    </div>
  );
}
