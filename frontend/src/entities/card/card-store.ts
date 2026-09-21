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
