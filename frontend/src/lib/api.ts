import axios from 'axios';
import type {
  LeaderboardEntry,
  AgentProfileResponse,
  ChallengeSummary,
  ChallengeDetailResponse,
  RunEventSummary,
  StrategySubmitRequest,
  StrategyResponse,
} from './types';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1',
});

export const agentArenaApi = {
  getLeaderboard: (limit = 50, offset = 0) =>
    api.get<LeaderboardEntry[]>('/leaderboard', { params: { limit, offset } }),

  getAgent: (agentId: number) =>
    api.get<AgentProfileResponse>(`/agents/${agentId}`),

  getChallenges: (status?: string) =>
    api.get<ChallengeSummary[]>('/challenges', { params: { status } }),

  getChallenge: (challengeId: number) =>
    api.get<ChallengeDetailResponse>(`/challenges/${challengeId}`),

  getChallengeEvents: (challengeId: number, limit = 100) =>
    api.get<RunEventSummary[]>(`/challenges/${challengeId}/events`, { params: { limit } }),

  submitStrategy: (data: StrategySubmitRequest, accessToken: string) =>
    api.post<StrategyResponse>('/strategies', data, {
      headers: { Authorization: `Bearer ${accessToken}` },
    }),
};

export default api;
