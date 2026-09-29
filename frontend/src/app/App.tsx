import { BrowserRouter } from 'react-router';
import { AppProviders } from '@/app/providers';
import { AppRoutes } from '@/app/router';
import { TourHost } from '@/shared/ui/tour';

export function App() {
  return (
    <AppProviders>
      <BrowserRouter>
        <AppRoutes />
        {/* I7 E56: the guided tour's overlay, above every route (a tour spans pages). */}
        <TourHost />
      </BrowserRouter>
    </AppProviders>
  );
}
