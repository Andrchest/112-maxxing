// The DDS radio log (SPEC §11/§12). `listRadioMessages` projects `RADIO_MESSAGE_CREATED` events —
// there is no radio table (`docs/hld/20-db-schema.md` §20.1) — and the WS event fold keeps it live
// between fetches (`entities/radio`'s `applyRadioMessageEvent`). Rendered in log order (`seq_no`).
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { useRadioStore } from '@/entities/radio';
import { listRadioMessages, queryKeys } from '@/shared/api';

interface RadioLogProps {
  sessionId: string;
}

export function RadioLog({ sessionId }: RadioLogProps) {
  const messages = useRadioStore((state) => state.messages);

  const query = useQuery({
    queryKey: queryKeys.dds.radioMessages(sessionId),
    queryFn: () => listRadioMessages(sessionId),
  });

  useEffect(() => {
    if (query.data) {
      useRadioStore.getState().setMessages(query.data.items, query.data.last_seq_no);
    }
  }, [query.data]);

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('ddsRadioLogTitle')}</h2>
      </CardHeader>
      <CardContent>
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('ddsRadioLogEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {messages.map((message) => (
              <li key={message.radio_message_id} className="text-sm">
                <span className="font-mono text-xs text-muted-foreground">{message.from_callsign}</span>{' '}
                <span>{message.text_ru}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
