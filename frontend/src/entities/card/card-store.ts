// Entity: the trainee's live OperatorCard (SPEC §9, §3; D3, D12). Fed ONLY by the server's
// `OperatorCardView` — a command response (`setCardField`, `selectRecipientService`,
// `deselectRecipientService`) or the refresh snapshot (`getSessionSnapshot`). Nothing in this
// module ever writes a value that did not come from one of those responses: no autofill, no
// suggestion, no derived default (SPEC §9, §42 test 4; D12 design decision #1/#2).
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type OperatorCardView = components['schemas']['OperatorCardView'];
export type CardFieldSpec = components['schemas']['CardFieldSpec'];
export type FactValue = components['schemas']['FactValue'];
// I3 E3b (70 §70.5.2): the card-local `visible_when` condition and its option shape — named here
// so `card-condition.ts` and the card-form controls never re-derive them from `schema.d.ts`
// themselves (D12 design decision #1: one place per generated shape).
export type CardCondition = components['schemas']['CardCondition'];
export type CardOption = components['schemas']['CardOption'];
export type CardControl = components['schemas']['CardControl'];

interface CardStoreState {
  card: OperatorCardView | null;
  /** Replaces the card wholesale with the server's latest view (D12 design decision #1: "the
   * view is replaced by the server's response"). */
  setCard: (card: OperatorCardView | null) => void;
}

export const useCardStore = create<CardStoreState>((set) => ({
  card: null,
  setCard: (card) => set({ card }),
}));
