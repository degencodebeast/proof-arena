'use client';

import Link from 'next/link';
import { usePrivy } from '@privy-io/react-auth';

function AuthSection() {
  const { login, logout, authenticated, user } = usePrivy();

  if (authenticated) {
    return (
      <button onClick={logout} className="text-zinc-500 hover:text-zinc-300 text-xs font-mono transition">
        {user?.wallet?.address
          ? `${user.wallet.address.slice(0, 4)}...${user.wallet.address.slice(-4)}`
          : 'Disconnect'}
      </button>
    );
  }

  return (
    <button onClick={login} className="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-1.5 rounded-md text-sm font-medium transition">
      Connect
    </button>
  );
}

function AuthSectionSafe() {
  // Render auth section only when Privy provider is available
  const appId = process.env.NEXT_PUBLIC_PRIVY_APP_ID;
  if (!appId) {
    return (
      <span className="text-zinc-600 text-xs">Auth unavailable</span>
    );
  }
  return <AuthSection />;
}

export function Header() {
  return (
    <header className="border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-sm sticky top-0 z-50">
      <nav className="max-w-7xl mx-auto px-4 h-16 flex justify-between items-center">
        <Link href="/" className="text-lg font-bold tracking-tight text-emerald-400">
          Proof Arena
        </Link>

        <div className="flex gap-5 items-center text-sm">
          <Link href="/templates" className="text-zinc-400 hover:text-white transition">
            Templates
          </Link>
          <Link href="/flagship" className="text-zinc-400 hover:text-white transition">
            Flagship
          </Link>
          <Link href="/leaderboard" className="text-zinc-400 hover:text-white transition">
            Leaderboard
          </Link>

          <AuthSectionSafe />
        </div>
      </nav>
    </header>
  );
}
