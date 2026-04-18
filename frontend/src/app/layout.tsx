import type { Metadata } from 'next';
import './globals.css';
import { PrivyProvider } from '@/components/auth/PrivyProvider';
import { QueryProvider } from '@/components/QueryProvider';
import { Header } from '@/components/Header';

export const metadata: Metadata = {
  title: 'Proof Arena — Verifiable Agent Performance',
  description: 'The benchmark and reputation layer for on-chain AI agents.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="font-sans bg-zinc-950 text-zinc-100 min-h-screen antialiased">
        <PrivyProvider>
          <QueryProvider>
            <Header />
            <main className="max-w-7xl mx-auto px-4 py-8">{children}</main>
          </QueryProvider>
        </PrivyProvider>
      </body>
    </html>
  );
}
