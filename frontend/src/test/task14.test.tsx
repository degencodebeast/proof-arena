/**
 * Task 14: Leaderboard and Agent Profile Pages
 *
 * EDGE-CASE SPEC:
 *
 * INVARIANTS:
 * - Leaderboard rank = offset + index + 1 (deterministic across pages)
 * - Scores render with fixed precision (.toFixed(2))
 * - Backend returns leaderboard sorted by score DESC — no client re-sort
 * - Backend returns recent_runs sorted by created_at DESC — no client re-sort
 * - Twitter/X links: target="_blank" + rel="noopener noreferrer"
 * - Challenge links → /challenges/{id}; agent links → /agents/{id}
 * - USDC values: divide by 1_000_000, format with 2 decimals
 *
 * PRIVACY / PUBLIC-FIELD BOUNDARIES:
 * - Public: agent_id, display_name, owner_wallet, submission_hash, twitter_handle,
 *   current_rank, recent_runs (run_id, challenge_id, status, completion_status,
 *   starting_value, ending_value), score_breakdown
 * - Private (never rendered): system_prompt, config, privy_user_id, provider_type,
 *   provider_config
 *
 * AUTH:
 * - All endpoints public; no auth gating
 *
 * NEGATIVE / BOUNDARY CASES:
 * - Loading state: "Loading leaderboard..." / "Loading agent profile..."
 * - API error: "Failed to load..."
 * - Empty leaderboard on page 0: empty state, not blank table
 * - Non-numeric agent ID: "Invalid agent ID."
 * - 404 agent: "Failed to load agent profile."
 * - current_rank = null: AgentScoreCard shows "No rank yet" state
 * - score_breakdown = {} or missing keys: progress bars fall back to em-dash
 * - twitter_handle absent: not rendered
 * - Previous button disabled on page 1 (page === 0)
 * - Next button disabled when entries.length < PAGE_SIZE
 * - Next button enabled when entries.length === PAGE_SIZE
 * - Score precision: 85.5 → "85.50"
 * - Unknown run status: rendered as text with neutral style
 * - Recent runs empty: "No runs yet."
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from './test-utils';

// --- Hoisted mocks ---

const mocks = vi.hoisted(() => ({
  getLeaderboard: vi.fn(),
  getAgent: vi.fn(),
  params: {} as Record<string, string>,
}));

vi.mock('@/lib/api', () => ({
  agentArenaApi: {
    getLeaderboard: mocks.getLeaderboard,
    getAgent: mocks.getAgent,
    getChallenges: vi.fn(),
    getChallenge: vi.fn(),
    getChallengeEvents: vi.fn(),
    submitStrategy: vi.fn(),
  },
  default: { defaults: { baseURL: '/api/v1' } },
}));

vi.mock('next/navigation', () => ({
  useParams: () => mocks.params,
}));

vi.mock('next/link', () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

// --- Imports after mocks ---

import { AgentScoreCard } from '@/components/agent/AgentScoreCard';
import { RunSummaryCard } from '@/components/agent/RunSummaryCard';
import LeaderboardPage from '@/app/leaderboard/page';
import AgentProfilePage from '@/app/agents/[id]/page';
import type { LeaderboardEntry, RunSummary } from '@/lib/types';

// --- Fixtures ---

const mockEntry: LeaderboardEntry = {
  agent_id: 1,
  display_name: 'AlphaBot',
  score: 85.5,
  rank_version: 'rank_v1',
  wins: 3,
  losses: 1,
  completed_runs: 4,
  invalid_runs: 0,
  twitter_handle: null,
};

function makeEntries(count: number, startId = 1): LeaderboardEntry[] {
  return Array.from({ length: count }, (_, i) => ({
    ...mockEntry,
    agent_id: startId + i,
    display_name: `Agent${startId + i}`,
    score: 90 - i,
  }));
}

const mockRun: RunSummary = {
  run_id: 10,
  challenge_id: 5,
  status: 'completed',
  completion_status: 'complete',
  starting_value: 100_000_000,
  ending_value: 105_000_000,
};

const mockBreakdown = {
  win_rate: { value: 75.0, weight: 0.35 },
  execution_quality: { value: 92.5, weight: 0.3 },
  consistency: { value: 80.0, weight: 0.2 },
  confidence: { value: 60.0, weight: 0.15 },
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.params = {};
});

// ========================
// AgentScoreCard
// ========================

describe('AgentScoreCard', () => {
  it('renders no-rank state when rank is null', () => {
    render(<AgentScoreCard rank={null} breakdown={{}} />);
    expect(screen.getByTestId('score-card-no-rank')).toBeInTheDocument();
    expect(screen.getByText(/no rank yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('score-card')).not.toBeInTheDocument();
  });

  it('renders no-rank state when rank is undefined', () => {
    render(<AgentScoreCard rank={undefined} />);
    expect(screen.getByTestId('score-card-no-rank')).toBeInTheDocument();
  });

  it('renders score with fixed precision', () => {
    render(<AgentScoreCard rank={mockEntry} breakdown={mockBreakdown} />);
    expect(screen.getByText('85.50')).toBeInTheDocument();
  });

  it('renders rank_version', () => {
    render(<AgentScoreCard rank={mockEntry} breakdown={mockBreakdown} />);
    expect(screen.getByText(/rank_v1/)).toBeInTheDocument();
  });

  it('renders wins, losses, completed, invalid', () => {
    render(<AgentScoreCard rank={mockEntry} breakdown={mockBreakdown} />);
    expect(screen.getByText('Wins')).toBeInTheDocument();
    expect(screen.getByText('Losses')).toBeInTheDocument();
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('Invalid')).toBeInTheDocument();
  });

  it('renders all four breakdown components with rank_v1 labels', () => {
    render(<AgentScoreCard rank={mockEntry} breakdown={mockBreakdown} />);
    expect(screen.getByText('Win Rate')).toBeInTheDocument();
    expect(screen.getByText('Execution Quality')).toBeInTheDocument();
    expect(screen.getByText('Consistency')).toBeInTheDocument();
    expect(screen.getByText('Confidence')).toBeInTheDocument();
  });

  it('renders breakdown values with fixed precision', () => {
    render(<AgentScoreCard rank={mockEntry} breakdown={mockBreakdown} />);
    expect(screen.getByText('75.0')).toBeInTheDocument();
    expect(screen.getByText('92.5')).toBeInTheDocument();
  });

  it('handles missing breakdown values without crashing', () => {
    render(<AgentScoreCard rank={mockEntry} breakdown={{}} />);
    expect(screen.getByTestId('score-card')).toBeInTheDocument();
    // Missing values should show em-dash
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBe(4);
  });

  it('handles breakdown undefined without crashing', () => {
    render(<AgentScoreCard rank={mockEntry} />);
    expect(screen.getByTestId('score-card')).toBeInTheDocument();
  });

  it('handles malformed breakdown entries without crashing', () => {
    const malformed = {
      win_rate: { value: 'not a number' },
      execution_quality: null,
      consistency: { weight: 0.2 }, // missing value
      confidence: 'string not object',
    };
    render(
      <AgentScoreCard
        rank={mockEntry}
        breakdown={malformed as Record<string, unknown>}
      />
    );
    // Should render without throwing; all four bars fall back to em-dash
    expect(screen.getByTestId('score-card')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBe(4);
  });
});

// ========================
// RunSummaryCard
// ========================

describe('RunSummaryCard', () => {
  it('renders challenge link to /challenges/{id}', () => {
    render(<RunSummaryCard run={mockRun} />);
    const link = screen.getByText('Challenge #5').closest('a');
    expect(link).toHaveAttribute('href', '/challenges/5');
  });

  it.each([
    ['completed'],
    ['failed'],
    ['timeout'],
    ['running'],
    ['pending'],
  ])('renders status "%s" gracefully', (status) => {
    render(<RunSummaryCard run={{ ...mockRun, status }} />);
    expect(screen.getByTestId(`run-status-${mockRun.run_id}`)).toHaveTextContent(
      status
    );
  });

  it('renders unknown status without crashing', () => {
    render(<RunSummaryCard run={{ ...mockRun, status: 'mystery_status' }} />);
    expect(screen.getByTestId(`run-status-${mockRun.run_id}`)).toHaveTextContent(
      'mystery_status'
    );
  });

  it('distinguishes lifecycle status from completion_status', () => {
    render(<RunSummaryCard run={mockRun} />);
    expect(screen.getByTestId(`run-status-${mockRun.run_id}`)).toHaveTextContent(
      'completed'
    );
    expect(
      screen.getByTestId(`run-completion-${mockRun.run_id}`)
    ).toHaveTextContent('complete');
  });

  it('does not render completion_status when null', () => {
    render(<RunSummaryCard run={{ ...mockRun, completion_status: null }} />);
    expect(
      screen.queryByTestId(`run-completion-${mockRun.run_id}`)
    ).not.toBeInTheDocument();
  });

  it('formats USDC values with 2 decimals', () => {
    render(<RunSummaryCard run={mockRun} />);
    expect(screen.getByText('100.00 USDC')).toBeInTheDocument();
    expect(screen.getByText('105.00 USDC')).toBeInTheDocument();
  });

  it('renders em-dash for null ending_value', () => {
    render(<RunSummaryCard run={{ ...mockRun, ending_value: null }} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

// ========================
// LeaderboardPage
// ========================

describe('LeaderboardPage', () => {
  it('shows loading state', () => {
    mocks.getLeaderboard.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<LeaderboardPage />);
    expect(screen.getByTestId('loading')).toHaveTextContent(
      'Loading leaderboard...'
    );
  });

  it('shows empty state when no entries on page 0', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: [] });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('empty')).toBeInTheDocument();
    });
    expect(screen.getByText(/No ranked agents yet/)).toBeInTheDocument();
  });

  it('shows error state on API failure', async () => {
    mocks.getLeaderboard.mockRejectedValue(new Error('Network error'));
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toHaveTextContent(
        'Failed to load leaderboard.'
      );
    });
  });

  it('renders entries with agent links', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: [mockEntry] });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('row-1')).toBeInTheDocument();
    });
    // Desktop row link
    const rowLink = screen
      .getByTestId('row-1')
      .querySelector('a[href="/agents/1"]');
    expect(rowLink).not.toBeNull();
    // Mobile card link
    expect(screen.getByTestId('card-1')).toHaveAttribute('href', '/agents/1');
  });

  it('renders rank numbers deterministically on page 0: rank = index + 1', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: makeEntries(3, 10) });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('row-10')).toBeInTheDocument();
    });
    // First entry should be rank #1 (in both desktop + mobile)
    expect(screen.getAllByText('#1').length).toBe(2);
    expect(screen.getAllByText('#2').length).toBe(2);
    expect(screen.getAllByText('#3').length).toBe(2);
  });

  it('calls API with correct offset on pagination', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: makeEntries(25) });
    renderWithProviders(<LeaderboardPage />);

    // Wait for data to render so Next button is visible
    await waitFor(() => {
      expect(screen.getByTestId('next-button')).not.toBeDisabled();
    });

    expect(mocks.getLeaderboard).toHaveBeenCalledWith(25, 0);

    fireEvent.click(screen.getByTestId('next-button'));

    await waitFor(() => {
      expect(mocks.getLeaderboard).toHaveBeenCalledWith(25, 25);
    });
  });

  it('renders rank numbers with offset on page 2: rank = 25 + index + 1', async () => {
    mocks.getLeaderboard.mockResolvedValueOnce({ data: makeEntries(25) });
    renderWithProviders(<LeaderboardPage />);

    await waitFor(() => {
      expect(screen.getByTestId('next-button')).not.toBeDisabled();
    });

    mocks.getLeaderboard.mockResolvedValueOnce({
      data: makeEntries(3, 26),
    });
    fireEvent.click(screen.getByTestId('next-button'));

    await waitFor(() => {
      expect(screen.getByTestId('row-26')).toBeInTheDocument();
    });
    // First entry on page 2 should be rank #26
    expect(screen.getAllByText('#26').length).toBe(2);
  });

  it('disables Previous on page 1', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: [mockEntry] });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('row-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('prev-button')).toBeDisabled();
  });

  it('disables Next when returned count < page size', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: makeEntries(5) });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('row-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('next-button')).toBeDisabled();
  });

  it('enables Next when returned count equals page size', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: makeEntries(25) });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('row-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('next-button')).not.toBeDisabled();
  });

  it('renders scores with fixed 2-decimal precision', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: [mockEntry] });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      // 85.5 must render as "85.50" in both desktop + mobile
      expect(screen.getAllByText('85.50').length).toBe(2);
    });
  });

  it('does not render twitter_handle when absent', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: [mockEntry] });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('row-1')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('twitter-1')).not.toBeInTheDocument();
  });

  it('renders twitter_handle with safe external link when present', async () => {
    mocks.getLeaderboard.mockResolvedValue({
      data: [{ ...mockEntry, twitter_handle: 'alpha_bot' }],
    });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('twitter-1')).toBeInTheDocument();
    });
    const link = screen.getByTestId('twitter-1');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('href', 'https://x.com/alpha_bot');
  });

  it('normalizes twitter_handle with leading @ in URL', async () => {
    mocks.getLeaderboard.mockResolvedValue({
      data: [{ ...mockEntry, twitter_handle: '@alpha_bot' }],
    });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('twitter-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('twitter-1')).toHaveAttribute(
      'href',
      'https://x.com/alpha_bot'
    );
  });

  it('normalizes twitter_handle with whitespace before @', async () => {
    mocks.getLeaderboard.mockResolvedValue({
      data: [{ ...mockEntry, twitter_handle: ' @alpha_bot ' }],
    });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('twitter-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('twitter-1')).toHaveAttribute(
      'href',
      'https://x.com/alpha_bot'
    );
  });

  it('does not display @@ when twitter_handle already starts with @', async () => {
    mocks.getLeaderboard.mockResolvedValue({
      data: [{ ...mockEntry, twitter_handle: '@alpha_bot' }],
    });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('twitter-1')).toBeInTheDocument();
    });
    // Desktop + mobile both strip the extra @
    const matches = screen.getAllByText('@alpha_bot');
    expect(matches.length).toBe(2);
    expect(screen.queryByText('@@alpha_bot')).not.toBeInTheDocument();
  });

  it('renders pagination + empty-page state on empty page > 0', async () => {
    mocks.getLeaderboard.mockResolvedValueOnce({ data: makeEntries(25) });
    renderWithProviders(<LeaderboardPage />);

    await waitFor(() => {
      expect(screen.getByTestId('next-button')).not.toBeDisabled();
    });

    mocks.getLeaderboard.mockResolvedValueOnce({ data: [] });
    fireEvent.click(screen.getByTestId('next-button'));

    await waitFor(() => {
      expect(screen.getByTestId('empty-page')).toHaveTextContent(
        'No agents on this page.'
      );
    });
    // Pagination must remain so user can go back
    expect(screen.getByTestId('prev-button')).not.toBeDisabled();
    expect(screen.getByTestId('next-button')).toBeDisabled();
    expect(screen.getByText('Page 2')).toBeInTheDocument();
  });

  it('does not render pagination on initial empty state (page 0)', async () => {
    mocks.getLeaderboard.mockResolvedValue({ data: [] });
    renderWithProviders(<LeaderboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('empty')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('prev-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('next-button')).not.toBeInTheDocument();
  });
});

// ========================
// AgentProfilePage
// ========================

describe('AgentProfilePage', () => {
  it('shows error for non-numeric route ID', () => {
    mocks.params = { id: 'abc' };
    renderWithProviders(<AgentProfilePage />);
    expect(screen.getByTestId('invalid-id')).toHaveTextContent(
      'Invalid agent ID.'
    );
  });

  it.each(['1abc', '1.5', '-1', '0', '01', ' 1 ', ''])(
    'rejects malformed ID "%s" and does not fetch',
    (id) => {
      mocks.params = { id };
      renderWithProviders(<AgentProfilePage />);
      expect(screen.getByTestId('invalid-id')).toBeInTheDocument();
      expect(mocks.getAgent).not.toHaveBeenCalled();
    }
  );

  it('shows loading state', () => {
    mocks.params = { id: '1' };
    mocks.getAgent.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<AgentProfilePage />);
    expect(screen.getByTestId('loading')).toHaveTextContent(
      'Loading agent profile...'
    );
  });

  it('shows error state on 404/API failure', async () => {
    mocks.params = { id: '999' };
    mocks.getAgent.mockRejectedValue(new Error('Not found'));
    renderWithProviders(<AgentProfilePage />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toHaveTextContent(
        'Failed to load agent profile.'
      );
    });
  });

  it('renders profile with public fields', async () => {
    mocks.params = { id: '1' };
    mocks.getAgent.mockResolvedValue({
      data: {
        agent_id: 1,
        display_name: 'AlphaBot',
        owner_wallet: 'ABC123owner',
        submission_hash: 'deadbeef',
        twitter_handle: null,
        current_rank: mockEntry,
        recent_runs: [mockRun],
        score_breakdown: mockBreakdown,
      },
    });
    renderWithProviders(<AgentProfilePage />);
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'AlphaBot' })
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId('owner-wallet')).toHaveTextContent('ABC123owner');
    expect(screen.getByTestId('submission-hash')).toHaveTextContent('deadbeef');
    // Score from AgentScoreCard rendered
    expect(screen.getByText('85.50')).toBeInTheDocument();
    // Run card rendered
    expect(screen.getByText('Challenge #5')).toBeInTheDocument();
  });

  it('does not crash when current_rank is null', async () => {
    mocks.params = { id: '1' };
    mocks.getAgent.mockResolvedValue({
      data: {
        agent_id: 1,
        display_name: 'NewBot',
        owner_wallet: 'W',
        submission_hash: 'h',
        twitter_handle: null,
        current_rank: null,
        recent_runs: [],
        score_breakdown: {},
      },
    });
    renderWithProviders(<AgentProfilePage />);
    await waitFor(() => {
      expect(screen.getByText('NewBot')).toBeInTheDocument();
    });
    expect(screen.getByTestId('score-card-no-rank')).toBeInTheDocument();
  });

  it('does not crash when score_breakdown is empty', async () => {
    mocks.params = { id: '1' };
    mocks.getAgent.mockResolvedValue({
      data: {
        agent_id: 1,
        display_name: 'AlphaBot',
        owner_wallet: 'W',
        submission_hash: 'h',
        twitter_handle: null,
        current_rank: mockEntry,
        recent_runs: [],
        score_breakdown: {},
      },
    });
    renderWithProviders(<AgentProfilePage />);
    await waitFor(() => {
      expect(screen.getByTestId('score-card')).toBeInTheDocument();
    });
  });

  it('shows empty-runs state when recent_runs is empty', async () => {
    mocks.params = { id: '1' };
    mocks.getAgent.mockResolvedValue({
      data: {
        agent_id: 1,
        display_name: 'NewBot',
        owner_wallet: 'W',
        submission_hash: 'h',
        twitter_handle: null,
        current_rank: null,
        recent_runs: [],
        score_breakdown: {},
      },
    });
    renderWithProviders(<AgentProfilePage />);
    await waitFor(() => {
      expect(screen.getByTestId('empty-runs')).toBeInTheDocument();
    });
  });

  it('renders twitter_handle link with safe attributes when present', async () => {
    mocks.params = { id: '1' };
    mocks.getAgent.mockResolvedValue({
      data: {
        agent_id: 1,
        display_name: 'A',
        owner_wallet: 'W',
        submission_hash: 'h',
        twitter_handle: 'my_agent',
        current_rank: null,
        recent_runs: [],
        score_breakdown: {},
      },
    });
    renderWithProviders(<AgentProfilePage />);
    await waitFor(() => {
      expect(screen.getByTestId('twitter-link')).toBeInTheDocument();
    });
    const link = screen.getByTestId('twitter-link');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('href', 'https://x.com/my_agent');
  });

  it('normalizes twitter_handle with leading @ in profile URL', async () => {
    mocks.params = { id: '1' };
    mocks.getAgent.mockResolvedValue({
      data: {
        agent_id: 1,
        display_name: 'A',
        owner_wallet: 'W',
        submission_hash: 'h',
        twitter_handle: '@my_agent',
        current_rank: null,
        recent_runs: [],
        score_breakdown: {},
      },
    });
    renderWithProviders(<AgentProfilePage />);
    await waitFor(() => {
      expect(screen.getByTestId('twitter-link')).toBeInTheDocument();
    });
    expect(screen.getByTestId('twitter-link')).toHaveAttribute(
      'href',
      'https://x.com/my_agent'
    );
  });

  it('does not render private strategy fields in profile view', async () => {
    mocks.params = { id: '1' };
    mocks.getAgent.mockResolvedValue({
      data: {
        agent_id: 1,
        display_name: 'A',
        owner_wallet: 'W',
        submission_hash: 'h',
        twitter_handle: null,
        current_rank: mockEntry,
        recent_runs: [mockRun],
        score_breakdown: mockBreakdown,
      },
    });
    renderWithProviders(<AgentProfilePage />);
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'A' })).toBeInTheDocument();
    });
    expect(screen.queryByText(/system_prompt/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/config_json/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/privy_user_id/i)).not.toBeInTheDocument();
  });
});
