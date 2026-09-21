import { useNavigate } from 'react-router';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { useAuthStore } from '@/entities/session';

/** Signs out and returns to /login. Used from the app shell header (D12: "header with user,
 * role, connection + readiness badges"). */
export function LogoutButton() {
  const navigate = useNavigate();
  const logout = useAuthStore((state) => state.logout);

  function handleClick() {
    logout();
    navigate('/login', { replace: true });
  }

  return (
    <Button variant="ghost" size="sm" onClick={handleClick}>
      {t('logoutButton')}
    </Button>
  );
}
