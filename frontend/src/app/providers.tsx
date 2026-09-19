import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/shared/ui/tooltip';
import { Toaster } from '@/shared/ui/sonner';

const queryClient = new QueryClient();

/** App-wide providers: TanStack Query for REST, tooltip context for
 * shadcn/ui primitives, and the toast host. Zustand stores are local
 * modules with no provider and are added per realtime concern starting
 * E7/E11. */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        {children}
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
