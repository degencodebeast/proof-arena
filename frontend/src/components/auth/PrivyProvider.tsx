'use client';

import { PrivyProvider as Provider } from '@privy-io/react-auth';
import { useSyncExternalStore, type ReactNode } from 'react';

const subscribe = () => () => {};
const getSnapshot = () => true;
const getServerSnapshot = () => false;

export function PrivyProvider({ children }: { children: ReactNode }) {
  const isClient = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const appId = process.env.NEXT_PUBLIC_PRIVY_APP_ID;

  if (!isClient || !appId) {
    return <>{children}</>;
  }

  return (
    <Provider
      appId={appId}
      config={{
        loginMethods: ['email', 'wallet'],
        appearance: {
          theme: 'dark',
          accentColor: '#10b981',
        },
        embeddedWallets: {
          solana: {
            createOnLogin: 'users-without-wallets',
          },
        },
      }}
    >
      {children}
    </Provider>
  );
}
