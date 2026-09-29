// I7 E56 (owner item 6): a beginner hint — a small «?» next to a key field that shows one sentence
// in a tooltip (hover or keyboard focus). Renders nothing unless the signed-in user turned
// «Подсказки для новичков» on in the user menu (default off: the tour covers first use).
import { CircleHelp } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/ui/tooltip';
import { t } from '@/shared/i18n';
import { useAuthStore } from '@/entities/session';
import { useHintsEnabled } from './tour-preferences';

export function Hint({ text }: { text: string }) {
  const user = useAuthStore((state) => state.user);
  const enabled = useHintsEnabled(user?.id);
  if (!enabled) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`${t('hintButtonLabel')}: ${text}`}
          data-slot="beginner-hint"
          className="inline-flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          <CircleHelp className="size-3.5" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-xs">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}
