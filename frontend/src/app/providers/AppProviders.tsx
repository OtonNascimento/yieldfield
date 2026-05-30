import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactElement, type ReactNode } from 'react';

import { ThemeProvider } from '@/design-system';

/**
 * Application composition root for global context (ARCHITECTURE app/providers/):
 * the server-state cache (§9, TanStack Query) and the design system's theme
 * provider (§5A). No business logic — wiring only.
 */
export function AppProviders({ children }: { children: ReactNode }): ReactElement {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>{children}</ThemeProvider>
    </QueryClientProvider>
  );
}
