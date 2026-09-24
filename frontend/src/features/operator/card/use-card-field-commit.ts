// One `setCardField` command per field edit (D12 design decision #2, unchanged by the v2
// rewrite) — the single place every control under `features/operator/card/**` commits a value
// through. A failed command never mutates the card locally; the caller restores its own draft.
import { useCardStore } from '@/entities/card';
import type { CardFieldSpec, FactValue } from '@/entities/card';
import { t } from '@/shared/i18n';
import { setCardField, problemMessageRu, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

export type CommitResult = { ok: true } | { ok: false; message: string };
export type CommitCardField = (spec: CardFieldSpec, newValue: FactValue) => Promise<CommitResult>;

export function useCardFieldCommit(sessionId: string): CommitCardField {
  return async function commitCardField(spec, newValue) {
    try {
      const response = await setCardField(sessionId, {
        field_path: spec.field_path,
        new_value: newValue,
        client_command_id: crypto.randomUUID(),
      });
      useCardStore.getState().setCard(response.card);
      return { ok: true };
    } catch (error) {
      const message = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
      return { ok: false, message };
    }
  };
}
