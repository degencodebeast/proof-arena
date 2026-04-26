import axios from 'axios';
import type {
  LeaderboardEntry,
  AgentProfileResponse,
  ChallengeSummary,
  ChallengeDetailResponse,
  RunEventSummary,
  StrategySubmitRequest,
  StrategyResponse,
  FlagshipResponse,
  InstanceProfileResponse,
  TemplateSummary,
  TemplateDetailResponse,
  InstanceDeployRequest,
  InstanceDeployResponse,
} from './types';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1',
});

export const agentArenaApi = {
  getLeaderboard: (
    limit = 50,
    offset = 0,
    subject?: 'canonical' | 'customized',
  ) =>
    api.get<LeaderboardEntry[]>('/leaderboard', {
      params: { limit, offset, ...(subject ? { subject } : {}) },
    }),

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

  getFlagship: () => api.get<FlagshipResponse>('/flagship'),

  listTemplates: () => api.get<TemplateSummary[]>('/templates'),

  getInstance: (instanceId: number, accessToken: string) =>
    api.get<InstanceProfileResponse>(`/instances/${instanceId}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    }),

  getTemplate: (templateKey: string) =>
    api.get<TemplateDetailResponse>(`/templates/${templateKey}`),

  deployInstance: (body: InstanceDeployRequest, accessToken: string) =>
    api.post<InstanceDeployResponse>('/instances/deploy', body, {
      headers: { Authorization: `Bearer ${accessToken}` },
    }),
};

export default api;
