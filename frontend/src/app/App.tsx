import { BrowserRouter } from 'react-router';
import { AppProviders } from '@/app/providers';
import { AppRoutes } from '@/app/router';

export function App() {
  return (
    <AppProviders>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AppProviders>
  );
}
