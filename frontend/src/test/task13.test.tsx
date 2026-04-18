/**
 * Task 13: Strategy Submission and Challenge Views
 *
 * EDGE-CASE SPEC (written before implementation per TDD requirements):
 *
 * INVARIANTS:
 * - Unauthenticated users cannot submit strategies (SubmitForm, StrategyBuilderLite)
 * - agent_name is required and max 64 chars
 * - system_prompt is required (SubmitForm only; builder uses template)
 * - Config JSON must be valid before mutation (SubmitForm)
 * - Strategy Builder templates produce deterministic system_prompt + config
 * - Submission success displays submission_hash, never private backend fields
 * - Challenge status badges are deterministic for known statuses; unknown statuses render gracefully
 * - Events render in backend-provided order (no client-side re-sort)
 * - TX links use devnet explorer with rel="noopener noreferrer" and target="_blank"
 * - winner_agent_id highlight only when it matches a contestant
 *
 * PRIVACY / PUBLIC-FIELD BOUNDARIES:
 * - Public: submission_hash, display_name, agent_id, onchain_address
 * - Private (never in challenge views): system_prompt, config (strategy-specific)
 * - Challenge config is public (challenge-level, not strategy-level)
 *
 * AUTH BOUNDARIES:
 * - POST /strategies: requires authenticated user + valid access token
 * - GET /challenges, /challenges/:id, /challenges/:id/events: public
 *
 * DATA CONSISTENCY / ORDERING:
 * - Events rendered in array order from backend (sequence_no-sorted)
 * - ContestantsList may receive empty or undefined array
 *
 * IDEMPOTENCY / RETRY:
 * - Submit button disabled during pending mutation
 * - Backend anti-spam limits (429) surfaced as user-facing error
 *
 * NEGATIVE / BOUNDARY CASES:
 * - getAccessToken() returning null → safe error
 * - Empty agent_name → validation error
 * - agent_name > 64 chars → validation error
 * - Invalid JSON config → validation error
 * - API error → user-facing message without stack traces
 * - Challenge list empty → empty state
 * - Challenge list API error → error state
 * - Challenge ID non-numeric → "Invalid challenge ID"
 * - Empty events → "No events yet."
 * - Unknown event type → renders type name with neutral style
 * - ContestantsList undefined/empty → "No contestants."
 * - Winner not matching any contestant → no highlight
 *
 * POLLING:
 * - Active challenges: refetchInterval=5000 for events
 * - Non-active challenges: refetchInterval=false
 * - (Polling behavior not unit-tested; verified via code review of refetchInterval logic)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from './test-utils';

// --- Hoisted mocks ---

const mocks = vi.hoisted(() => ({
  submitStrategy: vi.fn(),
  getChallenges: vi.fn(),
  getChallenge: vi.fn(),
  getChallengeEvents: vi.fn(),
  privy: {
    authenticated: false,
    getAccessToken: vi.fn().mockResolvedValue('test-token'),
    login: vi.fn(),
    logout: vi.fn(),
    user: null as unknown,
  },
  params: {} as Record<string, string>,
}));

vi.mock('@privy-io/react-auth', () => ({
  usePrivy: () => mocks.privy,
}));

vi.mock('@/lib/api', () => ({
  agentArenaApi: {
    submitStrategy: mocks.submitStrategy,
    getChallenges: mocks.getChallenges,
    getChallenge: mocks.getChallenge,
    getChallengeEvents: mocks.getChallengeEvents,
    getLeaderboard: vi.fn(),
    getAgent: vi.fn(),
  },
  default: { defaults: { baseURL: '/api/v1' } },
}));

vi.mock('next/navigation', () => ({
  useParams: () => mocks.params,
}));

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

// --- Imports (after mocks) ---

import { SubmitForm } from '@/components/strategy/SubmitForm';
import {
  StrategyBuilderLite,
  STRATEGY_TEMPLATES,
} from '@/components/strategy/StrategyBuilderLite';
import { ChallengeCard } from '@/components/challenge/ChallengeCard';
import { LiveRunView } from '@/components/challenge/LiveRunView';
import { ContestantsList } from '@/components/challenge/ContestantsList';
import ChallengesPage from '@/app/challenges/page';
import ChallengeDetailPage from '@/app/challenges/[id]/page';

import type { ChallengeSummary, RunEventSummary, ContestantSummary } from '@/lib/types';

// --- Fixtures ---

const mockChallenge: ChallengeSummary = {
  challenge_id: 1,
  challenge_type: 'swap_execution',
  challenge_version: 'swap_execution_v1',
  status: 'active',
  num_contestants: 2,
  num_finalized: 0,
  started_at: '2025-04-01T00:00:00Z',
  ended_at: null,
};

const mockEvents: RunEventSummary[] = [
  {
    event_id: 1,
    run_id: 1,
    sequence_no: 1,
    event_type: 'observe',
    timestamp: '2025-04-01T00:01:00Z',
    tx_signature: null,
  },
  {
    event_id: 2,
    run_id: 1,
    sequence_no: 2,
    event_type: 'execute',
    timestamp: '2025-04-01T00:02:00Z',
    tx_signature: '5abc123def',
  },
];

const mockContestants: ContestantSummary[] = [
  {
    agent_id: 10,
    display_name: 'Agent Alpha',
    run_id: 1,
    status: 'completed',
    completion_status: 'complete',
    ending_value: 105_000_000,
  },
  {
    agent_id: 20,
    display_name: 'Agent Beta',
    run_id: 2,
    status: 'completed',
    completion_status: 'incomplete',
    ending_value: 98_000_000,
  },
];

// --- Helpers ---

function setAuthenticated(value: boolean) {
  mocks.privy.authenticated = value;
  mocks.privy.getAccessToken = vi.fn().mockResolvedValue(value ? 'test-token' : null);
  mocks.privy.login = vi.fn();
}

// --- Tests ---

beforeEach(() => {
  vi.clearAllMocks();
  setAuthenticated(false);
  mocks.params = {};
});

// ========================
// SubmitForm
// ========================

describe('SubmitForm', () => {
  it('shows auth prompt when not authenticated', () => {
    renderWithProviders(<SubmitForm />);
    expect(screen.getByTestId('auth-prompt')).toBeInTheDocument();
    expect(screen.getByText(/connect your wallet or sign in/i)).toBeInTheDocument();
  });

  it('shows sign-in button for unauthenticated users', () => {
    renderWithProviders(<SubmitForm />);
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders form fields when authenticated', () => {
    setAuthenticated(true);
    renderWithProviders(<SubmitForm />);
    expect(screen.getByLabelText(/agent name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/system prompt/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/config/i)).toBeInTheDocument();
  });

  it('shows error when agent name is empty on submit', async () => {
    setAuthenticated(true);
    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'Test prompt' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Agent name is required.');
    });
  });

  it('shows error when agent name exceeds 64 characters', async () => {
    setAuthenticated(true);
    renderWithProviders(<SubmitForm />);

    // The input has maxLength=64, so we set value directly via state
    // We need to type a name > 64 chars. Since maxLength caps the input,
    // we test the JS validation with a name that's exactly at the boundary.
    // NOTE: HTML maxLength prevents typing beyond 64, so this test verifies
    // the JS validation layer for programmatic input.
    const input = screen.getByLabelText(/agent name/i);
    // Simulate a programmatic value that bypasses maxLength
    Object.defineProperty(input, 'value', { value: 'a'.repeat(65), writable: true });
    fireEvent.change(input, { target: { value: 'a'.repeat(65) } });
    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'Test' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Agent name must be 64 characters or fewer.'
      );
    });
  });

  it('shows error when system prompt is empty', async () => {
    setAuthenticated(true);
    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'TestBot' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('System prompt is required.');
    });
  });

  it('shows error when config JSON is invalid', async () => {
    setAuthenticated(true);
    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'TestBot' },
    });
    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'Test prompt' },
    });
    fireEvent.change(screen.getByLabelText(/config/i), {
      target: { value: '{invalid json' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Config must be valid JSON.');
    });
  });

  it('shows error when getAccessToken returns null', async () => {
    setAuthenticated(true);
    mocks.privy.getAccessToken = vi.fn().mockResolvedValue(null);
    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'TestBot' },
    });
    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'Test prompt' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Authentication required. Please sign in and try again.'
      );
    });
  });

  it('shows submission_hash on success', async () => {
    setAuthenticated(true);
    mocks.submitStrategy.mockResolvedValue({
      data: {
        agent_id: 1,
        display_name: 'TestBot',
        submission_hash: 'abc123hash',
        onchain_address: null,
      },
    });

    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'TestBot' },
    });
    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'Test prompt' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByTestId('success-message')).toBeInTheDocument();
    });
    expect(screen.getByText(/abc123hash/)).toBeInTheDocument();
    expect(screen.getByText(/TestBot/)).toBeInTheDocument();
  });

  it('does not display private backend-only fields on success', async () => {
    setAuthenticated(true);
    mocks.submitStrategy.mockResolvedValue({
      data: {
        agent_id: 42,
        display_name: 'TestBot',
        submission_hash: 'hash123',
        onchain_address: 'ABC123onchain',
      },
    });

    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'TestBot' },
    });
    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'prompt' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByTestId('success-message')).toBeInTheDocument();
    });

    const successEl = screen.getByTestId('success-message');
    // onchain_address should not be shown
    expect(successEl).not.toHaveTextContent('ABC123onchain');
    // raw agent_id should not be shown as a standalone visible field
    expect(successEl).not.toHaveTextContent('agent_id');
  });

  it('shows backend detail for 4xx errors', async () => {
    setAuthenticated(true);
    mocks.submitStrategy.mockRejectedValue({
      response: { status: 429, data: { detail: 'Rate limit exceeded' } },
    });

    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'TestBot' },
    });
    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'prompt' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Rate limit exceeded');
    });
  });

  it('shows generic error for 5xx responses without leaking detail', async () => {
    setAuthenticated(true);
    mocks.submitStrategy.mockRejectedValue({
      response: { status: 500, data: { detail: 'Internal: db connection pool exhausted at line 42' } },
    });

    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'TestBot' },
    });
    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'prompt' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Submission failed. Please try again.');
    });
    expect(screen.getByRole('alert')).not.toHaveTextContent('db connection');
  });

  it('disables submit button during pending', async () => {
    setAuthenticated(true);
    // Never-resolving promise to keep mutation pending
    mocks.submitStrategy.mockReturnValue(new Promise(() => {}));

    renderWithProviders(<SubmitForm />);

    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'TestBot' },
    });
    fireEvent.change(screen.getByLabelText(/system prompt/i), {
      target: { value: 'prompt' },
    });
    fireEvent.submit(screen.getByRole('form', { name: /submit strategy/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /submitting/i })).toBeDisabled();
    });
  });
});

// ========================
// StrategyBuilderLite
// ========================

describe('StrategyBuilderLite', () => {
  it('shows auth prompt when not authenticated', () => {
    renderWithProviders(<StrategyBuilderLite />);
    expect(screen.getByTestId('auth-prompt')).toBeInTheDocument();
  });

  it('renders all three templates when authenticated', () => {
    setAuthenticated(true);
    renderWithProviders(<StrategyBuilderLite />);
    expect(screen.getByTestId('template-CONSERVATIVE')).toBeInTheDocument();
    expect(screen.getByTestId('template-BALANCED')).toBeInTheDocument();
    expect(screen.getByTestId('template-AGGRESSIVE')).toBeInTheDocument();
  });

  it('templates produce deterministic system_prompt and config', () => {
    // Invariant: templates are static objects, not computed at runtime
    expect(STRATEGY_TEMPLATES.CONSERVATIVE.system_prompt).toBe(
      'Execute swaps conservatively with low slippage. Prefer stable routes. Minimize unnecessary swaps. Prioritize capital preservation while completing the required basket.'
    );
    expect(STRATEGY_TEMPLATES.CONSERVATIVE.config.max_slippage_bps).toBe(50);
    expect(STRATEGY_TEMPLATES.BALANCED.config.risk_level).toBe('medium');
    expect(STRATEGY_TEMPLATES.AGGRESSIVE.config.max_slippage_bps).toBe(200);
  });

  it('shows preview after template selection', () => {
    setAuthenticated(true);
    renderWithProviders(<StrategyBuilderLite />);

    fireEvent.click(screen.getByTestId('template-CONSERVATIVE'));

    expect(screen.getByTestId('template-preview')).toBeInTheDocument();
    expect(screen.getByText(/Execute swaps conservatively/)).toBeInTheDocument();
  });

  it('shows error when submitting without agent name', async () => {
    setAuthenticated(true);
    renderWithProviders(<StrategyBuilderLite />);

    fireEvent.click(screen.getByTestId('template-BALANCED'));
    fireEvent.click(screen.getByTestId('builder-submit'));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Agent name is required.');
    });
  });

  it('shows submission_hash on success', async () => {
    setAuthenticated(true);
    mocks.submitStrategy.mockResolvedValue({
      data: {
        agent_id: 5,
        display_name: 'MyAgent',
        submission_hash: 'builder_hash_abc',
        onchain_address: null,
      },
    });

    renderWithProviders(<StrategyBuilderLite />);

    fireEvent.click(screen.getByTestId('template-AGGRESSIVE'));
    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'MyAgent' },
    });
    fireEvent.click(screen.getByTestId('builder-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('success-message')).toBeInTheDocument();
    });
    expect(screen.getByText(/builder_hash_abc/)).toBeInTheDocument();
  });

  it('calls submitStrategy with template prompt and config', async () => {
    setAuthenticated(true);
    mocks.submitStrategy.mockResolvedValue({
      data: { agent_id: 1, display_name: 'A', submission_hash: 'h', onchain_address: null },
    });

    renderWithProviders(<StrategyBuilderLite />);

    fireEvent.click(screen.getByTestId('template-CONSERVATIVE'));
    fireEvent.change(screen.getByLabelText(/agent name/i), {
      target: { value: 'ConBot' },
    });
    fireEvent.click(screen.getByTestId('builder-submit'));

    await waitFor(() => {
      expect(mocks.submitStrategy).toHaveBeenCalledWith(
        {
          agent_name: 'ConBot',
          system_prompt: STRATEGY_TEMPLATES.CONSERVATIVE.system_prompt,
          config: expect.objectContaining({
            risk_level: 'low',
            max_slippage_bps: 50,
          }),
        },
        'test-token'
      );
    });
  });
});

// ========================
// ChallengeCard
// ========================

describe('ChallengeCard', () => {
  it('renders challenge info', () => {
    render(<ChallengeCard challenge={mockChallenge} />);
    expect(screen.getByText('Challenge #1')).toBeInTheDocument();
    expect(screen.getByText(/2 contestants/)).toBeInTheDocument();
  });

  it.each([
    ['pending', 'Pending'],
    ['active', 'Active'],
    ['settling', 'Settling'],
    ['completed', 'Completed'],
  ])('shows correct status badge for %s', (status, label) => {
    render(
      <ChallengeCard challenge={{ ...mockChallenge, status }} />
    );
    expect(screen.getByTestId('status-badge')).toHaveTextContent(label);
  });

  it('renders gracefully for unknown status', () => {
    render(
      <ChallengeCard challenge={{ ...mockChallenge, status: 'mystery_status' }} />
    );
    expect(screen.getByTestId('status-badge')).toHaveTextContent('mystery_status');
  });
});

// ========================
// LiveRunView
// ========================

describe('LiveRunView', () => {
  it('shows empty state when no events', () => {
    render(<LiveRunView events={[]} />);
    expect(screen.getByTestId('empty-events')).toHaveTextContent('No events yet.');
  });

  it('shows empty state when events is undefined', () => {
    render(<LiveRunView />);
    expect(screen.getByTestId('empty-events')).toBeInTheDocument();
  });

  it('shows loading state when isLoading is true', () => {
    render(<LiveRunView isLoading={true} />);
    expect(screen.getByTestId('events-loading')).toHaveTextContent(
      'Loading events...'
    );
    expect(screen.queryByTestId('empty-events')).not.toBeInTheDocument();
  });

  it('shows error state when isError is true', () => {
    render(<LiveRunView isError={true} />);
    expect(screen.getByTestId('events-error')).toHaveTextContent(
      'Failed to load events.'
    );
    expect(screen.queryByTestId('empty-events')).not.toBeInTheDocument();
  });

  it('renders events in order', () => {
    render(<LiveRunView events={mockEvents} />);
    expect(screen.getByTestId('event-type-1')).toHaveTextContent('observe');
    expect(screen.getByTestId('event-type-2')).toHaveTextContent('execute');
  });

  it('renders unknown event types gracefully', () => {
    const unknownEvent: RunEventSummary = {
      event_id: 99,
      run_id: 1,
      sequence_no: 1,
      event_type: 'future_event_type',
      timestamp: '2025-04-01T00:00:00Z',
      tx_signature: null,
    };
    render(<LiveRunView events={[unknownEvent]} />);
    expect(screen.getByTestId('event-type-99')).toHaveTextContent('future_event_type');
  });

  it('renders TX links with devnet explorer URL', () => {
    render(<LiveRunView events={mockEvents} />);
    const link = screen.getByText('View TX');
    expect(link).toHaveAttribute(
      'href',
      'https://explorer.solana.com/tx/5abc123def?cluster=devnet'
    );
  });

  it('TX links open in new tab with safe rel', () => {
    render(<LiveRunView events={mockEvents} />);
    const link = screen.getByText('View TX');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('does not render TX link when tx_signature is null', () => {
    render(<LiveRunView events={[mockEvents[0]]} />);
    expect(screen.queryByText('View TX')).not.toBeInTheDocument();
  });
});

// ========================
// ContestantsList
// ========================

describe('ContestantsList', () => {
  it('handles empty contestants array', () => {
    render(<ContestantsList contestants={[]} />);
    expect(screen.getByTestId('empty-contestants')).toHaveTextContent('No contestants.');
  });

  it('handles undefined contestants', () => {
    render(<ContestantsList />);
    expect(screen.getByTestId('empty-contestants')).toBeInTheDocument();
  });

  it('renders contestant info', () => {
    render(<ContestantsList contestants={mockContestants} />);
    expect(screen.getByText('Agent Alpha')).toBeInTheDocument();
    expect(screen.getByText('Agent Beta')).toBeInTheDocument();
    expect(screen.getByText('105.00 USDC', { exact: false })).toBeInTheDocument();
  });

  it('highlights winner when winner_agent_id matches', () => {
    render(<ContestantsList contestants={mockContestants} winnerAgentId={10} />);
    expect(screen.getByTestId('winner-badge')).toBeInTheDocument();
    // Winner badge should be near Agent Alpha
    const container = screen.getByTestId('contestant-10');
    expect(container).toHaveTextContent('WINNER');
  });

  it('does not highlight when winner_agent_id is null', () => {
    render(<ContestantsList contestants={mockContestants} winnerAgentId={null} />);
    expect(screen.queryByTestId('winner-badge')).not.toBeInTheDocument();
  });

  it('does not highlight when winner_agent_id does not match any contestant', () => {
    render(<ContestantsList contestants={mockContestants} winnerAgentId={999} />);
    expect(screen.queryByTestId('winner-badge')).not.toBeInTheDocument();
  });

  it('links contestant names to agent profiles', () => {
    render(<ContestantsList contestants={mockContestants} />);
    const link = screen.getByText('Agent Alpha').closest('a');
    expect(link).toHaveAttribute('href', '/agents/10');
    const link2 = screen.getByText('Agent Beta').closest('a');
    expect(link2).toHaveAttribute('href', '/agents/20');
  });

  it('does not render private strategy fields', () => {
    render(<ContestantsList contestants={mockContestants} winnerAgentId={10} />);
    // system_prompt and config should never appear
    expect(screen.queryByText(/system_prompt/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/risk_level/i)).not.toBeInTheDocument();
  });
});

// ========================
// ChallengesPage
// ========================

describe('ChallengesPage', () => {
  it('shows loading state', () => {
    mocks.getChallenges.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<ChallengesPage />);
    expect(screen.getByTestId('loading')).toHaveTextContent('Loading challenges...');
  });

  it('shows empty state when no challenges', async () => {
    mocks.getChallenges.mockResolvedValue({ data: [] });
    renderWithProviders(<ChallengesPage />);
    await waitFor(() => {
      expect(screen.getByTestId('empty')).toHaveTextContent('No challenges yet.');
    });
  });

  it('renders challenge cards on success', async () => {
    mocks.getChallenges.mockResolvedValue({ data: [mockChallenge] });
    renderWithProviders(<ChallengesPage />);
    await waitFor(() => {
      expect(screen.getByText('Challenge #1')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    mocks.getChallenges.mockRejectedValue(new Error('Network error'));
    renderWithProviders(<ChallengesPage />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toHaveTextContent('Failed to load challenges.');
    });
  });
});

// ========================
// ChallengeDetailPage
// ========================

describe('ChallengeDetailPage', () => {
  it('shows error for non-numeric route ID', () => {
    mocks.params = { id: 'abc' };
    renderWithProviders(<ChallengeDetailPage />);
    expect(screen.getByTestId('invalid-id')).toHaveTextContent('Invalid challenge ID.');
  });

  it.each(['1abc', '1.5', '-1', '0'])(
    'rejects malformed challenge ID "%s" and does not fetch',
    (id) => {
      mocks.params = { id };
      renderWithProviders(<ChallengeDetailPage />);
      expect(screen.getByTestId('invalid-id')).toBeInTheDocument();
      expect(mocks.getChallenge).not.toHaveBeenCalled();
    }
  );

  it('shows loading state', () => {
    mocks.params = { id: '42' };
    mocks.getChallenge.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<ChallengeDetailPage />);
    expect(screen.getByTestId('loading')).toHaveTextContent('Loading challenge...');
  });

  it('renders challenge detail with contestants and events', async () => {
    mocks.params = { id: '1' };
    mocks.getChallenge.mockResolvedValue({
      data: {
        challenge_id: 1,
        challenge_type: 'swap_execution',
        challenge_version: 'swap_execution_v1',
        llm_provider: 'anthropic',
        llm_model: 'claude-sonnet',
        status: 'active',
        config: {},
        num_contestants: 2,
        num_finalized: 0,
        winner_agent_id: null,
        contestants: mockContestants,
        created_at: '2025-04-01T00:00:00Z',
        started_at: '2025-04-01T00:00:00Z',
        ended_at: null,
      },
    });
    mocks.getChallengeEvents.mockResolvedValue({ data: mockEvents });

    renderWithProviders(<ChallengeDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Challenge #1')).toBeInTheDocument();
    });
    expect(screen.getByText('Agent Alpha')).toBeInTheDocument();
    expect(screen.getByText('Agent Beta')).toBeInTheDocument();
  });

  it('shows error when challenge not found', async () => {
    mocks.params = { id: '999' };
    mocks.getChallenge.mockRejectedValue(new Error('Not found'));
    renderWithProviders(<ChallengeDetailPage />);

    await waitFor(() => {
      expect(screen.getByTestId('error')).toHaveTextContent('Failed to load challenge.');
    });
  });
});
