import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { login as loginRequest, problemMessageRu, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { useAuthStore, homeRouteForRole } from '@/entities/session';

/** Route: /login. Local username/password against `POST /auth/login` (D8). On success the token
 * and account go into `entities/session`'s auth store and the user lands on their role's home
 * route (D12 design decision #4). */
export function LoginPage() {
  const navigate = useNavigate();
  const authLogin = useAuthStore((state) => state.login);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const mutation = useMutation({
    mutationFn: () => loginRequest({ username, password }),
    onSuccess: (response) => {
      authLogin(response.access_token, response.user);
      navigate(homeRouteForRole(response.user.user_role), { replace: true });
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate();
  }

  const errorMessage = mutation.isError
    ? mutation.error instanceof ProblemError
      ? problemMessageRu(mutation.error.code as ProblemCode)
      : t('problemUnknown')
    : null;

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <h1 className="font-heading text-base leading-snug font-medium">{t('loginTitle')}</h1>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="login-username">{t('loginUsernameLabel')}</Label>
              <Input
                id="login-username"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="login-password">{t('loginPasswordLabel')}</Label>
              <Input
                id="login-password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            {errorMessage ? (
              <p role="alert" className="text-sm text-destructive">
                {errorMessage}
              </p>
            ) : null}
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? t('loginSubmitting') : t('loginSubmit')}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
