import { describe, it, expect } from 'vitest';

describe('Task 12: Frontend Setup', () => {
  describe('API Client', () => {
    it('exports agentArenaApi with all required methods', async () => {
      const { agentArenaApi } = await import('@/lib/api');
      expect(agentArenaApi.getLeaderboard).toBeDefined();
      expect(agentArenaApi.getAgent).toBeDefined();
      expect(agentArenaApi.getChallenges).toBeDefined();
      expect(agentArenaApi.getChallenge).toBeDefined();
      expect(agentArenaApi.getChallengeEvents).toBeDefined();
      expect(agentArenaApi.submitStrategy).toBeDefined();
    });

    it('uses NEXT_PUBLIC_API_URL as base', async () => {
      const { default: api } = await import('@/lib/api');
      expect(api.defaults.baseURL).toContain('/api/v1');
    });
  });

  describe('Types', () => {
    it('LeaderboardEntry has required fields', async () => {
      const entry: import('@/lib/types').LeaderboardEntry = {
        agent_id: 1,
        display_name: 'Test',
        score: 85.5,
        rank_version: 'rank_v1',
        wins: 3,
        losses: 1,
        completed_runs: 4,
        invalid_runs: 0,
        twitter_handle: null,
      };
      expect(entry.score).toBe(85.5);
    });

    it('StrategySubmitRequest matches backend contract', async () => {
      const req: import('@/lib/types').StrategySubmitRequest = {
        agent_name: 'Bot',
        system_prompt: 'Do swaps.',
        config: { risk: 'low' },
      };
      expect(req.agent_name).toBe('Bot');
    });

    it('ChallengeDetailResponse includes contestants', async () => {
      const detail: import('@/lib/types').ChallengeDetailResponse = {
        challenge_id: 1,
        challenge_type: 'swap_execution',
        challenge_version: 'swap_execution_v1',
        llm_provider: 'anthropic',
        llm_model: 'claude-sonnet-4-20250514',
        status: 'active',
        config: {},
        num_contestants: 2,
        num_finalized: 0,
        winner_agent_id: null,
        contestants: [],
        created_at: '2025-01-01T00:00:00Z',
        started_at: null,
        ended_at: null,
      };
      expect(detail.contestants).toEqual([]);
    });
  });

  describe('Page exports', () => {
    it('builder page exports default', async () => {
      const mod = await import('@/app/builder/page');
      expect(mod.default).toBeDefined();
    });

    it('quickstart page exports default', async () => {
      const mod = await import('@/app/quickstart/page');
      expect(mod.default).toBeDefined();
    });

    it('leaderboard page exports default', async () => {
      const mod = await import('@/app/leaderboard/page');
      expect(mod.default).toBeDefined();
    });

    it('challenges page exports default', async () => {
      const mod = await import('@/app/challenges/page');
      expect(mod.default).toBeDefined();
    });

    it('submit page exports default', async () => {
      const mod = await import('@/app/submit/page');
      expect(mod.default).toBeDefined();
    });
  });
});
